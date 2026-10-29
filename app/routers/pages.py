from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Wishlist

router = APIRouter(include_in_schema=False)
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

PAGES = {
    "/": "index.html",
    "/login": "login.html",
    "/register": "register.html",
    "/me": "me.html",
    "/admin": "admin.html",
}


def _page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name, media_type="text/html")


for path, filename in PAGES.items():

    def _make(fn: str):
        def handler() -> FileResponse:
            return _page(fn)

        return handler

    router.add_api_route(path, _make(filename), methods=["GET"])


@router.get("/lists/{wishlist_id}/edit")
def edit_page(wishlist_id: int) -> FileResponse:
    return _page("edit.html")


def render_share_page(wl: Wishlist | None, request: Request) -> HTMLResponse:
    settings = get_settings()
    template = (STATIC_DIR / "w.html").read_text(encoding="utf-8")
    if wl is None:
        body = (STATIC_DIR / "404.html").read_text(encoding="utf-8")
        return HTMLResponse(body, status_code=404)
    og_title = html.escape(f"{wl.title} · Kept", quote=True)
    desc = wl.description.strip() or f"{wl.owner.display_name}'s wishlist"
    og_desc = html.escape(desc[:200], quote=True)
    og_url = html.escape(f"{settings.public_base(request)}/w/{wl.share_token}", quote=True)
    body = (
        template.replace("{{OG_TITLE}}", og_title)
        .replace("{{OG_DESCRIPTION}}", og_desc)
        .replace("{{OG_URL}}", og_url)
    )
    return HTMLResponse(body)


@router.get("/w/{token}")
def share_page(token: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    wl = db.scalar(select(Wishlist).where(Wishlist.share_token == token))
    return render_share_page(wl, request)


@router.get("/robots.txt")
def robots() -> FileResponse:
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain")
