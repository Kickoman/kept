# Kept

A self-hosted wishlist. Friends reserve gifts from your list, and you don't see what's been reserved.

The owner signs up, creates a list and fills it with wishes: a title, a description, a photo and a link. Paste a link and the rest is filled in automatically. The list lives at a secret URL that search engines don't index. Friends open it without an account, and when they want to reserve a gift they sign in and it is reserved under their name. The owner never sees who reserved what, or whether anything is reserved at all.

- Private share links (128-bit token, can be regenerated), `noindex` everywhere it matters.
- Reservations are hidden from the owner; guests see how much of an item is taken, but not by whom.
- Quantity limits are enforced transactionally, so two guests can't reserve the last item at once.
- Link import: page metadata (Open Graph, JSON-LD), optionally polished by an LLM; optional AI-generated product photos.
- Admin panel: users, lists, items, reservations, sessions, AI provider settings, media cleanup.
- UI in English, Russian and Belarusian; light and dark themes.
- A landing page per language, rendered on the server, with a sitemap, hreflang links and Open Graph previews.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 + Alembic, SQLite (Postgres should only need a different `DATABASE_URL`).
- **Frontend:** static HTML and vanilla JS (ES modules), no build step. i18n: en / ru / be. Design tokens in `static/css/tokens.css`. The landing pages are the exception: `app/landing.py` renders them on the server.
- **AI (optional):** providers behind the `TextProvider` / `ImageProvider` interfaces in `app/services/ai_providers.py`. Text: Anthropic or Yandex Cloud (YandexGPT Lite). Images: Yandex Cloud. Configured in the admin panel. Without a provider, link import still works from page metadata.
- **Runtime:** Docker + `docker compose`; the database and media live in `./data` on the host.

## Quick start (Docker)

```bash
cp .env.example .env      # adjust if needed; see the configuration table below
docker compose up --build
```

Open http://localhost:8000. Migrations run when the container starts. The database and images are stored in `./data`, which is created automatically and handed to the `app` user inside the container.

To make yourself an administrator, put your username into `ADMIN_USERNAMES` in `.env` before (or after) registering and restart the container.

For running it on a server behind a reverse proxy with TLS, see [DEPLOY.md](DEPLOY.md).

## Configuration

All settings come from environment variables (or `.env`); see `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | `dev-secret-change-me` | Reserved for signing; nothing uses it yet (session tokens are random and stored hashed). Set a long random string anyway. |
| `PORT` | `8000` | Host port the container is published on (bound to `127.0.0.1`). |
| `APP_UID`, `APP_GID` | `1000` | uid/gid of the app user in the container; use your own (`id -u`, `id -g`) so `./data` stays yours. |
| `BASE_URL` | — | Public origin, e.g. `https://kept.example`. Optional, see [Reverse proxy](DEPLOY.md#reverse-proxy-and-tls). |
| `DATA_DIR`, `DATABASE_URL` | `./data`, sqlite in `DATA_DIR` | Where the database and media live. Compose sets them to `/data`. |
| `ADMIN_USERNAMES` | — | Comma-separated usernames that get the admin flag at startup and on registration. |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error`. |
| `TEXT_PROVIDER`, `IMAGE_PROVIDER` | `none` | Default AI providers (`none`/`anthropic`/`yandex` and `none`/`yandex`). The admin panel overrides them. |
| `ANTHROPIC_API_KEY`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` | — | Default AI credentials; also editable in the admin panel. |
| `MEDIA_SWEEP_HOURS` | `24` | How often unused images are deleted (`0` turns the sweep off). |
| `MEDIA_ORPHAN_TTL_HOURS` | `24` | Unused images younger than this are kept. |

