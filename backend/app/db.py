"""SQLite и транзакции: общий кэш страниц меньше отдельного поискового кэша."""

import logging
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, MetaData, create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from app.config import BACKEND_ROOT, settings
from app.system import diagnostics

log = logging.getLogger("tentex.db")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


#: Постоянные соединения поиска. Пачка GET экрана разбирает общий пул, и поиск
#: попадал на соединение с холодным кэшем: первый поиск на нём 3 с вместо 0,3 с
#: (чтение с bind-mount). Свой маленький пул держит индекс кусков прогретым.
SEARCH_POOL_SIZE = 2


def _pool_arguments(pool_size: int) -> dict[str, object]:
    """Пул для API или новое соединение на сессию для воркера и скриптов."""
    if pool_size == 0:
        return {"poolclass": NullPool}
    # QueuePool по умолчанию (5+10, 30 с) исчерпывался пачкой GET с экрана.
    # Большой overflow снимает этот предел: лишние соединения закрываются
    # при возврате. LIFO отдаёт последнее соединение, у которого кэш прогрет.
    return {
        "poolclass": QueuePool,
        "pool_size": pool_size,
        "max_overflow": 64,
        "pool_timeout": 60,
        "pool_use_lifo": True,
    }


def _create_engine(pool_size: int) -> Engine:
    return create_engine(
        URL.create("sqlite+pysqlite", database=str(settings.database_path)),
        connect_args={"autocommit": False, "check_same_thread": False, "timeout": 30},
        **_pool_arguments(pool_size),
    )


engine = _create_engine(settings.sqlite_pool_size)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
search_engine = (
    _create_engine(min(SEARCH_POOL_SIZE, settings.sqlite_pool_size))
    if settings.sqlite_pool_size
    else engine
)
SearchSessionLocal = sessionmaker(bind=search_engine, expire_on_commit=False)


def configure_sqlite(
    dbapi_connection: object, _: object, *, cache_kib: int | None = None,
) -> None:
    """Кэш страниц ограничен ролью соединения; WAL и mmap одинаковы для всех."""
    previous_autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            # Штатный спутник WAL: fsync на контрольной точке, а не на каждом
            # коммите. С FULL любая запись ждала fsync через bind-mount с хоста.
            cursor.execute("PRAGMA synchronous=NORMAL")
            # data/ — bind-mount с Windows-хоста: mmap для wal-index там ненадёжен
            # и роняет параллельные запросы с "disk I/O error".
            # Обычный файловый ввод-вывод работает.
            cursor.execute("PRAGMA mmap_size=0")
            if settings.sqlite_pool_size:
                cursor.execute(f"PRAGMA cache_size=-{cache_kib or settings.sqlite_cache_kib}")
        finally:
            cursor.close()
    finally:
        dbapi_connection.autocommit = previous_autocommit


for _engine in {engine, search_engine}:
    event.listen(
        _engine, "connect", partial(
            configure_sqlite,
            cache_kib=(settings.sqlite_search_cache_kib if _engine is search_engine
                       else settings.sqlite_cache_kib),
        ),
    )


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def dispose_engines() -> None:
    """Закрыть соединения обоих пулов перед подменой файла базы."""
    for pooled in {engine, search_engine}:
        pooled.dispose()


def get_search_session() -> Iterator[Session]:
    """Сессия поисковых GET: те же данные, но соединения из пула поиска."""
    with SearchSessionLocal() as session:
        yield session


@contextmanager
def project_write_transaction(session: Session, project_id: UUID):
    """Reserve SQLite's writer before reads so timer/worker commits cannot stale the snapshot.

    Python 3.13 autocommit=False already opens BEGIN on connect. A no-op write
    obtains the same reservation as BEGIN IMMEDIATE without nesting BEGIN or
    rolling back caller data. Values and project revisions remain unchanged.
    Use only for short local transactions, never across a model request.
    """
    # Read endpoints may leave SQLAlchemy's autobegun transaction open on a
    # reused session (notably in TestClient and background workflows). Close
    # that read transaction before reserving the writer; request-scoped
    # sessions still have no-op overhead here.
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.execute(text("UPDATE projects SET id = id WHERE id = :id"), {"id": project_id.hex})
        yield


