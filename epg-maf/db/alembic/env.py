"""Alembic runtime environment.

Resolves the database URL from ``ALEMBIC_URL`` (preferred) or from
``egp_maf.config.Settings`` fields (fallback). Runs migrations synchronously
with plain psycopg — async is not needed for DDL and this keeps the Alembic
tooling standard.

The URL is expected to use the migrator role (``egp_migrator``), NOT the
application role (``egp_agent_ro``). Failing to distinguish would allow the
application to accidentally alter schema — see Design §11.5.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object — the values from alembic.ini.
config = context.config

# Configure Python logging via the [loggers] section of alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    """Return a SQLAlchemy connection URL for Alembic to use.

    Priority order:
      1. ``ALEMBIC_URL`` environment variable.
      2. Constructed from ``POSTGRES_MIGRATOR_*`` env vars.
      3. Constructed from ``POSTGRES_*`` env vars (dev fallback only).
    """
    explicit = os.environ.get("ALEMBIC_URL")
    if explicit:
        return explicit

    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DATABASE", "egp")
    ssl_mode = os.environ.get("POSTGRES_SSL_MODE", "prefer")

    user = os.environ.get("POSTGRES_MIGRATOR_USER") or os.environ.get(
        "POSTGRES_USER", "egp_migrator"
    )
    password = os.environ.get("POSTGRES_MIGRATOR_PASSWORD") or os.environ.get(
        "POSTGRES_PASSWORD"
    )
    if not password:
        raise RuntimeError(
            "No migrator password set. Provide ALEMBIC_URL, "
            "POSTGRES_MIGRATOR_PASSWORD, or POSTGRES_PASSWORD."
        )

    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?sslmode={ssl_mode}"
    )


def run_migrations_offline() -> None:
    """Run migrations without a live connection — emit SQL to a file / stdout."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    url = _resolve_url()
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
