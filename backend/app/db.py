import sqlite3
import time
from collections.abc import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import BACKEND_ROOT, settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine = create_engine(
    URL.create("sqlite+pysqlite", database=str(settings.database_path)),
    connect_args={"autocommit": False, "check_same_thread": False, "timeout": 30},
    # SQLAlchemy-пул рассчитан на дорогие сетевые соединения. Для SQLite
    # соединение — это просто open() файла, а WAL и busy_timeout уже решают
    # конкуренцию на уровне самого SQLite. С QueuePool по умолчанию (5+10)
    # пачка параллельных запросов с экрана (~6 GET разом) исчерпывала пул и
    # часть запросов падала с sqlalchemy.exc.TimeoutError после 30с ожидания.
    poolclass=NullPool,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def configure_sqlite(dbapi_connection: object, _: object) -> None:
    previous_autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            # data/ — bind-mount с Windows-хоста: mmap для wal-index там ненадёжен
            # и роняет параллельные запросы с "disk I/O error".
            # Обычный файловый ввод-вывод работает.
            cursor.execute("PRAGMA mmap_size=0")
        finally:
            cursor.close()
    finally:
        dbapi_connection.autocommit = previous_autocommit


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


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
    _ensure_wal_mode()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
