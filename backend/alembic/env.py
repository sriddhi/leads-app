import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure the app package is importable from the backend/ root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402 — must come after sys.path insert
from app.models.base import Base  # noqa: E402
# Import all models so Alembic's autogenerate can detect them
import app.models.lead  # noqa: F401, E402
import app.models.user  # noqa: F401, E402
import app.models.audit  # noqa: F401, E402
import app.models.timeline  # noqa: F401, E402
import app.models.settings  # noqa: F401, E402

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """
    Return a *synchronous* database URL suitable for Alembic migrations.
    Replaces the asyncpg driver with psycopg2.
    """
    url = settings.DATABASE_URL
    # e.g. postgresql+asyncpg://... -> postgresql+psycopg2://...
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://").replace(
        "postgresql+aiosqlite://", "sqlite:///"
    )


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — generates SQL script without a live
    database connection.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode — connects to the database and applies
    migrations directly.
    """
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
