from __future__ import annotations

from alembic import context

from app.config import get_settings
from app.db import Base, make_engine
from app.logging_setup import setup_logging
from app import models  # noqa: F401  (registers tables on Base.metadata)

# Migrations run at container start; their lines must be the same JSON as
# everything else, or the collector files them as unparsed.
setup_logging()

config = context.config

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(get_settings().db_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
