"""Turn a product/page URL into an item suggestion: page metadata, optionally polished by Claude."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..logging_setup import get_logger
from . import ai_settings, linkfetch
from .ai_providers import ItemSuggestion, PageMeta, ProviderError

log = get_logger()

MAX_PAGE_TEXT = 6000


def _first(*values: str | None) -> str | None:
    for v in values:
        if v and v.strip():
            return v.strip()
    return None


def _meta(soup: BeautifulSoup, **attrs: str) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    if tag is None:
        return None
    content = tag.get("content")
    return content.strip() if isinstance(content, str) else None


def _jsonld_product(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            graph = obj.get("@graph")
            if isinstance(graph, list):
                candidates.extend(x for x in graph if isinstance(x, dict))
            types = obj.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types:
                return obj
    return {}


def parse_page(url: str, html: bytes) -> PageMeta:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        if tag.name == "script" and tag.get("type") == "application/ld+json":
            continue
        tag.decompose()
    product = _jsonld_product(soup)
    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    price = None
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        p, cur = offers.get("price"), offers.get("priceCurrency")
        if p:
            price = f"{p} {cur or ''}".strip()
    title = _first(
        product.get("name") if isinstance(product.get("name"), str) else None,
        _meta(soup, property="og:title"),
        soup.title.get_text() if soup.title else None,
    )
    description = _first(
        product.get("description") if isinstance(product.get("description"), str) else None,
        _meta(soup, property="og:description"),
        _meta(soup, name="description"),
    )
    image_url = _first(image if isinstance(image, str) else None, _meta(soup, property="og:image"))
    if image_url:
        image_url = urljoin(url, image_url)
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:MAX_PAGE_TEXT]
    return PageMeta(url=url, title=title, description=description, image_url=image_url, price=price, text=text)


def suggest(meta: PageMeta, lang: str) -> tuple[ItemSuggestion | None, str]:
    """Ask the active text provider; returns (suggestion, provider name). Never raises: metadata is the fallback."""
    provider = ai_settings.text_provider()
    if provider is None:
        return None, "metadata"
    try:
        return provider.suggest(meta, lang), provider.name
    except ProviderError as exc:
        log.warning("provider_error", op="enrich", provider=provider.name, kind=exc.kind, status=exc.status, message=exc.message, host=linkfetch.host_of(meta.url))
        return None, "metadata"


@dataclass
class Enriched:
    title: str | None
    description: str | None
    image_url: str | None
    source: str


def enrich(url: str, lang: str) -> Enriched:
    """Raises linkfetch.UnsafeURL / linkfetch.FetchError."""
    result = linkfetch.safe_fetch(url, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5")
    if "html" not in result.content_type.lower() and not result.body.lstrip()[:15].lower().startswith(b"<!doctype html"):
        raise linkfetch.FetchError("not_html")
    meta = parse_page(result.url, result.body)
    suggestion, source = suggest(meta, lang)
    if suggestion is not None:
        return Enriched(suggestion.title[:160], suggestion.description[:4000], meta.image_url, source)
    return Enriched(
        (meta.title or "")[:160] or None,
        (meta.description or "")[:4000] or None,
        meta.image_url,
        "metadata",
    )
