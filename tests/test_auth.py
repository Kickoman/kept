from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import HEADERS, register


def test_register_login_logout(client: TestClient):
    me = register(client)
    assert me["username"] == "alice"
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["display_name"] == "Alice"

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/login", json={"username": "ALICE", "password": "password123"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_duplicate_username_and_bad_password(client: TestClient):
    register(client)
    r = client.post("/api/auth/register", json={"username": "Alice", "password": "password123", "display_name": "A"})
    assert r.status_code == 409
    r = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"})
    assert r.status_code == 401
    r = client.post("/api/auth/register", json={"username": "bob", "password": "short", "display_name": "B"})
    assert r.status_code == 422


def test_csrf_header_required():
    raw = TestClient(app)
    r = raw.post("/api/auth/register", json={"username": "x1", "password": "password123", "display_name": "X"})
    assert r.status_code == 403
    r = raw.post(
        "/api/auth/register",
        json={"username": "x1", "password": "password123", "display_name": "X"},
        headers={"X-Requested-With": "fetch", "Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_session_cookie_flags(client: TestClient):
    r = client.post("/api/auth/register", json={"username": "carol", "password": "password123", "display_name": "C"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_profile_and_change_password(client: TestClient, user: dict):
    r = client.patch("/api/auth/me", json={"display_name": "  Alice Cooper "})
    assert r.status_code == 200 and r.json()["display_name"] == "Alice Cooper"

    other = TestClient(app, headers=HEADERS)
    assert other.post("/api/auth/login", json={"username": "alice", "password": "password123"}).status_code == 200

    assert client.post("/api/auth/change-password", json={"current_password": "nope-nope", "new_password": "newpassword1"}).status_code == 401
    assert client.post("/api/auth/change-password", json={"current_password": "password123", "new_password": "short"}).status_code == 422
    assert client.post("/api/auth/change-password", json={"current_password": "password123", "new_password": "newpassword1"}).status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # this session survives
    assert other.get("/api/auth/me").status_code == 401  # other sessions are closed
    assert other.post("/api/auth/login", json={"username": "alice", "password": "password123"}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "alice", "password": "newpassword1"}).status_code == 200
