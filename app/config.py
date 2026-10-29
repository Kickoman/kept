from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = "dev-secret-change-me"
    data_dir: Path = Path("./data")
    database_url: str | None = None
    # Optional public origin override (e.g. https://kept.example). When unset, links are derived from each request.
    base_url: str | None = None
    # AI provider defaults; the admin UI (app_settings table) overrides these.
    text_provider: str = "none"
    image_provider: str = "none"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    yandex_api_key: str | None = None
    yandex_folder_id: str | None = None
    session_ttl_days: int = 30
    max_upload_bytes: int = 5 * 1024 * 1024
    fetch_max_bytes: int = 2 * 1024 * 1024
    fetch_timeout_seconds: float = 10.0
    ai_rate_limit_per_hour: int = 60
    # Orphan media cleanup: run every N hours (0 = off); files younger than the TTL are never touched.
    media_sweep_hours: int = 24
    media_orphan_ttl_hours: int = 24
    # Comma-separated usernames that get the admin flag at startup / registration.
    admin_usernames: str = ""

    @property
    def admin_set(self) -> set[str]:
        return {u.strip().lower() for u in self.admin_usernames.split(",") if u.strip()}

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'wishlist.db').as_posix()}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def public_base(self, request) -> str:
        """Origin used in share links and OG tags.

        BASE_URL wins when configured. Otherwise the origin is rebuilt from the
        request: uvicorn runs with --no-proxy-headers (so request.client stays
        the real peer for logging), which means X-Forwarded-Proto/Host from the
        reverse proxy are read here explicitly.
        """
        if self.base_url:
            return self.base_url.rstrip("/")
        return f"{request_scheme(request)}://{request_host(request)}"

    def cookie_secure(self, request) -> bool:
        if self.base_url:
            return self.base_url.lower().startswith("https://")
        return request_scheme(request) == "https"



@lru_cache
def get_settings() -> Settings:
    return Settings()


def request_scheme(request) -> str:
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return forwarded if forwarded in ("http", "https") else request.url.scheme


def request_host(request) -> str:
    forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    return forwarded or request.headers.get("host") or request.url.netloc
