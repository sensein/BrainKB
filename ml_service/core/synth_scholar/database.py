"""Async SQLAlchemy engine and session factory for the SynthScholar tables.

Standalone from ml_service's raw-asyncpg pool: SynthScholar uses SQLAlchemy
2.0 declarative models with JSONB columns, and tying it to the existing pool
would force a dual-driver setup. They share the same Postgres database — the
DSN is built from the same JWT_POSTGRES_DATABASE_* vars ml_service already
uses — but the engines are independent so each side manages its own pool.

SynthScholar's tables (`reviews` + synthscholar's bundled `article_store` /
`review_cache` / `pipeline_checkpoints`) live alongside the existing JWT auth
tables in the same `brainkb` database. No name collisions: synthscholar uses
lower_snake_case while the JWT side uses `Web_*` PascalCase.
"""

from __future__ import annotations

import logging
import os
from importlib.resources import files

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


def _resolve_dsn() -> str:
    """Construct the SQLAlchemy async DSN from the unified Postgres env vars.

    Required: JWT_POSTGRES_DATABASE_HOST_URL / _USER / _PASSWORD / _NAME.
    Port defaults to 5432. Falls back to a local-dev DSN only when none of
    the env vars are present (e.g. running `python -m` outside docker).
    """
    host = os.environ.get("JWT_POSTGRES_DATABASE_HOST_URL")
    user = os.environ.get("JWT_POSTGRES_DATABASE_USER")
    password = os.environ.get("JWT_POSTGRES_DATABASE_PASSWORD")
    db = os.environ.get("JWT_POSTGRES_DATABASE_NAME")
    port = os.environ.get("JWT_POSTGRES_DATABASE_PORT", "5432")
    if host and user and password and db:
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
    return "postgresql+asyncpg://postgres:postgres@localhost:5432/brainkb"


DATABASE_URL = _resolve_dsn()

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for SynthScholar ORM models."""
    pass


async def init_db() -> None:
    """Create review tables and apply additive ALTERs idempotently.

    Safe to call on every startup. The CREATE TABLE is checkfirst-aware; the
    ALTERs use ADD COLUMN IF NOT EXISTS so re-running is a no-op.
    """
    from . import db_models  # noqa: F401 — register models with metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        for stmt in (
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS run_request_json JSONB",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS share_to_cache BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS checkpoint_json JSONB",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS last_completed_step INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stage VARCHAR(200)",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stage_idx INTEGER",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stage_total INTEGER",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stage_done_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stage_remaining INTEGER",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS articles_included INTEGER",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS latest_message TEXT",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS owner_email VARCHAR(320)",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS pending_plan_json JSONB",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS pending_plan_iteration INTEGER",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS plan_response_json JSONB",
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT FALSE",
        ):
            await conn.execute(text(stmt))

    await apply_synthscholar_migrations()


async def apply_synthscholar_migrations() -> None:
    """Apply synthscholar's bundled cache migrations idempotently.

    These create the article_store / review_cache / pipeline_checkpoints
    tables plus optional pgvector embeddings used by the search endpoints.
    Migration 004 requires the pgvector extension; if Postgres doesn't ship
    it, the failure is logged and semantic search degrades to keyword/by_title.
    """
    try:
        from synthscholar.cache import migrations as _migrations_pkg  # type: ignore
    except Exception as exc:
        logger.warning("synthscholar migrations not available: %s", exc)
        return

    migrations_dir = (
        files(_migrations_pkg)
        if hasattr(_migrations_pkg, "__path__")
        else files("synthscholar.cache").joinpath("migrations")
    )
    sql_files = sorted(p for p in migrations_dir.iterdir() if p.name.endswith(".sql"))
    for path in sql_files:
        sql = path.read_text(encoding="utf-8")
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql(sql)
            logger.info("Applied synthscholar migration: %s", path.name)
        except Exception as exc:
            logger.warning("Migration %s skipped: %s", path.name, exc)


async def close_db() -> None:
    """Dispose the connection pool on shutdown."""
    await engine.dispose()
