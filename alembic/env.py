"""
Alembic Migration Environment Configuration

This module configures the Alembic migration environment for the
AgentScoring STT pipeline database. It sets up the database connection,
imports the models, and provides migration execution functions.

Author: AgentScoring Team
Date: 2025-09-15
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add the parent directory to the Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.common.config import settings
from app.common.db import Base
from app.common import models  # noqa: F401 - Import needed to register models


# Alembic configuration object
config = context.config

# Inject runtime database URL from settings
if settings.database_url:
    config.set_main_option('sqlalchemy.url', settings.database_url)

# Configure logging if config file exists
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogeneration
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the
    Engine creation, we don't even need a DBAPI to be available.
    
    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option('sqlalchemy.url')
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    
    In this scenario, we need to create an Engine and associate
    a connection with the context.
    """
    configuration = config.get_section(config.config_ini_section)
    connectable = engine_from_config(
        configuration,
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


# Execute appropriate migration mode
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
