import io
import threading

from fastapi.testclient import TestClient
from PIL import Image

from app.db import SessionLocal
from app.main import app
from app.models import Item, User
from app.services import bookings as booking_svc
from tests.conftest import HEADERS, register


def _add(client: TestClient, wl_id: int, **kw) -> dict:
    payload = {"title": "Thing", "description": "", "quantity": 1}
    payload.update(kw)
    r = client.post(f"/api/wishlists/{wl_id}/items", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_item_crud_and_order(client: TestClient, wishlist: dict):
    a = _add(client, wishlist["id"], title="A", url="https://example.com/a")
    b = _add(client, wishlist["id"], title="B", quantity=None)
    assert a["position"] == 1 and b["position"] == 2 and b["quantity"] is None

    r = client.patch(f"/api/items/{a['id']}", json={"title": "A2", "unlimited": True, "url": ""})
    assert r.json()["title"] == "A2" and r.json()["quantity"] is None and r.json()["url"] is None
    r = client.patch(f"/api/items/{a['id']}", json={"quantity": 5})
    assert r.json()["quantity"] == 5

    r = client.put(f"/api/wishlists/{wishlist['id']}/items/order", json={"item_ids": [b["id"], a["id"]]})
    assert [i["id"] for i in r.json()] == [b["id"], a["id"]]
    r = client.put(f"/api/wishlists/{wishlist['id']}/items/order", json={"item_ids": [a["id"]]})
    assert r.status_code == 422

    assert client.delete(f"/api/items/{a['id']}").status_code == 204
    r = client.get(f"/api/wishlists/{wishlist['id']}")
    assert [i["id"] for i in r.json()["items"]] == [b["id"]]


def test_image_upload_and_remove(client: TestClient, wishlist: dict, tmp_path):
    item = _add(client, wishlist["id"])
    buf = io.BytesIO()
    Image.new("RGBA", (2000, 1000), (255, 0, 0, 128)).save(buf, "PNG")
    r = client.post(f"/api/items/{item['id']}/image", files={"file": ("x.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["image_url"]
    assert url.startswith("/media/") and url.endswith(".jpg")
    got = client.get(url)
    assert got.status_code == 200 and got.headers["x-robots-tag"].startswith("noindex")
    assert Image.open(io.BytesIO(got.content)).size == (1600, 800)

    r = client.post(f"/api/items/{item['id']}/image", files={"file": ("x.txt", b"not an image", "text/plain")})
    assert r.status_code == 422

    r = client.patch(f"/api/items/{item['id']}", json={"remove_image": True})
    assert r.json()["image_url"] is None
    assert client.get(url).status_code == 404


def test_public_view_and_booking_flow(client: TestClient, wishlist: dict):
    limited = _add(client, wishlist["id"], title="Limited", quantity=2)
    unlimited = _add(client, wishlist["id"], title="Endless", quantity=None)
    token = wishlist["share_token"]

    anon = TestClient(app, headers=HEADERS)
    r = anon.get(f"/api/w/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["is_owner"] is False and body["owner_name"] == "Alice"
    assert {i["title"] for i in body["items"]} == {"Limited", "Endless"}
    # claiming requires an account
    assert anon.post(f"/api/w/{token}/items/{limited['id']}/bookings", json={"quantity": 1}).status_code == 401

    bob = TestClient(app, headers=HEADERS)
    register(bob, username="bob", name="Bob")
    eve = TestClient(app, headers=HEADERS)
    register(eve, username="eve", name="Eve")

    r = bob.post(f"/api/w/{token}/items/{limited['id']}/bookings", json={"quantity": 1, "note": "hi"})
    assert r.status_code == 201 and r.json()["name"] == "Bob" and "claim_token" not in r.json()
    bob_booking = r.json()["id"]
    r = eve.post(f"/api/w/{token}/items/{limited['id']}/bookings", json={"quantity": 2})
    assert r.status_code == 409 and r.json()["detail"]["available"] == 1
    assert eve.post(f"/api/w/{token}/items/{limited['id']}/bookings", json={"quantity": 1}).status_code == 201
    for _ in range(3):
        assert eve.post(f"/api/w/{token}/items/{unlimited['id']}/bookings", json={}).status_code == 201

    r = bob.get(f"/api/w/{token}")
    view = {i["id"]: i for i in r.json()["items"]}
    assert view[limited["id"]]["booked_qty"] == 2 and view[limited["id"]]["available"] == 0
    # only Bob's own booking comes back; Eve's is counted but never named
    assert view[limited["id"]]["my_qty"] == 1 and [b["note"] for b in view[limited["id"]]["bookings"]] == ["hi"]
    assert "Eve" not in r.text and "name" not in view[limited["id"]]["bookings"][0]
    assert view[unlimited["id"]]["booked_qty"] == 3 and view[unlimited["id"]]["available"] is None and view[unlimited["id"]]["my_qty"] == 0
    r = anon.get(f"/api/w/{token}")
    anon_view = {i["id"]: i for i in r.json()["items"]}
    assert anon_view[limited["id"]]["booked_qty"] == 2 and anon_view[limited["id"]]["bookings"] == [] and anon_view[limited["id"]]["my_qty"] == 0
    assert "Bob" not in r.text and "Eve" not in r.text and all(i["bookings"] == [] for i in r.json()["items"])
    r = eve.get(f"/api/w/{token}")
    eve_view = {i["id"]: i for i in r.json()["items"]}
    assert eve_view[limited["id"]]["my_qty"] == 1 and eve_view[unlimited["id"]]["my_qty"] == 3 and "Bob" not in r.text

    # owner sees no bookings at all, even via the public endpoint
    r = client.get(f"/api/w/{token}")
    assert r.json()["is_owner"] is True
    assert all(i["booked_qty"] == 0 and i["bookings"] == [] for i in r.json()["items"])
    assert client.post(f"/api/w/{token}/items/{limited['id']}/bookings", json={}).status_code == 403
    # owner edits are never validated against bookings
    assert client.patch(f"/api/items/{limited['id']}", json={"quantity": 1}).status_code == 200
    view = {i["id"]: i for i in bob.get(f"/api/w/{token}").json()["items"]}
    assert view[limited["id"]]["available"] == 0 and view[limited["id"]]["booked_qty"] == 2

    # cancel: only your own booking, from any device
    assert eve.delete(f"/api/bookings/{bob_booking}").status_code == 404
    assert anon.delete(f"/api/bookings/{bob_booking}").status_code == 401
    assert bob.delete(f"/api/bookings/{bob_booking}").status_code == 204
    view = {i["id"]: i for i in bob.get(f"/api/w/{token}").json()["items"]}
    assert view[limited["id"]]["booked_qty"] == 1

    # deleting an item with bookings cascades; deleting the wishlist too
    assert client.delete(f"/api/items/{limited['id']}").status_code == 204
    assert client.delete(f"/api/wishlists/{wishlist['id']}").status_code == 204
    assert anon.get(f"/api/w/{token}").status_code == 404
    with SessionLocal() as db:
        from sqlalchemy import func, select

        from app.models import Booking

        assert db.scalar(select(func.count(Booking.id))) == 0


def test_deleting_user_removes_their_bookings(client: TestClient, wishlist: dict):
    item = _add(client, wishlist["id"], quantity=None)
    bob = TestClient(app, headers=HEADERS)
    register(bob, username="bob", name="Bob")
    assert bob.post(f"/api/w/{wishlist['share_token']}/items/{item['id']}/bookings", json={}).status_code == 201
    root = TestClient(app, headers=HEADERS)
    register(root, username="root", name="Root")
    bob_id = bob.get("/api/auth/me").json()["id"]
    assert root.delete(f"/api/admin/users/{bob_id}").status_code == 204
    view = client.get(f"/api/wishlists/{wishlist['id']}").json()
    assert view["items"][0]["id"] == item["id"]
    with SessionLocal() as db:
        from sqlalchemy import func, select

        from app.models import Booking

        assert db.scalar(select(func.count(Booking.id))) == 0


def test_share_page_headers_and_og(client: TestClient, wishlist: dict, anon: TestClient):
    client.patch(f"/api/wishlists/{wishlist['id']}", json={"title": "<b>Party</b>"})
    r = anon.get(f"/w/{wishlist['share_token']}")
    assert r.status_code == 200
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert "&lt;b&gt;Party&lt;/b&gt;" in r.text and "<b>Party</b>" not in r.text
    assert anon.get("/w/nope").status_code == 404
    assert "Disallow: /w/" in anon.get("/robots.txt").text


def test_concurrent_bookings_respect_limit(client: TestClient, wishlist: dict):
    item = _add(client, wishlist["id"], quantity=3)
    results: list[str] = []
    lock = threading.Lock()

    with SessionLocal() as db:
        guests = [User(username=f"guest{n}", password_hash="x", display_name=f"Guest {n}") for n in range(12)]
        db.add_all(guests)
        db.commit()
        guest_ids = [g.id for g in guests]

    def worker(n: int) -> None:
        with SessionLocal() as db:
            it = db.get(Item, item["id"])
            guest = db.get(User, guest_ids[n])
            try:
                booking_svc.create_booking(db, it, guest, 1)
                db.commit()
                outcome = "ok"
            except booking_svc.NotEnough:
                db.rollback()
                outcome = "full"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 3 and results.count("full") == 9
    with SessionLocal() as db:
        assert booking_svc.booked_qty(db, item["id"]) == 3
