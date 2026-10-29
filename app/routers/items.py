from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..config import get_settings
from ..db import get_db
from ..logging_setup import get_logger
from ..models import Item, User, Wishlist
from ..schemas import ItemIn, ItemOrderIn, ItemOut, ItemPatch
from ..services import images
from .wishlists import get_owned_wishlist

router = APIRouter(tags=["items"])
log = get_logger()


def _generated_path(name: str | None) -> str | None:
    """A file produced by /ai/image; only accepted if it really is in the media dir."""
    if not name:
        return None
    if not (images.media_dir() / name).is_file():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="image_path_unknown")
    return name


def get_owned_item(item_id: int, db: Session, user: User) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.wishlist.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return item


@router.post("/wishlists/{wishlist_id}/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def create_item(
    wishlist_id: int, payload: ItemIn, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> ItemOut:
    wl = get_owned_wishlist(wishlist_id, db, user)
    next_pos = (db.scalar(select(func.max(Item.position)).where(Item.wishlist_id == wl.id)) or 0) + 1
    image_path = _generated_path(payload.image_path) or (images.try_download_remote(payload.image_url) if payload.image_url else None)
    item = Item(
        wishlist_id=wl.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        url=payload.url,
        quantity=payload.quantity,
        position=next_pos,
        image_path=image_path,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    log.info(
        "item_created",
        item_id=item.id,
        wishlist_id=wl.id,
        has_image=image_path is not None,
        image_requested=payload.image_url is not None,
        unlimited=item.quantity is None,
        has_url=bool(item.url),
    )
    return images.item_out(item)


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(
    item_id: int, payload: ItemPatch, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> ItemOut:
    item = get_owned_item(item_id, db, user)
    old_image: str | None = None
    if payload.title is not None:
        item.title = payload.title.strip()
    if payload.description is not None:
        item.description = payload.description.strip()
    if payload.url is not None:
        item.url = payload.url or None
    if payload.unlimited:
        item.quantity = None
    elif payload.quantity is not None:
        item.quantity = payload.quantity
    if payload.remove_image and item.image_path:
        old_image, item.image_path = item.image_path, None
    if payload.image_path:
        old_image, item.image_path = item.image_path, _generated_path(payload.image_path)
    elif payload.image_url:
        new_path = images.try_download_remote(payload.image_url)
        if new_path is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="image_download_failed")
        old_image, item.image_path = item.image_path, new_path
    db.commit()
    db.refresh(item)
    images.remove(old_image)
    return images.item_out(item)


@router.post("/items/{item_id}/image", response_model=ItemOut)
def upload_image(
    item_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> ItemOut:
    item = get_owned_item(item_id, db, user)
    data = file.file.read(get_settings().max_upload_bytes + 1)
    try:
        new_path = images.save_image_bytes(data)
    except images.InvalidImage as exc:
        log.info("image_rejected", item_id=item.id, reason=str(exc), bytes=len(data))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"invalid_image:{exc}") from exc
    old_image, item.image_path = item.image_path, new_path
    db.commit()
    db.refresh(item)
    images.remove(old_image)
    log.info("image_uploaded", item_id=item.id, bytes=len(data))
    return images.item_out(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)) -> None:
    item = get_owned_item(item_id, db, user)
    old_image = item.image_path
    wishlist_id = item.wishlist_id
    db.delete(item)
    db.commit()
    images.remove(old_image)
    log.info("item_deleted", item_id=item_id, wishlist_id=wishlist_id)


@router.put("/wishlists/{wishlist_id}/items/order", response_model=list[ItemOut])
def reorder_items(
    wishlist_id: int, payload: ItemOrderIn, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> list[ItemOut]:
    wl = get_owned_wishlist(wishlist_id, db, user)
    by_id = {it.id: it for it in wl.items}
    if set(payload.item_ids) != set(by_id) or len(payload.item_ids) != len(by_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="item_ids_mismatch")
    for pos, item_id in enumerate(payload.item_ids, start=1):
        by_id[item_id].position = pos
    db.commit()
    db.expire(wl)
    wl = db.get(Wishlist, wishlist_id)
    return [images.item_out(it) for it in wl.items]
