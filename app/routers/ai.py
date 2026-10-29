from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import require_user
from ..config import get_settings
from ..logging_setup import get_logger
from ..models import User
from ..schemas import EnrichIn, EnrichOut, ImageGenIn, ImageGenOut
from ..services import enrich as enrich_svc
from ..services import images, linkfetch
from ..services.ai_providers import ProviderError
from ..services.ratelimit import RateLimiter

router = APIRouter(prefix="/ai", tags=["ai"])
log = get_logger()
_limiter = RateLimiter(limit=get_settings().ai_rate_limit_per_hour)


def _check_rate(user: User) -> None:
    if not _limiter.allow(str(user.id)):
        log.warning("rate_limited", user_id=user.id)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")


@router.post("/enrich", response_model=EnrichOut)
def enrich(payload: EnrichIn, user: User = Depends(require_user)) -> EnrichOut:
    _check_rate(user)
    started = time.perf_counter()
    host = linkfetch.host_of(payload.url)
    try:
        result = enrich_svc.enrich(payload.url, payload.lang)
    except linkfetch.UnsafeURL as exc:
        log.warning("enrich_failed", host=host, reason=f"unsafe_url:{exc}", user_id=user.id)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"unsafe_url:{exc}") from exc
    except linkfetch.FetchError as exc:
        log.info("enrich_failed", host=host, reason=f"fetch_failed:{exc}", user_id=user.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"fetch_failed:{exc}") from exc
    log.info(
        "enrich_done",
        host=host,
        source=result.source,
        lang=payload.lang,
        has_image=result.image_url is not None,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        user_id=user.id,
    )
    return EnrichOut(title=result.title, description=result.description, image_url=result.image_url, source=result.source)


IMAGE_STYLE = {
    "ru": "предметное фото на нейтральном светлом фоне, без текста и надписей",
    "be": "прадметнае фота на нейтральным светлым фоне, без тэксту",
    "en": "product photo on a neutral light background, no text",
}


@router.post("/image", response_model=ImageGenOut)
def generate_image(payload: ImageGenIn, user: User = Depends(require_user)) -> ImageGenOut:
    provider = images.get_image_provider()
    if provider is None:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="image_generation_disabled")
    subject = " ".join(p.strip() for p in (payload.title, payload.description) if p and p.strip())
    if len(subject) < 3:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty_prompt")
    _check_rate(user)
    prompt = f"{subject[:400]}. {IMAGE_STYLE.get(payload.lang, IMAGE_STYLE['en'])}"
    started = time.perf_counter()
    try:
        data = provider.generate(prompt, payload.lang)
        path = images.save_image_bytes(data)
    except ProviderError as exc:
        log.warning("provider_error", op="image", provider=provider.name, kind=exc.kind, status=exc.status, message=exc.message, user_id=user.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"provider_error:{exc.kind}") from exc
    except images.InvalidImage as exc:
        log.warning("provider_error", op="image", provider=provider.name, kind="bad_response", message=f"invalid image: {exc}", user_id=user.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="provider_error:bad_response") from exc
    log.info("image_generated", provider=provider.name, duration_ms=round((time.perf_counter() - started) * 1000, 2), bytes=len(data), user_id=user.id)
    return ImageGenOut(image_url=images.media_url(path) or "", image_path=path)
