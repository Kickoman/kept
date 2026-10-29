from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="kept-test-"))
os.environ["DATA_DIR"] = str(_tmp)
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["BASE_URL"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["IMAGE_PROVIDER"] = "none"
os.environ["SERVICE_NAME"] = "wishlist-test"
os.environ["ADMIN_USERNAMES"] = "root"
os.environ["LOG_LEVEL"] = "info"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

HEADERS = {"X-Requested-With": "fetch"}


@pytest.fixture(autouse=True)
def _fresh_db():
    from app.services import ai_settings

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ai_settings.invalidate()
    media = _tmp / "media"
    if media.is_dir():
        for f in media.iterdir():
            f.unlink()
    yield
    ai_settings.invalidate()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, headers=HEADERS)


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app, headers=HEADERS)


def register(client: TestClient, username: str = "alice", password: str = "password123", name: str = "Alice") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": password, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def user(client: TestClient) -> dict:
    return register(client)


@pytest.fixture
def wishlist(client: TestClient, user: dict) -> dict:
    r = client.post("/api/wishlists", json={"title": "Birthday", "description": "Things I like"})
    assert r.status_code == 201, r.text
    return r.json()
