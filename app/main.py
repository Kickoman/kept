from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import SessionLocal
from .logging_setup import RequestLogMiddleware, get_logger, setup_logging
from .routers import admin, ai, auth, items, pages, public, wishlists
from .routers.pages import STATIC_DIR
from .schemas import ConfigOut
from .services import ai_settings, images

setup_logging()
log = get_logger()
NOINDEX_PREFIXES = ("/w/", "/api/", "/media/", "/admin")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _sweep_once() -> None:
    with SessionLocal() as db:
        images.sweep_orphans(db, timedelta(hours=get_settings().media_orphan_ttl_hours))


async def _media_sweeper(every_hours: int) -> None:
    """Delete generated-but-unused images once a day (see images.sweep_orphans)."""
    while True:
        try:
            await run_in_threadpool(_sweep_once)
        except Exception as exc:  # noqa: BLE001 - a failed sweep must not kill the loop
            log.error("media_sweep_failed", error=f"{type(exc).__name__}: {exc}")
        await asyncio.sleep(every_hours * 3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    images.media_dir()
    admin.bootstrap_admins(settings.admin_set)
    sweeper = asyncio.create_task(_media_sweeper(settings.media_sweep_hours)) if settings.media_sweep_hours > 0 else None
    ai = ai_settings.get_ai_settings()
    log.info(
        "startup",
        text_provider=ai.text_provider if ai.text_ready() else "none",
        image_provider=ai.image_provider if ai.image_ready() else "none",
        db=settings.db_url.split(":", 1)[0],
        base_url=settings.base_url or "",
    )
    yield
    if sweeper is not None:
        sweeper.cancel()
    log.info("shutdown")


app = FastAPI(title="Kept wishlist", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def security_headers_and_csrf(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and request.method in MUTATING:
        if request.headers.get("x-requested-with") != "fetch":
            log.warning("csrf_rejected", reason="header", http_path=path)
            return JSONResponse({"detail": "csrf_header_missing"}, status_code=403)
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            allowed = {request.headers.get("host", "")}
            if get_settings().base_url:
                allowed.add(urlsplit(get_settings().base_url).netloc)
            if urlsplit(origin).netloc not in allowed:
                log.warning("csrf_rejected", reason="origin", origin=urlsplit(origin).netloc, http_path=path)
                return JSONResponse({"detail": "bad_origin"}, status_code=403)
    response = await call_next(request)
    if path.startswith(NOINDEX_PREFIXES):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    # Safari caches GET responses aggressively and restores pages from bfcache; make the intent explicit.
    if "cache-control" not in response.headers:
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # live, per-user data (bookings, session)
        elif path.startswith("/media/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # uuid file names never change
        else:
            response.headers["Cache-Control"] = "no-cache"  # pages and assets: keep, but revalidate (ETag) every time
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@api.get("/config", response_model=ConfigOut, tags=["meta"])
def config(request: Request) -> ConfigOut:
    settings = get_settings()
    ai = ai_settings.get_ai_settings()
    return ConfigOut(
        ai_enrich=ai.text_ready(),
        image_generation=ai.image_ready(),
        languages=["en", "ru", "be"],
        base_url=settings.public_base(request),
    )


api.include_router(auth.router)
api.include_router(wishlists.router)
api.include_router(items.router)
api.include_router(public.router)
api.include_router(ai.router)
api.include_router(admin.router)
app.include_router(api)
app.include_router(pages.router)

# Added last so it wraps everything, including the CSRF middleware above:
# rejected requests are logged like any other.
app.add_middleware(RequestLogMiddleware)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/media", StaticFiles(directory=get_settings().media_dir, check_dir=False), name="media")
