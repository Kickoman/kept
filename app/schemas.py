from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict, Field, HttpUrl, field_serializer, field_validator


class BaseModel(_BaseModel):
    """All API models: timestamps are emitted as UTC ISO-8601 with a trailing Z (sqlite drops tzinfo)."""

    @field_serializer("created_at", "updated_at", "last_seen", check_fields=False)
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---- auth ----
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("username")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be blank")
        return v


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    is_admin: bool = False


class ProfilePatch(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be blank")
        return v


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


# ---- wishlists ----
class WishlistIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class WishlistPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class WishlistSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    share_token: str
    share_url: str
    item_count: int
    created_at: datetime
    updated_at: datetime


# ---- items ----
class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    url: str | None = Field(default=None, max_length=2048)
    # None = unlimited
    quantity: int | None = Field(default=1, ge=1, le=100000)
    # Remote image to download server-side (e.g. og:image suggested by /ai/enrich).
    image_url: str | None = Field(default=None, max_length=2048)
    # A generated image already stored in media (returned by /ai/image).
    image_path: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}\.jpg$")

    @field_validator("url", "image_url")
    @classmethod
    def _clean_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        HttpUrl(v)  # validates scheme/host
        return v


class ItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    url: str | None = Field(default=None, max_length=2048)
    quantity: int | None = Field(default=None, ge=1, le=100000)
    unlimited: bool | None = None
    remove_image: bool | None = None
    image_url: str | None = Field(default=None, max_length=2048)
    image_path: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}\.jpg$")

    @field_validator("url", "image_url")
    @classmethod
    def _clean_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return ""
        HttpUrl(v)
        return v


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    wishlist_id: int
    title: str
    description: str
    url: str | None
    image_url: str | None
    quantity: int | None
    position: int
    created_at: datetime


class ItemOrderIn(BaseModel):
    item_ids: list[int] = Field(min_length=0, max_length=1000)


class WishlistDetail(WishlistSummary):
    items: list[ItemOut]


# ---- public / bookings ----
class BookingPublic(BaseModel):
    """One of the viewer's own bookings. Other guests' bookings are never listed: only the totals are."""

    id: int
    quantity: int
    note: str
    created_at: datetime


class ItemPublic(BaseModel):
    id: int
    title: str
    description: str
    url: str | None
    image_url: str | None
    quantity: int | None
    position: int
    created_at: datetime
    booked_qty: int  # everyone's bookings together; who made them stays private
    available: int | None  # None = unlimited
    my_qty: int
    bookings: list[BookingPublic]  # the viewer's own only


class WishlistPublic(BaseModel):
    title: str
    description: str
    owner_name: str
    is_owner: bool
    updated_at: datetime
    items: list[ItemPublic]


class BookingIn(BaseModel):
    quantity: int = Field(default=1, ge=1, le=100000)
    note: str = Field(default="", max_length=500)


class BookingOut(BaseModel):
    id: int
    item_id: int
    name: str
    quantity: int
    note: str


# ---- misc ----
class ConfigOut(BaseModel):
    ai_enrich: bool
    image_generation: bool
    languages: list[str]
    base_url: str


class EnrichIn(BaseModel):
    url: str = Field(max_length=2048)
    lang: str = Field(default="en", pattern=r"^[a-z]{2}$")


class EnrichOut(BaseModel):
    title: str | None
    description: str | None
    image_url: str | None
    source: str  # "ai" | "metadata"


class ImageGenIn(BaseModel):
    title: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)
    lang: str = Field(default="en", pattern=r"^[a-z]{2}$")


class ImageGenOut(BaseModel):
    image_url: str
    image_path: str


class AISettingsOut(BaseModel):
    text_provider: str
    image_provider: str
    anthropic_model: str
    anthropic_key_tail: str
    yandex_key_tail: str
    yandex_folder_id: str
    yandex_text_model: str
    yandex_art_model: str
    text_ready: bool
    image_ready: bool


class AISettingsIn(BaseModel):
    text_provider: str | None = Field(default=None, pattern=r"^(none|anthropic|yandex)$")
    image_provider: str | None = Field(default=None, pattern=r"^(none|yandex)$")
    anthropic_api_key: str | None = None  # "" keeps, None (explicit null) clears -- see clear_* flags
    anthropic_model: str | None = Field(default=None, max_length=80)
    yandex_api_key: str | None = None
    yandex_folder_id: str | None = Field(default=None, max_length=64)
    yandex_text_model: str | None = Field(default=None, max_length=80)
    yandex_art_model: str | None = Field(default=None, max_length=80)
    clear_anthropic_api_key: bool = False
    clear_yandex_api_key: bool = False


class AITestIn(BaseModel):
    kind: str = Field(pattern=r"^(text|image)$")


class AITestOut(BaseModel):
    ok: bool
    detail: str


# ---- admin ----
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int


class AdminStats(BaseModel):
    users: int
    wishlists: int
    items: int
    bookings: int
    users_7d: int
    wishlists_7d: int
    items_24h: int
    bookings_24h: int


class AdminUserOut(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool
    created_at: datetime
    last_seen: datetime | None
    wishlists: int
    items: int
    bookings_received: int
    sessions: int


class AdminUserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    is_admin: bool | None = None


class AdminPasswordOut(BaseModel):
    username: str
    password: str


class AdminBookingOut(BaseModel):
    id: int
    user_id: int | None
    username: str
    item_id: int
    item_title: str
    wishlist_id: int
    wishlist_title: str
    owner_username: str
    booker_name: str
    quantity: int
    note: str
    created_at: datetime


class AdminItemOut(ItemOut):
    wishlist_title: str
    owner_id: int
    owner_username: str
    booked_qty: int
    bookings: list[AdminBookingOut] = []


class AdminWishlistOut(BaseModel):
    id: int
    title: str
    description: str
    owner_id: int
    owner_username: str
    item_count: int
    booking_count: int
    share_token: str
    share_url: str
    created_at: datetime
    updated_at: datetime


class AdminWishlistDetail(AdminWishlistOut):
    items: list[AdminItemOut]


class MediaStats(BaseModel):
    files: int
    bytes: int
    orphans: int
    orphan_bytes: int
    removable: int
    removable_bytes: int


class MediaSweepOut(BaseModel):
    removed: int
    bytes: int
