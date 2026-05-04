from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
import os
# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from libs.shared.models import Base
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
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
    # Build a safe config dict so ConfigParser interpolation doesn't fail
    from libs.shared.config import settings

    # 1. Prefer DATABASE_URL env var, otherwise use project settings
    cmd_line_url = os.getenv("DATABASE_URL") or settings.database_url

    # 2. Handle the 'postgres://' vs 'postgresql://' fix for SQLAlchemy
    if cmd_line_url and cmd_line_url.startswith("postgres://"):
        cmd_line_url = cmd_line_url.replace("postgres://", "postgresql://", 1)

    # 3. Create a minimal config dict and pass the URL explicitly to avoid
    #    triggering configparser interpolation on the alembic.ini file.
    cfg = {"sqlalchemy.url": cmd_line_url}

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=cmd_line_url,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