## Local development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head                     # creates ./data/wishlist.db
uvicorn app.main:app --reload            # http://127.0.0.1:8000
pytest                                   # auth, lists, bookings, admin, SSRF guard, enrich, logging
```

An end-to-end UI test drives headless Chromium against a running server (needs `playwright install chromium`):

```bash
KEPT_BASE_URL=http://127.0.0.1:8000 python tests/e2e_ui.py
```

## How it works

```
app/
  main.py          FastAPI app, CSRF/Origin check, X-Robots-Tag and cache headers, routers and static mounts
  config.py        settings from the environment (.env)
  db.py            engine; for sqlite: WAL, foreign_keys, busy_timeout, BEGIN IMMEDIATE
  models.py        User, UserSession, Wishlist, Item, Booking, AppSetting
  logging_setup.py JSON logging and the request-log middleware
  landing.py       landing pages (/, /ru/, /be/), sitemap.xml and robots.txt
  routers/         auth, wishlists, items, public (guest API), ai, admin, pages (HTML)
  services/        linkfetch (safe fetch), enrich, ai_providers, ai_settings, images, bookings, ratelimit
static/            HTML shells, css/, img/ (icons, preview images), js/ (api.js, ui.js, i18n.js, pages/*)
alembic/           migrations (batch mode for sqlite)
tests/             pytest + tests/e2e_ui.py (Playwright)
```

Key decisions:

- **Bookings are hidden from the owner.** `GET /api/w/{token}` recognises the owner by session and doesn't load bookings at all. The owner's edits are never validated against bookings (an error would give them away); deleting an item cascades to its bookings.
- **Guests see totals, not names.** For everyone else the public API returns how many of each item are taken plus the viewer's own bookings, so they can cancel them.
- **Private links.** The share token is 128 bits (`secrets.token_urlsafe(16)`) and can be regenerated. `X-Robots-Tag: noindex` on `/w/*`, `/api/*`, `/media/*`, `/admin`, plus `<meta name=robots>`. `robots.txt` deliberately doesn't block `/w/` for search engines, because a crawler only sees `noindex` on pages it may fetch; crawlers that collect AI training data are kept away from `/w/` instead. Hiding is best effort: nothing stops the owner from opening the link in a private window.
- **Languages.** The landing has one URL per language (`/`, `/ru/`, `/be/`) with `hreflang` links, so search engines see every version. Visitors who open `/` are sent to their language: the choice made with the language switcher wins, otherwise the browser language decides, and a Russian browser in the `Europe/Minsk` time zone gets Belarusian. The rest of the UI is translated in the browser by the same rules.
- **Only registered users can book.** The list opens without an account. Pressing "Book" sends a guest to sign in or register, and the booking is placed automatically afterwards (the dialog state waits in `localStorage` as `kept.pendingClaim`). The guest's name comes from their profile. A booking can be cancelled by its author from any device and by an administrator.
- **Quantity limits** are checked in a transaction holding the write lock (`BEGIN IMMEDIATE`), so concurrent bookings can't oversell (there is a threaded test for this).
- **SSRF guard** for every outgoing request (`services/linkfetch.py`): http/https only, private/loopback/link-local addresses refused, redirects followed manually and re-checked, response size capped while streaming.
- **Sessions** are `HttpOnly; SameSite=Lax` cookies; the database stores only the sha256 of the token. CSRF protection: a required `X-Requested-With: fetch` header plus an `Origin` check on mutating requests.

## API

Prefix `/api`, JSON. Interactive docs at `/api/docs`.

| Method | Path | Who |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/change-password`; GET/PATCH `/auth/me` | anyone / signed in |
| GET/POST | `/wishlists`; GET/PATCH/DELETE `/wishlists/{id}`; POST `/wishlists/{id}/regenerate-token` | owner |
| POST | `/wishlists/{id}/items`; PATCH/DELETE `/items/{id}`; POST `/items/{id}/image`; PUT `/wishlists/{id}/items/order` | owner |
| GET | `/w/{token}` | anyone with the link |
| POST | `/w/{token}/items/{item_id}/bookings`; DELETE `/bookings/{id}` | signed-in guests |
| POST | `/ai/enrich` `{url, lang}`; `/ai/image` (501 when no image provider is configured) | signed in |
| GET/PATCH/POST/DELETE | `/admin/*` | administrators |
| GET | `/config`, `/health` | anyone |

## Logs

The app writes one JSON line per event to stdout (`structlog`, `app/logging_setup.py`) and ships nothing itself: read them with `docker compose logs`, or point any collector at the container output. The compose file sets a `logging: "true"` label for collectors that pick containers by label, and the json-file driver rotates logs locally.

Streams:

- `http_request`: one event per request with `http_method`, `http_path` (the route pattern such as `/api/w/{token}`; static files and media are collapsed into `/static/*` and `/media/*`), `http_status`, `duration_ms`, `peer_ip` / `client_ip`, `user_agent` (up to 200 characters), `referrer_host` (the other site's host from `Referer`, only when present) and `trace_id` (taken from the `x-trace-id` request header when present and echoed in the response). `/api/health` is logged at `debug`.
- `internal`: application events such as `startup`, `user_registered`, `wishlist_created`, `item_created`, `booking_created` / `booking_rejected` / `booking_cancelled`, `enrich_done` / `enrich_failed`, `provider_error`, `csrf_rejected`, `unsafe_url_rejected`, `admin_action`. Passwords, session/share/booking tokens, guest names and full item URLs (only the host) never reach the logs.
- Logs from uvicorn, alembic and libraries go into the same JSON stream with `event: "log"`.

Every event carries `service` (`SERVICE_NAME`, `wishlist` in the container). uvicorn runs with `--no-proxy-headers`, so `peer_ip` is always the real peer; the client address and scheme are read from `X-Real-IP` / `X-Forwarded-*` explicitly.

## Admin panel

Usernames listed in `ADMIN_USERNAMES` get the `is_admin` flag at startup (if the account exists) or on registration. Administrators see an "Admin" link in the header (`/admin`): counters; search through users, lists, items and bookings (including guest names); deleting any of them; editing texts; resetting passwords; closing sessions; granting and revoking admin rights. The API is `/api/admin/*`, and every action is logged as `admin_action`. You can't delete yourself or demote the last administrator.

## AI providers

Configured in the admin panel (AI tab): the text provider (off / Anthropic / Yandex Cloud), the image provider (off / Yandex Cloud), keys, the Yandex folder id and model names. The "Check" button makes a real request and shows the error in plain words. The `TEXT_PROVIDER`, `IMAGE_PROVIDER`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` and `ANTHROPIC_API_KEY` variables are only defaults. The live configuration is stored in the `app_settings` table, so keep `data/` readable by its owner only.

**Anthropic:** an API key; the model is configurable (default `claude-opus-5`).

**Yandex Cloud:** the service account needs the `ai.languageModels.user` (text) and `ai.imageGeneration.user` (images) roles, and the API key the `yc.ai.languageModels.execute` and `yc.ai.imageGeneration.execute` scopes; the folder id looks like `b1g…`. Text uses `gpt://<folder>/yandexgpt-lite/latest` via the Text Generation API. Images use `art://<folder>/aliceai-image-art-3.0` via the OpenAI-compatible Images API (`https://ai.api.cloud.yandex.net/v1/images/generations`); the older asynchronous YandexART 2.0 API is retired. Rough prices as of September 2026: about $0.0016 per 1000 tokens of YandexGPT Lite, about $0.018 per image.

**Adding a provider:** a class with `suggest(meta, lang)` / `check()` (text) or `generate(prompt, lang)` / `check()` (images) in `app/services/ai_providers.py`, a branch in `ai_settings.text_provider()` / `image_provider()` and an option in the admin drop-down.

## Media

Uploaded, downloaded-from-the-page and generated images are stored in `data/media/` as JPEG (at most 1600 px on the long side, metadata stripped, random file names). Generated images are written before the item is saved, so unused files older than `MEDIA_ORPHAN_TTL_HOURS` are deleted by a background task every `MEDIA_SWEEP_HOURS`, and on demand with the "Delete unused" button on the admin AI tab.

## License

[MIT](LICENSE)
