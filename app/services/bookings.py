from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Booking, Item, User


class NotEnough(ValueError):
    def __init__(self, available: int):
        super().__init__("not_enough")
        self.available = available


def booked_qty(db: Session, item_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(Booking.quantity), 0)).where(Booking.item_id == item_id)) or 0)


def booked_by_item(db: Session, item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(Booking.item_id, func.coalesce(func.sum(Booking.quantity), 0))
        .where(Booking.item_id.in_(item_ids))
        .group_by(Booking.item_id)
    ).all()
    return {int(item_id): int(total) for item_id, total in rows}


def create_booking(db: Session, item: Item, user: User, quantity: int, note: str = "") -> Booking:
    """Insert a booking if the item has room. Must run inside a write-locked transaction (see db.py)."""
    if item.quantity is not None:
        taken = booked_qty(db, item.id)
        available = max(0, item.quantity - taken)
        if quantity > available:
            raise NotEnough(available)
    # The guest's name is read from the account when shown; booker_name only exists for rows that predate accounts.
    booking = Booking(item_id=item.id, user_id=user.id, booker_name="", quantity=quantity, note=note.strip())
    db.add(booking)
    db.flush()
    return booking


def cancel_booking(db: Session, booking_id: int, user_id: int) -> bool:
    """Remove the booking if it belongs to this user."""
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user_id:
        return False
    db.delete(booking)
    return True
