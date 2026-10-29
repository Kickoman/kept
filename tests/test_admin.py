import io

from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.main import app
from app.routers.admin import bootstrap_admins
from tests.conftest import HEADERS, register


def admin_client() -> TestClient:
    c = TestClient(app, headers=HEADERS)
    register(c, username="root", password="password123", name="Root")  # ADMIN_USERNAMES=root in conftest
    return c


def test_admin_flag_from_env_and_access(client: TestClient, anon: TestClient):
    root = admin_client()
    assert root.get("/api/auth/me").json()["is_admin"] is True
    register(client)  # alice, not admin
    assert client.get("/api/auth/me").json()["is_admin"] is False
    assert client.get("/api/admin/stats").status_code == 403
    assert anon.get("/api/admin/stats").status_code == 401
    r = root.get("/api/admin/stats")
    assert r.status_code == 200 and r.json()["users"] == 2


def test_bootstrap_grants_existing_user(client: TestClient):
    register(client, username="root")
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        u = db.query(User).filter_by(username="root").one()
        u.is_admin = False
        db.commit()
    bootstrap_admins(get_settings().admin_set)
    assert client.get("/api/auth/me").json()["is_admin"] is True


def test_lists_search_detail_and_cleanup(client: TestClient, wishlist: dict):
    root = admin_client()
    item = client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "Spam kettle", "quantity": 2}).json()
    buf = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buf, "PNG")
    item = client.post(f"/api/items/{item['id']}/image", files={"file": ("x.png", buf.getvalue(), "image/png")}).json()
    guest = TestClient(app, headers=HEADERS)
    register(guest, username="priya", name="Priya")
    tok = wishlist["share_token"]
    guest.post(f"/api/w/{tok}/items/{item['id']}/bookings", json={"quantity": 1, "note": "hi"})

    users = root.get("/api/admin/users?q=alice").json()
    assert users["total"] == 1 and users["items"][0]["username"] == "alice"
    assert users["items"][0]["wishlists"] == 1 and users["items"][0]["items"] == 1 and users["items"][0]["bookings_received"] == 1

    wls = root.get("/api/admin/wishlists?q=birth").json()
    assert wls["total"] == 1 and wls["items"][0]["owner_username"] == "alice" and wls["items"][0]["booking_count"] == 1
    assert root.get(f"/api/admin/wishlists?user_id={users['items'][0]['id']}").json()["total"] == 1

    detail = root.get(f"/api/admin/wishlists/{wishlist['id']}").json()
    assert detail["items"][0]["bookings"][0]["booker_name"] == "Priya"  # admin sees guests' claims

    items = root.get("/api/admin/items?q=kettle").json()
    assert items["total"] == 1 and items["items"][0]["booked_qty"] == 1
    bookings = root.get("/api/admin/bookings?q=priya").json()
    assert bookings["total"] == 1 and bookings["items"][0]["note"] == "hi" and bookings["items"][0]["username"] == "priya"
    assert bookings["items"][0]["booker_name"] == "Priya"
    # the name shown is the live profile name, not a snapshot taken at booking time
    guest.patch("/api/auth/me", json={"display_name": "Priya K."})
    assert root.get("/api/admin/bookings").json()["items"][0]["booker_name"] == "Priya K."
    assert root.get("/api/admin/bookings?q=Priya%20K").json()["total"] == 1
    assert root.get(f"/api/admin/wishlists/{wishlist['id']}").json()["items"][0]["bookings"][0]["booker_name"] == "Priya K."

    # edits
    r = root.patch(f"/api/admin/wishlists/{wishlist['id']}", json={"title": "Clean title"})
    assert r.json()["title"] == "Clean title"
    r = root.patch(f"/api/admin/items/{item['id']}", json={"title": "Kettle", "remove_image": True})
    assert r.json()["title"] == "Kettle" and r.json()["image_url"] is None
    assert client.get(item["image_url"]).status_code == 404
    r = root.patch(f"/api/admin/users/{users['items'][0]['id']}", json={"display_name": "Alice B"})
    assert r.json()["display_name"] == "Alice B"

    # delete a booking, then the whole user (cascade)
    assert root.delete(f"/api/admin/bookings/{bookings['items'][0]['id']}").status_code == 204
    assert root.get("/api/admin/bookings").json()["total"] == 0
    assert root.delete(f"/api/admin/users/{users['items'][0]['id']}").status_code == 204
    assert root.get("/api/admin/wishlists").json()["total"] == 0
    assert root.get("/api/admin/items").json()["total"] == 0
    assert client.get("/api/auth/me").status_code == 401


