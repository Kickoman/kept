from __future__ import annotations

import io
import time
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import get_settings
from ..logging_setup import get_logger
from ..models import Item
from ..schemas import ItemOut
from . import linkfetch

log = get_logger()

MAX_SIDE = 1600
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}


class InvalidImage(ValueError):
    pass


def media_dir() -> Path:
    d = get_settings().media_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def media_url(path: str | None) -> str | None:
    return f"/media/{path}" if path else None


def item_out(item: Item) -> ItemOut:
    return ItemOut(
        id=item.id,
        wishlist_id=item.wishlist_id,
        title=item.title,
        description=item.description,
        url=item.url,
        image_url=media_url(item.image_path),
        quantity=item.quantity,
        position=item.position,
        created_at=item.created_at,
    )


def save_image_bytes(data: bytes) -> str:
    """Validate, strip metadata, resize and store as JPEG. Returns the stored file name."""
    if len(data) > get_settings().max_upload_bytes:
        raise InvalidImage("too_large")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise InvalidImage("format")
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            img = bg
        else:
            img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage("decode") from exc
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(media_dir() / name, "JPEG", quality=85, optimize=True)
    return name


def download_remote(url: str) -> str:
    """Fetch a remote image through the SSRF guard and store it. Raises InvalidImage/linkfetch errors."""
    result = linkfetch.safe_fetch(url, max_bytes=get_settings().max_upload_bytes, accept="image/*")
    return save_image_bytes(result.body)


def try_download_remote(url: str) -> str | None:
    try:
        return download_remote(url)
    except (InvalidImage, linkfetch.UnsafeURL, linkfetch.FetchError) as exc:
        log.info("remote_image_skipped", host=linkfetch.host_of(url), reason=f"{type(exc).__name__}: {exc}")
        return None


def remove(path: str | None) -> None:
    if not path:
        return
    target = media_dir() / Path(path).name
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("media_remove_failed", file=target.name, error=str(exc))


# ---- housekeeping ----
def media_files() -> list[Path]:
    return [p for p in media_dir().iterdir() if p.is_file() and p.suffix == ".jpg"]


def referenced_images(db: Session) -> set[str]:
    return {name for name in db.scalars(select(Item.image_path).where(Item.image_path.is_not(None))).all()}


def find_orphans(db: Session, older_than: timedelta = timedelta(hours=24)) -> list[Path]:
    """Media files no item points to. Generated images are written before the item is saved, so
    files younger than `older_than` are kept: they may belong to a dialog that is still open."""
    used = referenced_images(db)
    cutoff = time.time() - older_than.total_seconds()
    return [p for p in media_files() if p.name not in used and p.stat().st_mtime < cutoff]


def media_stats(db: Session, older_than: timedelta = timedelta(hours=24)) -> dict:
    files = media_files()
    used = referenced_images(db)
    orphans_all = [p for p in files if p.name not in used]
    stale = find_orphans(db, older_than)
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "orphans": len(orphans_all),
        "orphan_bytes": sum(p.stat().st_size for p in orphans_all),
        "removable": len(stale),
        "removable_bytes": sum(p.stat().st_size for p in stale),
    }


def sweep_orphans(db: Session, older_than: timedelta = timedelta(hours=24)) -> tuple[int, int]:
    """Delete stale orphan files. Returns (files removed, bytes freed)."""
    removed = freed = 0
    for path in find_orphans(db, older_than):
        try:
            size = path.stat().st_size
            path.unlink()
            removed += 1
            freed += size
        except OSError as exc:
            log.warning("media_remove_failed", file=path.name, error=str(exc))
    log.info("media_sweep", removed=removed, bytes=freed, kept=len(media_files()))
    return removed, freed


# ---- generation providers ----
def get_image_provider():
    """Active image provider (see services/ai_settings.py) or None when generation is disabled."""
    from . import ai_settings

    return ai_settings.image_provider()
