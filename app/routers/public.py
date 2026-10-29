from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user, require_user
from ..db import get_db
from ..logging_setup import get_logger
from ..models import Booking, Item, User, Wishlist
from ..schemas import BookingIn, BookingOut, BookingPublic, ItemPublic, WishlistPublic
from ..services import bookings as booking_svc
from ..services import images

router = APIRouter(tags=["public"])
log = get_logger()


def _wishlist_by_token(db: Session, token: str) -> Wishlist:
    wl = db.scalar(
        select(Wishlist)
        .options(selectinload(Wishlist.items), selectinload(Wishlist.owner))
        .where(Wishlist.share_token == token)
    )
    if wl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return wl


@router.get("/w/{token}", response_model=WishlistPublic)
def public_wishlist(token: str, db: Session = Depends(get_db), user: User | None = Depends(current_user)) -> WishlistPublic:
    wl = _wishlist_by_token(db, token)
    is_owner = user is not None and user.id == wl.owner_id
    items: list[ItemPublic] = []
    if is_owner:
        # Bookings are deliberately hidden from the owner: don't even load them.
        for it in wl.items:
            items.append(
                ItemPublic(
                    **images.item_out(it).model_dump(exclude={"wishlist_id"}),
                    booked_qty=0,
                    available=it.quantity,
                    my_qty=0,
                    bookings=[],
                )
            )
    else:
        rows = db.scalars(
            select(Booking).where(Booking.item_id.in_([it.id for it in wl.items])).order_by(Booking.created_at, Booking.id)
        ).all()
        by_item: dict[int, list[Booking]] = {}
        for b in rows:
            by_item.setdefault(b.item_id, []).append(b)
        for it in wl.items:
            bs = by_item.get(it.id, [])
            booked = sum(b.quantity for b in bs)
            # Guests see how much is taken, never by whom; their own bookings come back so they can cancel.
            own = [b for b in bs if user is not None and b.user_id == user.id]
            items.append(
                ItemPublic(
                    **images.item_out(it).model_dump(exclude={"wishlist_id"}),
                    booked_qty=booked,
                    available=None if it.quantity is None else max(0, it.quantity - booked),
                    my_qty=sum(b.quantity for b in own),
                    bookings=[BookingPublic(id=b.id, quantity=b.quantity, note=b.note, created_at=b.created_at) for b in own],
                )
            )
    return WishlistPublic(
        title=wl.title,
        description=wl.description,
        owner_name=wl.owner.display_name,
        is_owner=is_owner,
        updated_at=wl.updated_at,
        items=items,
    )


@router.post("/w/{token}/items/{item_id}/bookings", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def book_item(
    token: str,
    item_id: int,
    payload: BookingIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> BookingOut:
    wl = db.scalar(select(Wishlist).where(Wishlist.share_token == token))
    if wl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if user.id == wl.owner_id:
        log.info("owner_booking_blocked", wishlist_id=wl.id, item_id=item_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner_cannot_book")
    item = db.get(Item, item_id)
    if item is None or item.wishlist_id != wl.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        booking = booking_svc.create_booking(db, item, user, payload.quantity, payload.note)
    except booking_svc.NotEnough as exc:
        log.info("booking_rejected", item_id=item.id, wishlist_id=wl.id, requested=payload.quantity, available=exc.available)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "not_enough", "available": exc.available}
        ) from exc
    db.commit()
    log.info(
        "booking_created", booking_id=booking.id, item_id=item.id, wishlist_id=wl.id, quantity=booking.quantity, user_id=user.id
    )
    return BookingOut(id=booking.id, item_id=item.id, name=user.display_name, quantity=booking.quantity, note=booking.note)


@router.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)) -> Response:
    if not booking_svc.cancel_booking(db, booking_id, user.id):
        log.info("booking_cancel_rejected", booking_id=booking_id, user_id=user.id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    db.commit()
    log.info("booking_cancelled", booking_id=booking_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
