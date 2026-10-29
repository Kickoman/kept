"""The app must emit one JSON line per event on stdout, in the shape the log aggregator expects."""
import io
import json
import sys

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.logging_setup import setup_logging


@pytest.fixture
def lines(monkeypatch):
    """Capture stdout log lines. structlog writes to the sys.stdout it was configured with, so reconfigure."""
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    setup_logging()
    yield lambda: [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
    setup_logging()


def test_http_request_event_uses_route_pattern(client: TestClient, wishlist: dict, lines):
    r = client.get(f"/api/wishlists/{wishlist['id']}", headers={"x-trace-id": "abc123"})
    assert r.status_code == 200 and r.headers["x-trace-id"] == "abc123"
    evs = [e for e in lines() if e["stream"] == "http_request"]
    assert len(evs) == 1
    ev = evs[0]
    assert ev["event"] == "http_request" and ev["service"] == "wishlist-test"
    assert ev["http_method"] == "GET" and ev["http_path"] == "/api/wishlists/{wishlist_id}"
    assert ev["http_status"] == 200 and ev["duration_ms"] >= 0 and ev["level"] == "info"
    assert ev["trace_id"] == "abc123" and ev["ts"].endswith("Z") and "peer_ip" in ev
    assert ev["user_agent"] == "testclient" and "referrer_host" not in ev


def test_http_request_event_keeps_the_referring_site_host_only(client: TestClient, wishlist: dict, lines):
    path = f"/api/wishlists/{wishlist['id']}"
    client.get(path, headers={"referer": "https://t.me/somechat?x=1", "user-agent": "Mozilla/5.0 " + "x" * 300})
    client.get(path, headers={"referer": "http://testserver/w.html"})
    first, own = [e for e in lines() if e["stream"] == "http_request"]
    assert first["referrer_host"] == "t.me" and len(first["user_agent"]) == 200
    assert "referrer_host" not in own


def test_health_is_quiet_and_media_is_collapsed(client: TestClient, wishlist: dict, lines):
    assert client.get("/api/health").status_code == 200
    assert [e for e in lines() if e["stream"] == "http_request"] == []

    item = client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "x"}).json()
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "PNG")
    url = client.post(f"/api/items/{item['id']}/image", files={"file": ("x.png", buf.getvalue(), "image/png")}).json()["image_url"]
    client.get(url)
    paths = [e["http_path"] for e in lines() if e["stream"] == "http_request"]
    assert "/media/*" in paths and url not in paths
    events = [e["event"] for e in lines() if e["stream"] == "internal"]
    assert "item_created" in events and "image_uploaded" in events


def test_internal_events_and_no_raw_lines(client: TestClient, wishlist: dict, anon: TestClient, lines):
    item = client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "x", "quantity": 1}).json()
    tok = wishlist["share_token"]
    from tests.conftest import register

    register(anon, username="bob", name="Bob")
    assert anon.post(f"/api/w/{tok}/items/{item['id']}/bookings", json={}).status_code == 201
    assert anon.post(f"/api/w/{tok}/items/{item['id']}/bookings", json={}).status_code == 409
    raw = TestClient(client.app)
    assert raw.post("/api/wishlists", json={"title": "x"}).status_code == 403  # csrf
    evs = lines()
    names = [e["event"] for e in evs]
    assert "booking_created" in names and "booking_rejected" in names and "csrf_rejected" in names
    booked = next(e for e in evs if e["event"] == "booking_created")
    assert booked["quantity"] == 1 and "Bob" not in json.dumps(booked) and "claim_token" not in booked
    for ev in evs:
        assert {"ts", "service", "stream", "level", "event", "message"} <= set(ev)


def test_stdlib_logs_are_rendered_as_json(lines):
    import logging

    logging.getLogger("uvicorn.error").info("Application startup complete.")
    evs = lines()
    assert evs and evs[-1]["event"] == "log" and evs[-1]["message"] == "Application startup complete."
    assert evs[-1]["stream"] == "internal" and evs[-1]["level"] == "info"
