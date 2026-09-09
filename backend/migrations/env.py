from logging.config import fileConfig

from alembic import context
from sqlalchemy import CheckConstraint, event

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



def _disable_foreign_keys(dbapi_connection: object, _: object) -> None:
    """Снять проверку внешних ключей на время миграции.

    SQLite не умеет ALTER, поэтому `batch_alter_table` пересобирает таблицу
    через DROP + CREATE + копирование строк. `app.db` включает
    `PRAGMA foreign_keys=ON` на каждом соединении, а Alembic работает через
    тот же engine — и при включённой проверке DROP любой таблицы, на которую
    кто-то ссылается, падает с «FOREIGN KEY constraint failed». Вылезает это
    только на базе с данными: на пустой ронять нечего, поэтому и тесты, и
    прогон на чистой базе проходили мимо ошибки.

    Слушатель вешается ПОСЛЕ того, что стоит в `app.db`, и на том же событии,
    поэтому переопределяет прагму на каждом новом соединении. PRAGMA не
    действует внутри транзакции, отсюда `autocommit` — тот же приём, что в
    `app.db.configure_sqlite`.
    """
    previous_autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=OFF")
        finally:
            cursor.close()
    finally:
        dbapi_connection.autocommit = previous_autocommit


def run_migrations_online() -> None:
    """Прогнать миграции и вернуть engine приложению нетронутым.

    `engine` здесь — тот же общий объект, что использует приложение:
    `upgrade_database()` зовётся на старте api и воркера, и подписка на
    `connect` пережила бы миграции. Тогда КАЖДОЕ последующее соединение
    процесса открывалось бы с `PRAGMA foreign_keys=OFF`, и все `ON DELETE
    CASCADE` молча переставали работать — так и оставались сироты в
    `typst_materials` после удаления материала. Поэтому слушатель снимается,
    а пул выбрасывается второй раз: соединения, открытые с прагмой OFF,
    не должны вернуться в работу.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    event.listen(engine, "connect", _disable_foreign_keys)
    # Соединения, взятые до подписки, прагму не увидят — выбрасываем пул.
    engine.dispose()
    try:
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
    finally:
        event.remove(engine, "connect", _disable_foreign_keys)
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
