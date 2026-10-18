"""Alembic environment — customised for repo_intel."""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from repo_intel.config import get_settings
from repo_intel.db.models import Base

# ------------------------------------------------------------------
# Alembic Config
# ------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from pydantic settings (use sync driver for migrations)
settings = get_settings()
sync_url = settings.database_url.replace("+psycopg", "", 1)
if not sync_url.startswith("postgresql"):
    sync_url = "postgresql" + sync_url
config.set_main_option("sqlalchemy.url", sync_url)

# Make our models importable from the migration scripts directory
sys.path.insert(0, str(Path(__file__).parent.parent))

# Target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (synchronous engine)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
