"""Superuser API: see everything (including guests' bookings) and clean up spam."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .. import auth as authlib
from ..auth import require_admin
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..logging_setup import get_logger
from ..models import Booking, Item, User, UserSession, Wishlist
from ..schemas import (
    AISettingsIn,
    AISettingsOut,
    AITestIn,
    AITestOut,
    AdminBookingOut,
    AdminItemOut,
    AdminPasswordOut,
    AdminStats,
    AdminUserOut,
    AdminUserPatch,
    AdminWishlistDetail,
    AdminWishlistOut,
    ItemPatch,
    MediaStats,
    MediaSweepOut,
    Page,
    WishlistPatch,
)
from ..services import ai_settings, images
from ..services.ai_providers import ProviderError
from .wishlists import share_url

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
log = get_logger()

PER_PAGE_MAX = 200


def bootstrap_admins(usernames: set[str]) -> None:
    """Grant the admin flag to accounts listed in ADMIN_USERNAMES. Called at startup."""
    if not usernames:
        return
    with SessionLocal() as db:
        result = db.execute(
            update(User).where(User.username.in_(usernames), User.is_admin.is_(False)).values(is_admin=True)
        )
        db.commit()
        log.info("admin_bootstrap", usernames=sorted(usernames), granted=result.rowcount)


def _audit(admin: User, action: str, target: str, target_id: int, **extra) -> None:
    log.info("admin_action", action=action, target=target, target_id=target_id, admin_id=admin.id, **extra)


def _paginate(page: int, per_page: int) -> tuple[int, int]:
    return max(page, 1), min(max(per_page, 1), PER_PAGE_MAX)


def _like(q: str) -> str:
    return f"%{q.strip()}%"


# ---- stats ----
@router.get("/stats", response_model=AdminStats)
def stats(db: Session = Depends(get_db)) -> AdminStats:
    now = datetime.utcnow()
    week, day = now - timedelta(days=7), now - timedelta(days=1)
    count = lambda model, *where: db.scalar(select(func.count()).select_from(model).where(*where)) or 0  # noqa: E731
    return AdminStats(
        users=count(User),
        wishlists=count(Wishlist),
        items=count(Item),
        bookings=count(Booking),
        users_7d=count(User, User.created_at >= week),
        wishlists_7d=count(Wishlist, Wishlist.created_at >= week),
        items_24h=count(Item, Item.created_at >= day),
        bookings_24h=count(Booking, Booking.created_at >= day),
    )


# ---- users ----
def _user_out(db: Session, u: User) -> AdminUserOut:
    wl_ids = select(Wishlist.id).where(Wishlist.owner_id == u.id)
    item_ids = select(Item.id).where(Item.wishlist_id.in_(wl_ids))
    return AdminUserOut(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        is_admin=u.is_admin,
        created_at=u.created_at,
        last_seen=db.scalar(select(func.max(UserSession.created_at)).where(UserSession.user_id == u.id)),
        wishlists=db.scalar(select(func.count()).select_from(Wishlist).where(Wishlist.owner_id == u.id)) or 0,
        items=db.scalar(select(func.count()).select_from(Item).where(Item.wishlist_id.in_(wl_ids))) or 0,
        bookings_received=db.scalar(select(func.count()).select_from(Booking).where(Booking.item_id.in_(item_ids))) or 0,
        sessions=db.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == u.id)) or 0,
    )


@router.get("/users", response_model=Page[AdminUserOut])
def list_users(
    q: str = "", page: int = 1, per_page: int = Query(50, le=PER_PAGE_MAX), db: Session = Depends(get_db)
) -> Page[AdminUserOut]:
    page, per_page = _paginate(page, per_page)
    stmt = select(User)
    if q.strip():
        stmt = stmt.where(or_(User.username.ilike(_like(q)), User.display_name.ilike(_like(q))))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return Page(items=[_user_out(db, u) for u in rows], total=total, page=page, per_page=per_page)


def _get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return u


def _admin_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))) or 0


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int, payload: AdminUserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> AdminUserOut:
    u = _get_user(db, user_id)
    if payload.display_name is not None:
        u.display_name = payload.display_name.strip()
    if payload.is_admin is not None and payload.is_admin != u.is_admin:
        if not payload.is_admin and u.is_admin and _admin_count(db) <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="last_admin")
        u.is_admin = payload.is_admin
    db.commit()
    _audit(admin, "user_update", "user", u.id, is_admin=u.is_admin)
    return _user_out(db, u)


@router.post("/users/{user_id}/reset-password", response_model=AdminPasswordOut)
def reset_password(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> AdminPasswordOut:
    u = _get_user(db, user_id)
    password = secrets.token_urlsafe(9)
    u.password_hash = authlib.hash_password(password)
    db.execute(delete(UserSession).where(UserSession.user_id == u.id))
    db.commit()
    _audit(admin, "password_reset", "user", u.id)
    return AdminPasswordOut(username=u.username, password=password)


@router.post("/users/{user_id}/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    u = _get_user(db, user_id)
    result = db.execute(delete(UserSession).where(UserSession.user_id == u.id))
    db.commit()
    _audit(admin, "sessions_revoked", "user", u.id, sessions=result.rowcount)


def _image_paths_for_wishlists(db: Session, wishlist_ids) -> list[str]:
    return [p for p in db.scalars(select(Item.image_path).where(Item.wishlist_id.in_(wishlist_ids), Item.image_path.is_not(None))).all()]


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    u = _get_user(db, user_id)
    if u.id == admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="self_delete")
    paths = _image_paths_for_wishlists(db, select(Wishlist.id).where(Wishlist.owner_id == u.id))
    wishlists = db.scalar(select(func.count()).select_from(Wishlist).where(Wishlist.owner_id == u.id)) or 0
    db.delete(u)
    db.commit()
    for p in paths:
        images.remove(p)
    _audit(admin, "user_delete", "user", user_id, wishlists=wishlists, images=len(paths))


# ---- wishlists ----
def _wishlist_out(db: Session, wl: Wishlist, request: Request) -> AdminWishlistOut:
    item_ids = select(Item.id).where(Item.wishlist_id == wl.id)
    return AdminWishlistOut(
        id=wl.id,
        title=wl.title,
        description=wl.description,
        owner_id=wl.owner_id,
        owner_username=wl.owner.username,
        item_count=db.scalar(select(func.count()).select_from(Item).where(Item.wishlist_id == wl.id)) or 0,
        booking_count=db.scalar(select(func.count()).select_from(Booking).where(Booking.item_id.in_(item_ids))) or 0,
        share_token=wl.share_token,
        share_url=share_url(wl.share_token, request),
        created_at=wl.created_at,
        updated_at=wl.updated_at,
    )


@router.get("/wishlists", response_model=Page[AdminWishlistOut])
def list_wishlists(
    request: Request,
    q: str = "",
    user_id: int | None = None,
    page: int = 1,
    per_page: int = Query(50, le=PER_PAGE_MAX),
    db: Session = Depends(get_db),
) -> Page[AdminWishlistOut]:
    page, per_page = _paginate(page, per_page)
    stmt = select(Wishlist).options(selectinload(Wishlist.owner))
    if user_id is not None:
        stmt = stmt.where(Wishlist.owner_id == user_id)
    if q.strip():
        stmt = stmt.join(User, User.id == Wishlist.owner_id).where(
            or_(Wishlist.title.ilike(_like(q)), Wishlist.description.ilike(_like(q)), User.username.ilike(_like(q)), Wishlist.share_token == q.strip())
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Wishlist.updated_at.desc(), Wishlist.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return Page(items=[_wishlist_out(db, wl, request) for wl in rows], total=total, page=page, per_page=per_page)


def _get_wishlist(db: Session, wishlist_id: int) -> Wishlist:
    wl = db.scalar(select(Wishlist).options(selectinload(Wishlist.owner)).where(Wishlist.id == wishlist_id))
    if wl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return wl


def _booking_out(b: Booking, item: Item, wl: Wishlist) -> AdminBookingOut:
    return AdminBookingOut(
        id=b.id,
        user_id=b.user_id,
        username=b.user.username if b.user is not None else "",
        item_id=item.id,
        item_title=item.title,
        wishlist_id=wl.id,
        wishlist_title=wl.title,
        owner_username=wl.owner.username,
        booker_name=b.user.display_name if b.user is not None else b.booker_name,  # live profile name
        quantity=b.quantity,
        note=b.note,
        created_at=b.created_at,
    )


def _item_out(item: Item, wl: Wishlist, with_bookings: bool) -> AdminItemOut:
    bookings = [_booking_out(b, item, wl) for b in item.bookings] if with_bookings else []
    return AdminItemOut(
        **images.item_out(item).model_dump(),
        wishlist_title=wl.title,
        owner_id=wl.owner_id,
        owner_username=wl.owner.username,
        booked_qty=sum(b.quantity for b in item.bookings),
        bookings=bookings,
    )


@router.get("/wishlists/{wishlist_id}", response_model=AdminWishlistDetail)
def wishlist_detail(wishlist_id: int, request: Request, db: Session = Depends(get_db)) -> AdminWishlistDetail:
    wl = db.scalar(
        select(Wishlist)
        .options(
            selectinload(Wishlist.owner),
            selectinload(Wishlist.items).selectinload(Item.bookings).selectinload(Booking.user),
        )
        .where(Wishlist.id == wishlist_id)
    )
    if wl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return AdminWishlistDetail(
        **_wishlist_out(db, wl, request).model_dump(),
        items=[_item_out(it, wl, with_bookings=True) for it in wl.items],
    )


@router.patch("/wishlists/{wishlist_id}", response_model=AdminWishlistOut)
def update_wishlist(
    wishlist_id: int, payload: WishlistPatch, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> AdminWishlistOut:
    wl = _get_wishlist(db, wishlist_id)
    if payload.title is not None:
        wl.title = payload.title.strip()
    if payload.description is not None:
        wl.description = payload.description.strip()
    db.commit()
    db.refresh(wl)
    _audit(admin, "wishlist_update", "wishlist", wl.id)
    return _wishlist_out(db, wl, request)


@router.delete("/wishlists/{wishlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_wishlist(wishlist_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    wl = _get_wishlist(db, wishlist_id)
    paths = _image_paths_for_wishlists(db, [wl.id])
    db.delete(wl)
    db.commit()
    for p in paths:
        images.remove(p)
    _audit(admin, "wishlist_delete", "wishlist", wishlist_id, images=len(paths))


# ---- items ----
@router.get("/items", response_model=Page[AdminItemOut])
def list_items(
    q: str = "",
    wishlist_id: int | None = None,
    user_id: int | None = None,
    page: int = 1,
    per_page: int = Query(50, le=PER_PAGE_MAX),
    db: Session = Depends(get_db),
) -> Page[AdminItemOut]:
    page, per_page = _paginate(page, per_page)
    stmt = select(Item).join(Wishlist, Wishlist.id == Item.wishlist_id).options(
        selectinload(Item.wishlist).selectinload(Wishlist.owner), selectinload(Item.bookings).selectinload(Booking.user)
    )
    if wishlist_id is not None:
        stmt = stmt.where(Item.wishlist_id == wishlist_id)
    if user_id is not None:
        stmt = stmt.where(Wishlist.owner_id == user_id)
    if q.strip():
        stmt = stmt.where(or_(Item.title.ilike(_like(q)), Item.description.ilike(_like(q)), Item.url.ilike(_like(q))))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Item.created_at.desc(), Item.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return Page(items=[_item_out(it, it.wishlist, with_bookings=False) for it in rows], total=total, page=page, per_page=per_page)


def _get_item(db: Session, item_id: int) -> Item:
    item = db.scalar(
        select(Item)
        .options(selectinload(Item.wishlist).selectinload(Wishlist.owner), selectinload(Item.bookings).selectinload(Booking.user))
        .where(Item.id == item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return item


@router.patch("/items/{item_id}", response_model=AdminItemOut)
def update_item(item_id: int, payload: ItemPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> AdminItemOut:
    item = _get_item(db, item_id)
    old_image = None
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
    db.commit()
    db.refresh(item)
    images.remove(old_image)
    _audit(admin, "item_update", "item", item.id, image_removed=old_image is not None)
    return _item_out(item, item.wishlist, with_bookings=True)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    item = _get_item(db, item_id)
    old_image = item.image_path
    db.delete(item)
    db.commit()
    images.remove(old_image)
    _audit(admin, "item_delete", "item", item_id)


# ---- bookings ----
@router.get("/bookings", response_model=Page[AdminBookingOut])
def list_bookings(
    q: str = "",
    wishlist_id: int | None = None,
    item_id: int | None = None,
    page: int = 1,
    per_page: int = Query(50, le=PER_PAGE_MAX),
    db: Session = Depends(get_db),
) -> Page[AdminBookingOut]:
    page, per_page = _paginate(page, per_page)
    stmt = (
        select(Booking)
        .join(Item, Item.id == Booking.item_id)
        .options(selectinload(Booking.item).selectinload(Item.wishlist).selectinload(Wishlist.owner), selectinload(Booking.user))
    )
    if wishlist_id is not None:
        stmt = stmt.where(Item.wishlist_id == wishlist_id)
    if item_id is not None:
        stmt = stmt.where(Booking.item_id == item_id)
    if q.strip():
        stmt = stmt.outerjoin(User, User.id == Booking.user_id).where(
            or_(
                User.display_name.ilike(_like(q)),
                User.username.ilike(_like(q)),
                Booking.booker_name.ilike(_like(q)),
                Booking.note.ilike(_like(q)),
                Item.title.ilike(_like(q)),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Booking.created_at.desc(), Booking.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return Page(items=[_booking_out(b, b.item, b.item.wishlist) for b in rows], total=total, page=page, per_page=per_page)


@router.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    b = db.get(Booking, booking_id)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    db.delete(b)
    db.commit()
    _audit(admin, "booking_delete", "booking", booking_id)


# ---- AI providers ----
def _tail(secret: str) -> str:
    return secret[-4:] if secret else ""


def _settings_out(s: ai_settings.AISettings) -> AISettingsOut:
    return AISettingsOut(
        text_provider=s.text_provider,
        image_provider=s.image_provider,
        anthropic_model=s.anthropic_model,
        anthropic_key_tail=_tail(s.anthropic_api_key),
        yandex_key_tail=_tail(s.yandex_api_key),
        yandex_folder_id=s.yandex_folder_id,
        yandex_text_model=s.yandex_text_model,
        yandex_art_model=s.yandex_art_model,
        text_ready=s.text_ready(),
        image_ready=s.image_ready(),
    )


@router.get("/ai-settings", response_model=AISettingsOut)
def get_ai_settings_view() -> AISettingsOut:
    return _settings_out(ai_settings.get_ai_settings())


@router.put("/ai-settings", response_model=AISettingsOut)
def update_ai_settings(payload: AISettingsIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> AISettingsOut:
    changes: dict[str, str | None] = {}
    for field in ("text_provider", "image_provider", "anthropic_model", "yandex_folder_id", "yandex_text_model", "yandex_art_model"):
        value = getattr(payload, field)
        if value is not None:
            changes[field] = value
    for field in ("anthropic_api_key", "yandex_api_key"):
        if getattr(payload, f"clear_{field}"):
            changes[field] = None
        elif getattr(payload, field):
            changes[field] = getattr(payload, field)
    s = ai_settings.save(db, changes)
    _audit(admin, "ai_settings_update", "settings", 0, fields=sorted(changes), text_provider=s.text_provider, image_provider=s.image_provider)
    return _settings_out(s)


@router.post("/ai-settings/test", response_model=AITestOut)
def test_ai_settings(payload: AITestIn, admin: User = Depends(require_admin)) -> AITestOut:
    provider = ai_settings.text_provider() if payload.kind == "text" else ai_settings.image_provider()
    if provider is None:
        return AITestOut(ok=False, detail="not_configured")
    try:
        detail = provider.check()
    except ProviderError as exc:
        log.warning("provider_error", op="test", kind_tested=payload.kind, provider=provider.name, kind=exc.kind, status=exc.status, message=exc.message, admin_id=admin.id)
        return AITestOut(ok=False, detail=f"{exc.kind}: {exc.message}")
    _audit(admin, "ai_settings_test", "settings", 0, kind=payload.kind, provider=provider.name)
    return AITestOut(ok=True, detail=detail)


# ---- media housekeeping ----
def _ttl() -> timedelta:
    return timedelta(hours=get_settings().media_orphan_ttl_hours)


@router.get("/media", response_model=MediaStats)
def media_stats(db: Session = Depends(get_db)) -> MediaStats:
    return MediaStats(**images.media_stats(db, _ttl()))


@router.post("/media/sweep", response_model=MediaSweepOut)
def media_sweep(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> MediaSweepOut:
    removed, freed = images.sweep_orphans(db, _ttl())
    _audit(admin, "media_sweep", "media", 0, removed=removed, bytes=freed)
    return MediaSweepOut(removed=removed, bytes=freed)
