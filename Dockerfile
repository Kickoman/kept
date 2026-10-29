FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data DATABASE_URL=sqlite:////data/wishlist.db SERVICE_NAME=wishlist

# The app user gets the host user's uid/gid (APP_UID/APP_GID from .env), so the
# sqlite file and media in the bind-mounted ./data stay editable from the host.
ARG APP_UID=1000
ARG APP_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/* \
    && (getent group "$APP_GID" >/dev/null || groupadd -g "$APP_GID" app) \
    && useradd -u "$APP_UID" -g "$APP_GID" -d /app -M app

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY static ./static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
VOLUME ["/data"]
ENTRYPOINT ["docker-entrypoint.sh"]
# --no-proxy-headers: uvicorn otherwise rewrites request.client from the
# forwarded headers, erasing the one address that is always true. The app
# reads X-Forwarded-Proto/Host itself where it needs them (share links,
# cookies) and logs both peer_ip and client_ip.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
