"""Metadata.create_all не обнаруживает старые CHECK: нужна проверка настоящих миграций."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app import db
from app.config import BACKEND_ROOT, settings
from app.models import BackgroundJob, BackgroundJobKind, BackgroundJobState


def test_upgrade_populated_job_queue_accepts_preparation_and_preserves_old_rows(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    monkeypatch.setattr(db, "engine", engine)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "20260901_0031")
    with Session(engine) as session:
        job = BackgroundJob(kind=BackgroundJobKind.PARSE, checkpoint={"retained": True})
        session.add(job)
        session.commit()
        job_id = job.id
    command.upgrade(config, "head")
    with Session(engine) as session:
        assert session.get(BackgroundJob, job_id).checkpoint == {"retained": True}
        session.add(
            BackgroundJob(kind=BackgroundJobKind.AI_PREPARATION, state=BackgroundJobState.CANCELLED)
        )
        session.commit()
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        assert session.execute(text("PRAGMA quick_check")).scalar() == "ok"
    engine.dispose()
