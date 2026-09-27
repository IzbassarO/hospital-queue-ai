"""Two engines: the one requests are served from, and the one batch work runs on.

`api_engine` serves HTTP. Its pool is sized for the control centre, which fires a handful of requests per tick from
every open browser: `DB_POOL_SIZE` kept connections plus `DB_MAX_OVERFLOW` extra ones, and a caller waits at most
`DB_POOL_TIMEOUT` seconds for one instead of the SQLAlchemy default of 30, so a burst fails fast instead of looking
hung. Every connection carries `statement_timeout` (`DB_STATEMENT_TIMEOUT_MS`), so no single query can hold a worker
and a connection indefinitely. When `APP_DB_USER` / `APP_DB_PASSWORD` are configured (db/init.sql) this engine
connects with that non-superuser role; otherwise with the owner role, as the demo stack does.

`engine` / `SessionLocal` is the owner connection for work that is not a request and must not be cut short: Alembic
runs on its own engine, but the seed loader, the publish commands and the tests use this one — a `COPY` of a seeded
table or a bundle publish takes far longer than a request may.

`pool_pre_ping` on both replaces connections a restarted Postgres has dropped. `get_session` is the only session a
request opens: the auth dependency and the endpoint share it (FastAPI caches the dependency), and the access log is
written by a background task in batches (app/core/access_log.py). Settings: `.env.example`, docs/security.md §2.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

api_engine = create_engine(
    settings.api_database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    connect_args={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
)
ApiSessionLocal = sessionmaker(bind=api_engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with ApiSessionLocal() as session:
        yield session
