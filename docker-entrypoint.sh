#!/bin/sh
set -e
# The bind-mounted data dir is usually created by Docker as root; hand it to the app user.
mkdir -p "${DATA_DIR:-/data}/media"
chown -R app:"$(id -g app)" "${DATA_DIR:-/data}"
cd /app
gosu app alembic upgrade head
exec gosu app "$@"
