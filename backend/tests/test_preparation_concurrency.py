"""Запись времени не должна превращать начатое сохранение оценки в BUSY_SNAPSHOT."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import Base, configure_sqlite, project_write_transaction
from app.models import Project
from app.projects.schemas import WorkspaceStateWrite
from app.projects.service import save_workspace_state


def test_short_project_writes_reserve_writer_before_reading(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'concurrent.sqlite'}",
        connect_args={"autocommit": False, "check_same_thread": False},
    )
    event.listen(engine, "connect", configure_sqlite)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        project = make_exam_project(session)
        project_id, revision = project.id, project.program_revision
    held, release, second_started = Event(), Event(), Event()

    def first_write():
        with Session(engine) as session, project_write_transaction(session, project_id):
            row = session.get(Project, project_id)
            held.set()
            assert release.wait(5)
            row.name = "first"

    def second_write():
        second_started.set()
        with Session(engine) as session, project_write_transaction(session, project_id):
            row = session.get(Project, project_id)
            assert row.name == "first"
            row.name = "second"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_write)
        assert held.wait(5)
        second = executor.submit(second_write)
        assert second_started.wait(5)
        try:
            with pytest.raises(TimeoutError):
                second.result(timeout=0.05)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    with Session(engine) as session:
        row = session.get(Project, project_id)
        assert row.name == "second" and row.program_revision == revision
    engine.dispose()


def test_workspace_save_waits_for_opening_write_without_stale_snapshot(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'workspace-concurrent.sqlite'}",
        connect_args={"autocommit": False, "check_same_thread": False},
    )
    event.listen(engine, "connect", configure_sqlite)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        project = make_exam_project(session)
        node = make_topic_node(session, project, title="Вопрос")
        project_id, node_id = project.id, node.id
    command = WorkspaceStateWrite.model_validate({
        "schema_version": 1,
        "layout": {
            "selected_node_id": str(node_id),
            "groups": [{"id": "main", "tabs": ["answer"], "active_tab": "answer"}],
            "group_weights": [1],
        },
    })
    held, release, save_started = Event(), Event(), Event()

    def opening_write():
        with Session(engine) as session, project_write_transaction(session, project_id):
            held.set()
            assert release.wait(5)

    def save_layout():
        save_started.set()
        with Session(engine) as session:
            return save_workspace_state(session, project_id, command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        opening = executor.submit(opening_write)
        assert held.wait(5)
        saving = executor.submit(save_layout)
        assert save_started.wait(5)
        with pytest.raises(TimeoutError):
            saving.result(timeout=0.1)
        release.set()
        opening.result(timeout=5)
        saved = saving.result(timeout=5)

    assert saved.layout.selected_node_id == node_id
    engine.dispose()
