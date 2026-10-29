from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import require_user
from ..config import get_settings
from ..db import get_db
from ..logging_setup import get_logger
from ..models import Item, User, Wishlist
from ..schemas import WishlistDetail, WishlistIn, WishlistPatch, WishlistSummary
from ..services import images

router = APIRouter(prefix="/wishlists", tags=["wishlists"])
log = get_logger()


def new_share_token() -> str:
    return secrets.token_urlsafe(16)


def share_url(token: str, request: Request) -> str:
    return f"{get_settings().public_base(request)}/w/{token}"


def get_owned_wishlist(wishlist_id: int, db: Session, user: User) -> Wishlist:
    wl = db.get(Wishlist, wishlist_id)
    if wl is None or wl.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return wl


def summary(wl: Wishlist, item_count: int, request: Request) -> WishlistSummary:
    return WishlistSummary(
        id=wl.id,
        title=wl.title,
        description=wl.description,
        share_token=wl.share_token,
        share_url=share_url(wl.share_token, request),
        item_count=item_count,
        created_at=wl.created_at,
        updated_at=wl.updated_at,
    )


def detail(wl: Wishlist, request: Request) -> WishlistDetail:
    return WishlistDetail(
        **summary(wl, len(wl.items), request).model_dump(),
        items=[images.item_out(it) for it in wl.items],
    )


@router.get("", response_model=list[WishlistSummary])
def list_wishlists(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> list[WishlistSummary]:
    counts = dict(
        db.execute(
            select(Item.wishlist_id, func.count(Item.id))
            .join(Wishlist, Wishlist.id == Item.wishlist_id)
            .where(Wishlist.owner_id == user.id)
            .group_by(Item.wishlist_id)
        ).all()
    )
    rows = db.scalars(
        select(Wishlist).where(Wishlist.owner_id == user.id).order_by(Wishlist.created_at.desc(), Wishlist.id.desc())
    ).all()
    return [summary(wl, counts.get(wl.id, 0), request) for wl in rows]


@router.post("", response_model=WishlistSummary, status_code=status.HTTP_201_CREATED)
def create_wishlist(
    payload: WishlistIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> WishlistSummary:
    wl = Wishlist(
        owner_id=user.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        share_token=new_share_token(),
    )
    db.add(wl)
    db.commit()
    db.refresh(wl)
    log.info("wishlist_created", wishlist_id=wl.id, user_id=user.id)
    return summary(wl, 0, request)


@router.get("/{wishlist_id}", response_model=WishlistDetail)
def get_wishlist(
    wishlist_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> WishlistDetail:
    wl = db.scalar(
        select(Wishlist).options(selectinload(Wishlist.items)).where(Wishlist.id == wishlist_id)
    )
    if wl is None or wl.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return detail(wl, request)


@router.patch("/{wishlist_id}", response_model=WishlistSummary)
def update_wishlist(
    wishlist_id: int,
    payload: WishlistPatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> WishlistSummary:
    wl = get_owned_wishlist(wishlist_id, db, user)
    if payload.title is not None:
        wl.title = payload.title.strip()
    if payload.description is not None:
        wl.description = payload.description.strip()
    db.commit()
    db.refresh(wl)
    count = db.scalar(select(func.count(Item.id)).where(Item.wishlist_id == wl.id)) or 0
    return summary(wl, count, request)


@router.delete("/{wishlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_wishlist(wishlist_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)) -> None:
    wl = get_owned_wishlist(wishlist_id, db, user)
    paths = [it.image_path for it in wl.items if it.image_path]
    item_count = len(wl.items)
    db.delete(wl)
    db.commit()
    for p in paths:
        images.remove(p)
    log.info("wishlist_deleted", wishlist_id=wishlist_id, user_id=user.id, item_count=item_count)


@router.post("/{wishlist_id}/regenerate-token", response_model=WishlistSummary)
def regenerate_token(
    wishlist_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> WishlistSummary:
    wl = get_owned_wishlist(wishlist_id, db, user)
    wl.share_token = new_share_token()
    db.commit()
    db.refresh(wl)
    log.info("share_token_regenerated", wishlist_id=wl.id, user_id=user.id)
    count = db.scalar(select(func.count(Item.id)).where(Item.wishlist_id == wl.id)) or 0
    return summary(wl, count, request)
