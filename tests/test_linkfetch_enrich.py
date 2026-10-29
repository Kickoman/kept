import pytest

from app.services import enrich, linkfetch


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://user:pw@example.com/",
        "http://example.com:22/",
        "http://foo.internal/",
    ],
)
def test_validate_url_rejects(url: str):
    with pytest.raises(linkfetch.UnsafeURL):
        linkfetch.validate_url(url)


def test_validate_url_accepts_public(monkeypatch):
    monkeypatch.setattr(linkfetch.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    assert linkfetch.validate_url("https://example.com/p") == "https://example.com/p"
    monkeypatch.setattr(linkfetch.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("10.1.1.1", 443))])
    with pytest.raises(linkfetch.UnsafeURL):
        linkfetch.validate_url("https://rebind.example.com/")


HTML = b"""<!doctype html><html><head><title>Fallback title</title>
<meta property="og:title" content="Fancy Kettle 1.7L">
<meta property="og:description" content="Stainless steel kettle">
<meta property="og:image" content="/img/kettle.jpg">
<script type="application/ld+json">{"@type":"Product","name":"Fancy Kettle","offers":{"price":"49.90","priceCurrency":"EUR"}}</script>
</head><body><nav>menu</nav><p>Boils water fast.</p><script>alert(1)</script></body></html>"""


def test_parse_page_prefers_product_and_resolves_image():
    meta = enrich.parse_page("https://shop.example/p/1", HTML)
    assert meta.title == "Fancy Kettle"
    assert meta.description == "Stainless steel kettle"
    assert meta.image_url == "https://shop.example/img/kettle.jpg"
    assert meta.price == "49.90 EUR"
    assert "Boils water fast." in meta.text and "alert" not in meta.text and "menu" not in meta.text


def test_enrich_without_api_key_uses_metadata(monkeypatch):
    monkeypatch.setattr(
        linkfetch,
        "safe_fetch",
        lambda url, **k: linkfetch.FetchResult(url=url, status=200, content_type="text/html; charset=utf-8", body=HTML),
    )
    out = enrich.enrich("https://shop.example/p/1", "en")
    assert out.source == "metadata" and out.title == "Fancy Kettle"


def test_enrich_with_mocked_provider(monkeypatch):
    monkeypatch.setattr(
        linkfetch,
        "safe_fetch",
        lambda url, **k: linkfetch.FetchResult(url=url, status=200, content_type="text/html", body=HTML),
    )
    from app.services import ai_settings
    from app.services.ai_providers import ItemSuggestion, ProviderError

    class Fake:
        name = "yandex"

        def suggest(self, meta, lang):
            assert lang == "ru" and meta.title == "Fancy Kettle"
            return ItemSuggestion(title="Kettle", description="A steel kettle, 1.7 litres.")

    monkeypatch.setattr(ai_settings, "text_provider", lambda settings=None: Fake())
    out = enrich.enrich("https://shop.example/p/1", "ru")
    assert out.source == "yandex" and out.title == "Kettle" and out.image_url.endswith("kettle.jpg")

    class Broken(Fake):
        def suggest(self, meta, lang):
            raise ProviderError("quota", "429")

    monkeypatch.setattr(ai_settings, "text_provider", lambda settings=None: Broken())
    out = enrich.enrich("https://shop.example/p/1", "ru")
    assert out.source == "metadata" and out.title == "Fancy Kettle"


def test_enrich_endpoint_rejects_unsafe(client, user):
    r = client.post("/api/ai/enrich", json={"url": "http://127.0.0.1/", "lang": "en"})
    assert r.status_code == 422
    r = client.post("/api/ai/image", json={"description": "a red bike"})
    assert r.status_code == 501
