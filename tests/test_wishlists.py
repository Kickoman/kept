from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import HEADERS, register


def test_crud_and_share_url(client: TestClient, user: dict):
    r = client.post("/api/wishlists", json={"title": "  Xmas ", "description": ""})
    assert r.status_code == 201
    wl = r.json()
    assert wl["title"] == "Xmas" and wl["share_url"] == f"http://testserver/w/{wl['share_token']}"

    r = client.get("/api/wishlists")
    assert [w["id"] for w in r.json()] == [wl["id"]]

    r = client.patch(f"/api/wishlists/{wl['id']}", json={"title": "New year"})
    assert r.json()["title"] == "New year"

    r = client.post(f"/api/wishlists/{wl['id']}/regenerate-token")
    assert r.json()["share_token"] != wl["share_token"]

    r = client.get(f"/api/wishlists/{wl['id']}")
    assert r.status_code == 200 and r.json()["items"] == []

    assert client.delete(f"/api/wishlists/{wl['id']}").status_code == 204
    assert client.get(f"/api/wishlists/{wl['id']}").status_code == 404


def test_isolation_between_users(client: TestClient, wishlist: dict):
    other = TestClient(app, headers=HEADERS)
    register(other, username="bob", name="Bob")
    assert other.get(f"/api/wishlists/{wishlist['id']}").status_code == 404
    assert other.patch(f"/api/wishlists/{wishlist['id']}", json={"title": "hack"}).status_code == 404
    assert other.delete(f"/api/wishlists/{wishlist['id']}").status_code == 404
    assert other.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "x"}).status_code == 404
    assert other.get("/api/wishlists").json() == []


def test_requires_auth(anon: TestClient):
    assert anon.get("/api/wishlists").status_code == 401
    assert anon.post("/api/wishlists", json={"title": "x"}).status_code == 401


def test_config_endpoint(anon: TestClient):
    r = anon.get("/api/config")
    assert r.status_code == 200
    assert r.json()["ai_enrich"] is False and r.json()["image_generation"] is False
