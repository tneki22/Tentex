"""Настоящий spawn воркера сохраняет lease, ревизию и FTS на отдельной базе."""

from datetime import timedelta

from conftest import make_material

from app.materials.worker import _process_claimed_job
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    ParserMode,
    utc_now,
)
from app.process_pool import IdleProcessPool


def test_heavy_retrieval_uses_processes_and_keeps_ai_capacity(monkeypatch):
    """Индекс делит слоты с AI, но большой корпус не остаётся в supervisor."""
    from concurrent.futures import Future

    from app.materials import worker

    kinds = [BackgroundJobKind.RETRIEVAL_INDEX, BackgroundJobKind.RETRIEVAL_EXHAUSTIVE,
             BackgroundJobKind.AI_PROGRAM_BUILD]
    queue = [BackgroundJob(kind=kind) for kind in kinds]
    monkeypatch.setattr(worker, "_claim_one", lambda lane:
                        queue.pop(0) if lane == "ai" and queue else None)

    class Executor:
        def __init__(self):
            self.kinds = []

        def submit(self, operation, job):
            self.kinds.append(job.kind)
            return Future()

    threads, processes = Executor(), Executor()
    active = {lane: set() for lane in worker.WORKER_LANES}
    assert worker._fill_slots(threads, active, {"local": 1, "cloud": 2, "ai": 3},
                              {"retrieval": processes})
    assert len(active["ai"]) == 3
    assert processes.kinds == kinds[:2]
    assert threads.kinds == kinds[2:]


def test_parse_in_child_publishes_revision(session, tmp_path, monkeypatch):
    """Дочерний процесс читает свой SessionLocal; основная БД установки не участвует."""
    monkeypatch.setenv("TENTEX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TENTEX_SQLITE_POOL_SIZE", "0")
    # Фикстура создаёт test.sqlite; Settings дочернего процесса ждёт tentex.sqlite.
    # SQLite backup даёт согласованный снимок без подмены файла открытой базы.
    import sqlite3

    material = make_material(session, "bade")
    source = tmp_path / "storage" / material.storage_path
    source.parent.mkdir(parents=True)
    source.write_text("Первый абзац.\n\nВторой абзац.", encoding="utf-8")
    job = BackgroundJob(
        kind=BackgroundJobKind.PARSE, material_id=material.id, parser_mode=ParserMode.FAST,
        state=BackgroundJobState.RUNNING, lease_owner="test-child",
        lease_expires_at=utc_now() + timedelta(minutes=1), total=1,
        checkpoint={
            "revision": 2, "source_revision": 1, "selected_pages": [1],
            "next_index": 0, "scope": {"kind": "all"},
        },
    )
    session.add(job)
    session.commit()
    session.expunge(job)
    with (
        sqlite3.connect(tmp_path / "test.sqlite") as original,
        sqlite3.connect(tmp_path / "tentex.sqlite") as target,
    ):
        original.backup(target)
    pool = IdleProcessPool(idle_seconds=1)
    try:
        pool.submit(_process_claimed_job, job).result(timeout=30)
    finally:
        pool.close()
    with sqlite3.connect(tmp_path / "tentex.sqlite") as result:
        assert result.execute(
            "SELECT state FROM background_jobs WHERE id=?", (job.id.hex,),
        ).fetchone() == ("completed",)
        assert result.execute(
            "SELECT active_parse_revision FROM materials WHERE id=?", (material.id.hex,),
        ).fetchone() == (2,)
        assert "Первый абзац" in result.execute(
            "SELECT text FROM material_pages WHERE material_id=? AND revision=2",
            (material.id.hex,),
        ).fetchone()[0]