def test_password_reset_logout_and_guards(client: TestClient, user: dict):
    root = admin_client()
    r = root.post(f"/api/admin/users/{user['id']}/reset-password")
    assert r.status_code == 200
    new_pw = r.json()["password"]
    assert client.get("/api/auth/me").status_code == 401  # sessions revoked
    assert client.post("/api/auth/login", json={"username": "alice", "password": "password123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "alice", "password": new_pw}).status_code == 200
    assert root.post(f"/api/admin/users/{user['id']}/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    me = root.get("/api/auth/me").json()
    assert root.delete(f"/api/admin/users/{me['id']}").status_code == 409
    assert root.patch(f"/api/admin/users/{me['id']}", json={"is_admin": False}).status_code == 409
    r = root.patch(f"/api/admin/users/{user['id']}", json={"is_admin": True})
    assert r.json()["is_admin"] is True
    assert root.patch(f"/api/admin/users/{me['id']}", json={"is_admin": False}).status_code == 200


def test_admin_page_and_robots(anon: TestClient):
    r = anon.get("/admin")
    assert r.status_code == 200 and r.headers["x-robots-tag"].startswith("noindex")
    assert "Disallow: /admin" in anon.get("/robots.txt").text


def test_ai_settings_roundtrip_and_masking(client: TestClient, wishlist: dict, monkeypatch):
    root = admin_client()
    s = root.get("/api/admin/ai-settings").json()
    assert s["text_provider"] == "none" and s["yandex_key_tail"] == "" and s["text_ready"] is False
    assert client.get("/api/admin/ai-settings").status_code == 403

    r = root.put("/api/admin/ai-settings", json={"text_provider": "yandex", "image_provider": "yandex", "yandex_api_key": "AQVNsecret1234", "yandex_folder_id": "b1gfolder"})
    s = r.json()
    assert s["text_ready"] and s["image_ready"] and s["yandex_key_tail"] == "1234" and "AQVN" not in r.text
    cfg = client.get("/api/config").json()
    assert cfg["ai_enrich"] is True and cfg["image_generation"] is True

    # empty key keeps the stored one; explicit clear removes it and the provider stops being ready
    s = root.put("/api/admin/ai-settings", json={"yandex_api_key": "", "yandex_text_model": "yandexgpt/latest"}).json()
    assert s["yandex_key_tail"] == "1234" and s["yandex_text_model"] == "yandexgpt/latest"
    s = root.put("/api/admin/ai-settings", json={"clear_yandex_api_key": True}).json()
    assert s["yandex_key_tail"] == "" and s["text_ready"] is False
    assert client.get("/api/config").json()["ai_enrich"] is False
    assert root.post("/api/admin/ai-settings/test", json={"kind": "text"}).json() == {"ok": False, "detail": "not_configured"}

    # test endpoint reports provider errors instead of raising
    from app.services import ai_providers, ai_settings

    class Broken:
        name = "yandex"

        def check(self):
            raise ai_providers.ProviderError("auth", "HTTP 403: denied", 403)

    monkeypatch.setattr(ai_settings, "text_provider", lambda settings=None: Broken())
    r = root.post("/api/admin/ai-settings/test", json={"kind": "text"}).json()
    assert r["ok"] is False and r["detail"].startswith("auth:")


def test_generated_image_attach(client: TestClient, wishlist: dict, monkeypatch):
    import io

    from PIL import Image

    from app.services import ai_settings

    class FakeArt:
        name = "yandex"

        def generate(self, prompt, lang):
            assert "Kettle" in prompt
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, "PNG")
            return buf.getvalue()

    monkeypatch.setattr(ai_settings, "image_provider", lambda settings=None: FakeArt())
    r = client.post("/api/ai/image", json={"title": "Kettle", "description": "steel", "lang": "en"})
    assert r.status_code == 200, r.text
    path = r.json()["image_path"]
    assert r.json()["image_url"] == f"/media/{path}"
    item = client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "Kettle", "image_path": path}).json()
    assert item["image_url"] == f"/media/{path}"
    assert client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "x", "image_path": "0" * 32 + ".jpg"}).status_code == 422
    assert client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "x", "image_path": "../etc/passwd"}).status_code == 422
    monkeypatch.setattr(ai_settings, "image_provider", lambda settings=None: None)
    assert client.post("/api/ai/image", json={"title": "Kettle"}).status_code == 501


def test_media_stats_and_sweep(client: TestClient, wishlist: dict):
    import os
    import time
    from datetime import timedelta

    from PIL import Image

    from app.db import SessionLocal
    from app.services import images

    root = admin_client()
    item = client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "x"}).json()
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    used = client.post(f"/api/items/{item['id']}/image", files={"file": ("x.png", buf.getvalue(), "image/png")}).json()["image_url"].split("/")[-1]
    fresh = images.save_image_bytes(buf.getvalue())
    stale = images.save_image_bytes(buf.getvalue())
    old = time.time() - 3 * 24 * 3600
    os.utime(images.media_dir() / stale, (old, old))

    assert client.get("/api/admin/media").status_code == 403
    m = root.get("/api/admin/media").json()
    assert m["files"] == 3 and m["orphans"] == 2 and m["removable"] == 1 and m["removable_bytes"] > 0

    r = root.post("/api/admin/media/sweep").json()
    assert r["removed"] == 1 and r["bytes"] > 0
    names = {p.name for p in images.media_files()}
    assert names == {used, fresh}

    with SessionLocal() as db:  # a zero TTL removes the fresh orphan too, never the used file
        removed, freed = images.sweep_orphans(db, timedelta(0))
    assert removed == 1 and freed > 0
    assert {p.name for p in images.media_files()} == {used}