@contextmanager
def chat_write_transaction(session: Session, project_id: UUID | None):
    """Резервировать writer для проектного либо библиотечного чата."""
    if project_id is not None:
        with project_write_transaction(session, project_id):
            yield
        return
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.execute(text("UPDATE chat_sessions SET id = id WHERE 1=0"))
        yield


@contextmanager
def job_write_transaction(session: Session, job_id: UUID | None = None):
    """Тот же приём резервирования writer, что у `project_write_transaction`,
    но для фоновой задачи (`SQLITE_BUSY_SNAPSHOT` объяснён там же).

    `job_id=None` — вариант для `claim_job`: конкретная задача ещё не выбрана
    (это чтение и есть первый шаг), поэтому резервирующий `UPDATE` не находит
    ни одной строки (`WHERE 1=0`). SQLite всё равно запрашивает write-lock при
    подготовке write-опкода, до сканирования совпадений — нулевой результат
    ничего не портит и ничего не меняет.
    """
    if session.in_transaction():
        session.commit()
    with session.begin():
        if job_id is None:
            session.execute(text("UPDATE background_jobs SET updated_at = updated_at WHERE 1=0"))
        else:
            session.execute(
                text("UPDATE background_jobs SET updated_at = updated_at WHERE id = :id"),
                {"id": job_id.hex},
            )
        yield


def retry_on_locked[T](operation: Callable[[], T], *, attempts: int = 5) -> T:
    """Повторить операцию при `SQLITE_BUSY_SNAPSHOT` вместо немедленного отказа.

    Эта ошибка не проходит через busy handler (`PRAGMA busy_timeout` не спасает),
    поэтому единственный выход — короткая пауза и новая попытка на свежем снимке.
    Любая другая ошибка пробрасывается сразу: ретраить её бессмысленно.
    """
    delays = (0.2, 0.5, 1, 2)
    for attempt in range(attempts):
        try:
            return operation()
        except OperationalError as error:
            message = str(error).lower()
            if "database is locked" not in message and "database is busy" not in message:
                raise
            if attempt == attempts - 1:
                # Одиночный исчерпанный повтор ещё не сбой: сводка «Состояние»
                # покажет блокировку, только если они повторяются.
                diagnostics.record_failure("database_locked", kind="exhausted")
                raise
            delay = delays[min(attempt, len(delays) - 1)]
            log.warning("retrying after sqlite lock, attempt=%d delay=%.1fs", attempt + 1, delay)
            time.sleep(delay)
    raise AssertionError("unreachable")


def _ensure_wal_mode(attempts: int = 5, delay: float = 0.5) -> None:
    # journal_mode живёт в самом файле базы, а не на соединении: переключатель
    # в configure_sqlite молча проглатывал результат PRAGMA. Если в момент
    # переключения был открыт хоть один параллельный коннект, SQLite тихо
    # оставлял режим DELETE — и база годами работала не в WAL, как задумано
    # по стеку, а в обычном rollback journal с его куда более жёсткими
    # эксклюзивными блокировками. Отсюда были "database is locked" на
    # обычных запросах. Здесь единственная точка входа при старте процесса
    # (до открытия конкурентных соединений) — переключаем и проверяем.
    last_mode = None
    for _ in range(attempts):
        connection = sqlite3.connect(str(settings.database_path), timeout=30)
        try:
            last_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        finally:
            connection.close()
        if last_mode == "wal":
            return
        time.sleep(delay)
    raise RuntimeError(f"не удалось перевести базу в WAL: journal_mode={last_mode!r}")


def upgrade_database() -> None:
    """Поднять схему до head.

    Api и worker зовут это на своём старте независимо (`docker compose restart
    api worker web` их не упорядочивает — `depends_on: condition:
    service_healthy` работает только на `up`). Если оба стартуют одновременно,
    один успевает применить миграцию первым; вторая транзакция уже прочитала
    старый снимок alembic_version и на попытке записи ловит
    `SQLITE_BUSY_SNAPSHOT` ("database is locked") мимо busy handler — 24.09.2026
    так падал api сразу после того, как worker применял 0059/0060, и оставался
    нездоровым до ручного перезапуска. `retry_on_locked` берёт свежий снимок и
    на повторной попытке видит, что миграция уже на head — no-op.
    """
    _ensure_wal_mode()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    retry_on_locked(lambda: command.upgrade(config, "head"))
