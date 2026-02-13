"""
Alembic migration environment for Transcriptionist v1.2.0.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

try:
    from transcriptionist_v3.infrastructure.database.models import Base
    from transcriptionist_v3.infrastructure.database.connection import _resolve_runtime_database_config
except ModuleNotFoundError:
    from infrastructure.database.models import Base
    from infrastructure.database.connection import _resolve_runtime_database_config


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_sqlalchemy_url() -> str:
    x_url = context.get_x_argument(as_dictionary=True).get("db_url", "").strip()
    if x_url.startswith("sqlite://"):
        return x_url
    if x_url:
        print("[WARN] Ignore non-sqlite --x db_url")

    env_url = (os.environ.get("TRANSCRIPTIONIST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if env_url.startswith("sqlite://"):
        return env_url
    if env_url:
        print("[WARN] Ignore non-sqlite DATABASE_URL")

    _, resolved_url, resolved_path = _resolve_runtime_database_config()
    if resolved_url:
        return resolved_url
    if resolved_path is not None:
        return f"sqlite:///{resolved_path}"

    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    url = _get_sqlalchemy_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = {
        "sqlalchemy.url": _get_sqlalchemy_url(),
        "poolclass": pool.NullPool,
    }
    connectable = create_engine(
        configuration["sqlalchemy.url"],
        poolclass=configuration["poolclass"],
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
