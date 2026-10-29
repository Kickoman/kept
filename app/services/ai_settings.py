"""Which AI providers are active and their credentials: admin-editable, stored in `app_settings`, env as defaults."""
from __future__ import annotations

import threading
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import engine
from ..models import AppSetting
from . import ai_providers as providers

TextProviderName = Literal["none", "anthropic", "yandex"]
ImageProviderName = Literal["none", "yandex"]
SECRET_FIELDS = ("anthropic_api_key", "yandex_api_key")


class AISettings(BaseModel):
    text_provider: TextProviderName = "none"
    image_provider: ImageProviderName = "none"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_text_model: str = "yandexgpt-lite/latest"
    yandex_art_model: str = "aliceai-image-art-3.0"

    def text_ready(self) -> bool:
        if self.text_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.text_provider == "yandex":
            return bool(self.yandex_api_key and self.yandex_folder_id)
        return False

    def image_ready(self) -> bool:
        return self.image_provider == "yandex" and bool(self.yandex_api_key and self.yandex_folder_id)


def _env_defaults() -> AISettings:
    s = get_settings()
    return AISettings(
        text_provider=s.text_provider,  # type: ignore[arg-type]
        image_provider=s.image_provider,  # type: ignore[arg-type]
        anthropic_api_key=s.anthropic_api_key or "",
        anthropic_model=s.anthropic_model,
        yandex_api_key=s.yandex_api_key or "",
        yandex_folder_id=s.yandex_folder_id or "",
    )


_lock = threading.Lock()
_cache: AISettings | None = None


def _merge(rows) -> AISettings:
    values = _env_defaults().model_dump()
    for key, value in rows:
        field = key[3:]
        if field in values:
            values[field] = value
    return AISettings.model_validate(values)


def load(db: Session) -> AISettings:
    rows = db.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.like("ai.%"))).all()
    return _merge(rows)


def _load_raw() -> AISettings:
    # A plain read outside any ORM transaction: every SQLAlchemy transaction here starts with
    # BEGIN IMMEDIATE (see db.py), and a request that already holds that lock would deadlock
    # against a second session opened just to read the settings.
    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM app_settings WHERE key LIKE 'ai.%'")
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return _merge(rows)


def get_ai_settings() -> AISettings:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load_raw()
        return _cache


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def save(db: Session, changes: dict[str, str | None]) -> AISettings:
    """Persist changed fields. For secrets: "" means keep, None means clear."""
    for field, value in changes.items():
        if field not in AISettings.model_fields:
            continue
        if field in SECRET_FIELDS and value == "":
            continue
        value = "" if value is None else str(value).strip()
        row = db.get(AppSetting, f"ai.{field}")
        if row is None:
            db.add(AppSetting(key=f"ai.{field}", value=value))
        else:
            row.value = value
    db.commit()
    invalidate()
    return load(db)


def text_provider(settings: AISettings | None = None) -> providers.TextProvider | None:
    s = settings or get_ai_settings()
    if not s.text_ready():
        return None
    if s.text_provider == "anthropic":
        return providers.AnthropicText(s.anthropic_api_key, s.anthropic_model)
    return providers.YandexGPTText(s.yandex_api_key, s.yandex_folder_id, s.yandex_text_model)


def image_provider(settings: AISettings | None = None) -> providers.ImageProvider | None:
    s = settings or get_ai_settings()
    if not s.image_ready():
        return None
    return providers.YandexArtImage(s.yandex_api_key, s.yandex_folder_id, s.yandex_art_model)
