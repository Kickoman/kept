# Deployment

Kept runs as a single Docker container with SQLite and media files in a bind-mounted `./data` directory. A reverse proxy in front of it terminates TLS. How you get the code onto the server (git, an archive, CI) is up to you.

Requirements: a Linux host with Docker Engine and the Compose plugin, a domain name, and a reverse proxy (nginx, Caddy, Traefik, …).

## 1. Configure

```bash
cp .env.example .env
chmod 600 .env
```

Set at least:

- `SECRET_KEY`: a long random string, e.g. `openssl rand -hex 32`.
- `PORT`: the host port the container is published on. It is bound to `127.0.0.1` only, so just the reverse proxy can reach it.
- `APP_UID` / `APP_GID`: the owner of `./data` on the host (`id -u`, `id -g`), so the database and images stay editable without root.
- `ADMIN_USERNAMES`: your username, to get access to `/admin`.
- `BASE_URL`: leave empty unless your proxy can't pass the original headers (see below).

The full list is in the [README](README.md#configuration).

## 2. Start

```bash
docker compose up -d --build
docker compose ps                                   # wait until the container is "healthy"
curl -s http://127.0.0.1:8000/api/health            # your PORT; prints {"status":"ok"}
```

Migrations run automatically every time the container starts.

## Reverse proxy and TLS

Point your proxy at `http://127.0.0.1:<PORT>`. The app builds share links and OG tags from the request and decides whether cookies are `Secure` from it too, so the proxy must pass:

- the original `Host` header (the CSRF check compares the browser's `Origin` with it, so `X-Forwarded-Host` alone is not enough);
- `X-Forwarded-Proto`;
- `X-Real-IP` / `X-Forwarded-For` (optional, but used in the logs as `client_ip`).

The app trusts these headers. Keep the container port bound to localhost (as in `docker-compose.yml`) so that only the proxy can set them.

Uploads can be up to 5 MB, so allow request bodies of at least 6 MB.

- **Caddy** passes the headers by default: `kept.example.com { reverse_proxy 127.0.0.1:8000 }` also gets you a certificate.
- **nginx**: see [`deploy/nginx.conf.example`](deploy/nginx.conf.example), then add TLS, e.g. with `certbot --nginx -d kept.example.com`.
- **Traefik** passes the headers by default.

If the proxy can't pass the original host and scheme, set `BASE_URL=https://kept.example.com`. It is then used for links, it makes cookies `Secure`, and it is accepted as an allowed `Origin` for API requests.

## 3. Check

```bash
curl -I https://kept.example.com/              # 200
curl -I https://kept.example.com/w/nope        # 404 with "X-Robots-Tag: noindex, nofollow"
```

Then register, create a list and open its share link in a private window: the link should use your domain and `https`.

## Data and backups

Everything lives in `./data`: `wishlist.db` (plus its `-wal` / `-shm` files while running) and `media/`. The database also stores AI provider keys, so treat backups as secrets.

A consistent copy while the app is running:

```bash
sqlite3 data/wishlist.db ".backup 'backup-$(date +%F).db'"
tar czf media-$(date +%F).tgz -C data media
```

Or stop the container (`docker compose stop`) and copy the whole `data/` directory.

## Updating

Back up, replace the code with the new version, then:

```bash
docker compose up -d --build
```

The new image applies pending migrations on start.

## Logs

```bash
docker compose logs -f app
```

The app writes JSON lines to stdout. Docker's json-file driver rotates them (3 × 50 MB). To keep them longer, point any log collector (Vector, Promtail, Fluent Bit, …) at the container; it carries the label `logging: "true"` for collectors that select containers by label. The event schema is described in the [README](README.md#logs).
