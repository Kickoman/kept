"""Outbound HTTP with an SSRF guard. Every fetch of a user-supplied URL goes through safe_fetch()."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import get_settings
from ..logging_setup import get_logger

log = get_logger()

MAX_REDIRECTS = 5
USER_AGENT = "Mozilla/5.0 (compatible; KeptWishlist/1.0)"


class UnsafeURL(ValueError):
    """The URL points somewhere we refuse to fetch."""


class FetchError(RuntimeError):
    """The remote fetch failed or exceeded limits."""


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    content_type: str
    body: bytes


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    )


def host_of(url: str) -> str:
    """Hostname for logs: enough to see which shops are used, without the full (possibly personal) URL."""
    try:
        return urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""


def validate_url(url: str) -> str:
    """Return the normalized URL or raise UnsafeURL. Resolves DNS and rejects non-public addresses."""
    try:
        return _validate_url(url)
    except UnsafeURL as exc:
        log.info("unsafe_url_rejected", host=host_of(url), reason=str(exc))
        raise


def _validate_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("scheme")
    host = parts.hostname
    if not host:
        raise UnsafeURL("host")
    if parts.username or parts.password:
        raise UnsafeURL("credentials")
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURL("host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in (80, 443, 8080, 8443):
        raise UnsafeURL("port")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_forbidden_ip(literal):
            raise UnsafeURL("ip")
        return url
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL("dns") from exc
    if not infos:
        raise UnsafeURL("dns")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_forbidden_ip(ip):
            raise UnsafeURL("ip")
    return url


def safe_fetch(url: str, *, max_bytes: int | None = None, accept: str = "*/*") -> FetchResult:
    settings = get_settings()
    limit = max_bytes or settings.fetch_max_bytes
    current = validate_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en,ru;q=0.8"}
    with httpx.Client(follow_redirects=False, timeout=settings.fetch_timeout_seconds, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError("redirect_without_location")
                        current = validate_url(urljoin(current, location))
                        continue
                    if resp.status_code >= 400:
                        raise FetchError(f"http_{resp.status_code}")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise FetchError("too_large")
                        chunks.append(chunk)
                    return FetchResult(
                        url=current,
                        status=resp.status_code,
                        content_type=resp.headers.get("content-type", ""),
                        body=b"".join(chunks),
                    )
            except httpx.HTTPError as exc:
                raise FetchError(f"network: {exc.__class__.__name__}") from exc
    raise FetchError("too_many_redirects")
