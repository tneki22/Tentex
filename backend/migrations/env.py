from logging.config import fileConfig

from alembic import context
from sqlalchemy import CheckConstraint

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


def normalized_check_sql(constraint: CheckConstraint) -> str:
    sql = str(
        constraint.sqltext.compile(
            dialect=engine.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    table_name = constraint.table.name
    return " ".join(
        sql.replace(f'"{table_name}".', "").replace(f"{table_name}.", "").split()
    )


TYPE_BOUND_CHECKS = frozenset(
    (table.name, normalized_check_sql(constraint))
    for table in target_metadata.tables.values()
    for constraint in table.constraints
    if isinstance(constraint, CheckConstraint)
    and getattr(constraint, "_type_bound", False)
)


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    _compare_to: object | None,
) -> bool:
    # FTS5 и её служебные таблицы создаются SQL вручную: SQLAlchemy не умеет
    # описать их в metadata и иначе считает их кандидатами на удаление.
    if type_ == "table" and name is not None and name.startswith("fragment_search"):
        return False
    # Alembic 1.19 видит созданные Enum проверки SQLite как самостоятельные,
    # но игнорирует их type-bound аналоги из metadata и предлагает удалить.
    # Сравниваем выражения, а не исторические имена: часть из них уже удвоена.
    return not (
        type_ == "check_constraint"
        and reflected
        and isinstance(object_, CheckConstraint)
        and (object_.table.name, normalized_check_sql(object_)) in TYPE_BOUND_CHECKS
    )


def run_migrations_offline() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    context.configure(
        url=engine.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
        include_object=include_object,
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
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
