"""Cache headers: live API data is never cached, assets revalidate, media is immutable."""
import io

from fastapi.testclient import TestClient
from PIL import Image


def test_cache_control_by_path(client: TestClient, wishlist: dict, anon: TestClient):
    assert anon.get("/api/health").headers["cache-control"] == "no-store"
    assert client.get(f"/api/w/{wishlist['share_token']}").headers["cache-control"] == "no-store"
    assert anon.get(f"/w/{wishlist['share_token']}").headers["cache-control"] == "no-cache"
    assert anon.get("/").headers["cache-control"] == "no-cache"
    r = anon.get("/static/css/app.css")
    assert r.headers["cache-control"] == "no-cache" and "etag" in r.headers

    item = client.post(f"/api/wishlists/{wishlist['id']}/items", json={"title": "x"}).json()
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    url = client.post(f"/api/items/{item['id']}/image", files={"file": ("x.png", buf.getvalue(), "image/png")}).json()["image_url"]
    assert anon.get(url).headers["cache-control"] == "public, max-age=31536000, immutable"
