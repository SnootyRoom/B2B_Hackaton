from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  регистрирует модели
from app.core.db import Base, engine

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
