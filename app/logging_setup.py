"""Structured JSON logging for the wishlist service.

Every event is one JSON line on stdout. Nothing is shipped from here -- a
collector on the host (if any) reads container stdout, so the app stays
unaware of where logs end up.

Two streams are produced:

``http_request``
    One event per request: method, route pattern, status, duration, the
    client's addresses, its User-Agent and the host of the site it came from.
``internal``
    Anything the handlers choose to record, via ``get_logger()``.

Wire-up (``app/main.py``)::

    setup_logging()
    app.add_middleware(RequestLogMiddleware)
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

# Set per request, picked up by every log line emitted while handling it --
# including logs from libraries that know nothing about this module.
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

# Endpoints logged at debug level. Health checks fire constantly and say
# nothing; at the default level they are dropped before serialization.
QUIET_ROUTES = frozenset({"/api/health"})

# Header values in a log are cut to this many characters: the client controls
# them, the log store pays for them.
LOGGED_TEXT = 200

DEFAULT_SERVICE = "wishlist"


def _add_context(_logger: Any, _name: str, event: dict) -> dict:
    event.setdefault("service", os.environ.get("SERVICE_NAME", DEFAULT_SERVICE))
    event.setdefault("stream", "internal")
    if trace_id := _trace_id.get():
        event.setdefault("trace_id", trace_id)
    return event


def _rename_fields(_logger: Any, _name: str, event: dict) -> dict:
    # structlog names them "timestamp" and "event"; the schema wants "ts",
    # and separates the machine-readable event name from the human message.
    event["ts"] = event.pop("timestamp")
    event.setdefault("message", event.get("event", ""))
    return event


def _rename_foreign_fields(_logger: Any, _name: str, event: dict) -> dict:
    """Same as _rename_fields, but for logs coming from libraries.

    Their entire message lands in "event" -- pids, ports and all. That column
    is LowCardinality, so every restart with a new pid adds another value to
    its dictionary, without bound. Keep the text in "message" and give these
    one stable event name.
    """
    event = _rename_fields(_logger, _name, event)
    event["event"] = "log"
    return event


_SHARED_PROCESSORS = [
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    _add_context,
]


def setup_logging(service: str = DEFAULT_SERVICE, level: str | None = None) -> None:
    os.environ.setdefault("SERVICE_NAME", service)
    level = (level or os.environ.get("LOG_LEVEL", "info")).upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            *_SHARED_PROCESSORS,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _rename_fields,
            # ensure_ascii=False: titles and names are Cyrillic; escaped
            # \uXXXX makes logs unreadable and needlessly larger.
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )

    # Route stdlib logs (uvicorn, alembic, sqlalchemy, httpx, anthropic)
    # through the same renderer, so the collector never sees two formats.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(ensure_ascii=False),
            foreign_pre_chain=[*_SHARED_PROCESSORS, _rename_foreign_fields],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level))

    # uvicorn installs its own handlers; drop them or every line appears twice.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # uvicorn.access repeats what RequestLogMiddleware already records, only
    # unstructured. Silence it rather than store every request twice.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True

    # httpx logs every outbound request at INFO with the full URL -- for
    # link enrichment that is a user's product page. enrich_done records
    # the host instead; keep the library quiet unless it has a problem.
    for name in ("httpx", "httpx2", "httpcore", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(stream: str = "internal", **bound: Any):
    """Return a lazily-configured logger.

    Values are passed to ``get_logger`` rather than ``.bind()`` on purpose:
    ``.bind()`` resolves the configuration immediately, so a module-level
    ``log = get_logger()`` in a router would freeze the default console
    renderer -- routers are imported before ``setup_logging()`` runs, and
    their events would come out unstructured while everything else is JSON.
    """
    return structlog.get_logger(stream=stream, **bound)


def new_trace(trace_id: str | None = None) -> str:
    trace_id = trace_id or uuid.uuid4().hex
    _trace_id.set(trace_id)
    return trace_id


def client_addresses(request: Request) -> dict:
    """Both the direct peer and the originating client.

    Behind a reverse proxy the socket peer is the proxy, which says nothing
    about who actually made the request, so the real client is recovered from
    the headers. Both are kept: ``peer_ip`` is always what really connected,
    while ``client_ip`` is a claim no stronger than the proxy in front.

    ``X-Real-IP`` is preferred because the proxy *sets* it, replacing anything
    the client sent. ``X-Forwarded-For`` is *appended* to, so its leftmost
    entries are whatever the client chose to put there; the trustworthy one
    is the last, which is the address the proxy itself saw.
    """
    peer = request.client.host if request.client else ""
    real = (request.headers.get("x-real-ip") or "").strip()
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]

    fields = {"peer_ip": peer, "client_ip": real or (chain[-1] if chain else peer)}
    if forwarded:
        fields["forwarded_for"] = forwarded
    return fields


def _referrer_host(request: Request) -> str:
    """Host of the page that linked here; empty for the site's own pages."""
    try:
        host = urlsplit(request.headers.get("referer", "")).netloc
    except ValueError:
        return ""
    return "" if host == request.headers.get("host", "") else host[:LOGGED_TEXT]


def _route_of(request: Request) -> str:
    """Route pattern, not the raw path.

    ``/api/w/{token}`` keeps the endpoint countable; the raw path would make
    every token its own endpoint and blow up cardinality in the log store.

    The pattern is rebuilt from the matched path params rather than taken
    from ``scope["route"].path``: for routers included into routers FastAPI
    reports that path without the outer prefix (``/wishlists/{id}`` instead
    of ``/api/wishlists/{id}``).

    Mounts (``/static``, ``/media``) are collapsed to ``<mount>/*``: media
    file names are random, and per-asset stats are not worth a column of
    unbounded values.
    """
    scope = request.scope
    if isinstance(scope.get("endpoint"), StaticFiles):
        return f"{scope.get('root_path', '')}/*"
    path = request.url.path
    params = scope.get("path_params") or {}
    if not params:
        return path
    by_value = {str(v): k for k, v in params.items()}
    return "/".join(f"{{{by_value[seg]}}}" if seg in by_value else seg for seg in path.split("/"))


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Emits one ``http_request`` event per request."""

    def __init__(self, app):
        super().__init__(app)
        self._log = get_logger(stream="http_request")

    async def dispatch(self, request: Request, call_next):
        # Reuse the caller's trace id when present, so one id spans services.
        trace_id = new_trace(request.headers.get("x-trace-id"))
        started = time.perf_counter()
        status, error = 500, ""

        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-trace-id"] = trace_id
            return response
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            route = _route_of(request)
            if status >= 500:
                level = "error"
            elif route in QUIET_ROUTES:
                level = "debug"
            else:
                level = "info"

            extra = {"user_agent": request.headers.get("user-agent", "")[:LOGGED_TEXT]}
            referrer = _referrer_host(request)
            if referrer:
                extra["referrer_host"] = referrer

            getattr(self._log, level)(
                "http_request",
                http_method=request.method,
                http_path=route,
                http_status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                error=error,
                **client_addresses(request),
                **extra,
            )
