"""Регрессия на `SQLITE_BUSY_SNAPSHOT` (Работа 1 плана правок мастера учебника).

Транзакция, которая сначала читает, потом пишет, в WAL-режиме ловит эту
ошибку, если между чтением и записью кто-то другой успел закоммитить.
`PRAGMA busy_timeout` здесь не спасает — SQLite не вызывает busy handler для
этого конкретного кода ошибки, отказ приходит мгновенно. Фикс —
резервировать writer безобидным `UPDATE` до всяких чтений
(`project_write_transaction`/`job_write_transaction`, `app/db.py`).

Стандартный `session`-фикстура из `conftest.py` не годится сюда: она не
включает WAL и не открывает соединение с `autocommit=False`, как это делает
`app/db.py` в проде — без этого `SQLITE_BUSY_SNAPSHOT` просто не
воспроизводится. Поэтому здесь свой движок на реальном файле и две отдельные
сессии на нём, имитирующие два процесса (API и воркер).
"""

from pathlib import Path
from uuid import uuid4

import pytest
from conftest import make_exam_project, make_material
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import Base, job_write_transaction, project_write_transaction
from app.materials.parsers.base import ParsedPage
from app.materials.worker import _save_page
from app.models import BackgroundJob, BackgroundJobKind, BackgroundJobState, Project, ProjectStatus


def _make_engine(path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"autocommit": False, "check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection: object, _: object) -> None:
        previous = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()
        finally:
            dbapi_connection.autocommit = previous

    return engine


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "contention.sqlite"
    setup_engine = _make_engine(path)
    Base.metadata.create_all(setup_engine)
    setup_engine.dispose()
    return path


def test_read_then_write_hits_busy_snapshot_without_reservation(db_path: Path) -> None:
    """Показывает саму проблему без фикса: чтение, чужой коммит, попытка
    писать в уже устаревшем снимке падает — это и есть "database is locked",
    от которого не спасает уже настроенный `busy_timeout`."""
    engine_a = _make_engine(db_path)
    engine_b = _make_engine(db_path)
    try:
        with Session(engine_a, expire_on_commit=False) as setup:
            project = make_exam_project(setup, status=ProjectStatus.DRAFT)
            project_id = project.id

        session_a = Session(engine_a, expire_on_commit=False)
        session_b = Session(engine_b, expire_on_commit=False)
        try:
            # Деферренный BEGIN, снимок берётся здесь.
            loaded = session_a.get(Project, project_id)
            assert loaded is not None

            with session_b.begin():
                session_b.execute(
                    text("UPDATE projects SET name = 'renamed' WHERE id = :id"),
                    {"id": project_id.hex},
                )

            with pytest.raises(OperationalError):
                session_a.execute(
                    text("UPDATE projects SET description = 'x' WHERE id = :id"),
                    {"id": project_id.hex},
                )
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine_a.dispose()
        engine_b.dispose()


def test_project_write_transaction_survives_concurrent_commit(db_path: Path) -> None:
    """Тот же порядок событий, но writer резервируется до чтения — не падает."""
    engine_a = _make_engine(db_path)
    engine_b = _make_engine(db_path)
    try:
        with Session(engine_a, expire_on_commit=False) as setup:
            project = make_exam_project(setup, status=ProjectStatus.DRAFT)
            project_id = project.id

        session_a = Session(engine_a, expire_on_commit=False)
        session_b = Session(engine_b, expire_on_commit=False)
        try:
            with session_b.begin():
                session_b.execute(
                    text("UPDATE projects SET name = 'renamed before' WHERE id = :id"),
                    {"id": project_id.hex},
                )

            with project_write_transaction(session_a, project_id):
                loaded = session_a.get(Project, project_id)
                assert loaded is not None
                loaded.description = "проверено без гонки"

            reloaded = session_a.get(Project, project_id)
            assert reloaded is not None
            assert reloaded.description == "проверено без гонки"
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine_a.dispose()
        engine_b.dispose()


def test_save_page_survives_concurrent_commit_and_keeps_task_running(db_path: Path) -> None:
    """`_save_page` (через `job_write_transaction`) переживает чужой коммит
    между сохранением двух страниц подряд — задача не падает в `FAILED`."""
    engine_a = _make_engine(db_path)
    engine_b = _make_engine(db_path)
    try:
        with Session(engine_a, expire_on_commit=False) as setup:
            material = make_material(setup, "c0ffee1")
            job = BackgroundJob(
                id=uuid4(),
                kind=BackgroundJobKind.PARSE,
                material_id=material.id,
                state=BackgroundJobState.RUNNING,
                done=0,
                total=2,
                checkpoint={"revision": 1, "selected_pages": [1, 2]},
            )
            setup.add(job)
            setup.commit()
            job_id = job.id

        session_a = Session(engine_a, expire_on_commit=False)
        session_b = Session(engine_b, expire_on_commit=False)
        try:
            page_one = ParsedPage(
                page_number=1,
                width=100,
                height=100,
                markdown="один",
                plain_text="один",
                quality="native",
                elements=(),
            )
            assert _save_page(session_a, job_id, page_one) is True

            # Конкурирующий коммит ровно между двумя страницами — то, что
            # раньше роняло воркер на тысячестраничном учебнике.
            with session_b.begin():
                session_b.execute(
                    text("UPDATE background_jobs SET error = NULL WHERE id = :id"),
                    {"id": job_id.hex},
                )

            page_two = ParsedPage(
                page_number=2,
                width=100,
                height=100,
                markdown="два",
                plain_text="два",
                quality="native",
                elements=(),
            )
            assert _save_page(session_a, job_id, page_two) is True

            task = session_a.get(BackgroundJob, job_id)
            assert task is not None
            assert task.state == BackgroundJobState.RUNNING
            assert task.done == 2
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine_a.dispose()
        engine_b.dispose()


def test_job_write_transaction_without_id_reserves_before_claim_scan(db_path: Path) -> None:
    """`job_id=None` (вариант для `claim_job`) резервирует writer до выборки
    задачи из очереди — тот же порядок, что спасает `project_write_transaction`."""
    engine_a = _make_engine(db_path)
    engine_b = _make_engine(db_path)
    try:
        with Session(engine_a, expire_on_commit=False) as setup:
            material = make_material(setup, "c0ffee2")
            job = BackgroundJob(
                id=uuid4(),
                kind=BackgroundJobKind.PARSE,
                material_id=material.id,
                state=BackgroundJobState.QUEUED,
                done=0,
                total=1,
                checkpoint={"revision": 1, "selected_pages": [1]},
            )
            setup.add(job)
            setup.commit()
            job_id = job.id

        session_a = Session(engine_a, expire_on_commit=False)
        session_b = Session(engine_b, expire_on_commit=False)
        try:
            with session_b.begin():
                session_b.execute(
                    text("UPDATE background_jobs SET error = NULL WHERE id = :id"),
                    {"id": job_id.hex},
                )

            with job_write_transaction(session_a):
                task = session_a.get(BackgroundJob, job_id)
                assert task is not None
                task.state = BackgroundJobState.RUNNING
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine_a.dispose()
        engine_b.dispose()
