from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401
from app.config import settings
from app.db import Base, engine

config = context.config
if config.config_file_name:
    # disable_existing_loggers по умолчанию True: без него fileConfig на каждом
    # запуске (upgrade_database вызывается при старте api и worker) глушит уже
    # созданные логгеры uvicorn ("uvicorn.access", "uvicorn.error") — из-за
    # этого пропадали и строки доступа, и трейсбеки 500-х.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    context.configure(
        url=engine.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
