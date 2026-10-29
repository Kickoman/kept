"""Landing pages, sitemap, robots.txt, icons, the HTML 404 page and compression."""
import html
import re

import pytest
from fastapi.testclient import TestClient

from app import landing

BASE = "http://testserver"


@pytest.mark.parametrize("lang,path", list(landing.PATHS.items()))
def test_landing_is_rendered_on_the_server(anon: TestClient, lang: str, path: str):
    r = anon.get(path)
    assert r.status_code == 200 and "x-robots-tag" not in r.headers
    page = r.text
    tx = landing.TEXTS[lang]
    assert f'<html lang="{lang}" data-page-lang="{lang}">' in page
    assert f"<title>{tx['title']}</title>" in page
    assert f"<h1>{tx['h1']}</h1>" in page
    assert all(html.escape(title) in page for title, _ in tx["steps"])
    assert all(html.escape(q) in page for q, _ in tx["questions"])
    assert f'<link rel="canonical" href="{BASE}{path}">' in page
    for code, href in [("en", "/"), ("ru", "/ru/"), ("be", "/be/"), ("x-default", "/")]:
        assert f'<link rel="alternate" hreflang="{code}" href="{BASE}{href}">' in page
    assert f'<meta property="og:image" content="{BASE}/static/img/og-{lang}.png">' in page
    assert '"@type": "WebSite"' in page
    assert 'href="/register"' in page and 'href="/me"' not in page
    # Only "/" sends visitors to their language version.
    assert ("location.replace" in page) == (lang == "en")
    assert "{{" not in page


def test_landing_for_a_signed_in_user(client: TestClient, user: dict):
    page = client.get("/ru/").text
    assert 'href="/me">Мои списки</a>' in page and 'href="/register"' not in page


def test_language_paths_without_slash_redirect(anon: TestClient):
    r = anon.get("/be", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/be/"


def test_sitemap_lists_every_language(anon: TestClient):
    r = anon.get("/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert re.findall(r"<loc>([^<]+)</loc>", r.text) == [f"{BASE}/", f"{BASE}/ru/", f"{BASE}/be/"]
    assert r.text.count('hreflang="x-default"') == 3


def test_robots_lets_search_engines_see_noindex_on_shared_lists(anon: TestClient):
    text = anon.get("/robots.txt").text
    everyone, ai, _ = text.split("\n\n")
    assert everyone.startswith("User-agent: *") and "Disallow: /w/" not in everyone and "Disallow: /api/" in everyone
    assert "User-agent: GPTBot" in ai and "Disallow: /w/" in ai
    assert f"Sitemap: {BASE}/sitemap.xml" in text


def test_shared_list_stays_noindex(anon: TestClient, wishlist: dict):
    r = anon.get(f"/w/{wishlist['share_token']}")
    assert r.status_code == 200 and r.headers["x-robots-tag"].startswith("noindex")


@pytest.mark.parametrize("path,media_type", [
    ("/favicon.ico", "image/x-icon"),
    ("/favicon.svg", "image/svg+xml"),
    ("/apple-touch-icon.png", "image/png"),
    ("/static/img/og-ru.png", "image/png"),
])
def test_icons_and_preview_images(anon: TestClient, path: str, media_type: str):
    r = anon.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith(media_type)


def test_unknown_page_gets_the_html_404(anon: TestClient):
    r = anon.get("/no-such-page")
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/html") and "Not found · Kept" in r.text
    r = anon.get("/api/no-such-endpoint")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_text_is_compressed_and_images_are_not(anon: TestClient):
    r = anon.get("/static/js/ui.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    r = anon.get("/static/img/og-en.png", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers
