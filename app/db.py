from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    """Create an engine. SQLite gets the pragmas and locking discipline we rely on."""
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False}, pool_pre_ping=True)

        @event.listens_for(engine, "connect")
        def _sqlite_on_connect(dbapi_conn, _record):  # noqa: ANN001
            # Let SQLAlchemy control transactions explicitly (pysqlite otherwise starts them lazily).
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):  # noqa: ANN001
            # Take the write lock up front so read-then-write checks (booking limits) are serialized.
            conn.exec_driver_sql("BEGIN IMMEDIATE")

        return engine
    return create_engine(url, pool_pre_ping=True)


engine: Engine = make_engine(get_settings().db_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
