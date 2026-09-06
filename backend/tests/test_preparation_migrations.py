"""Metadata.create_all не обнаруживает старые CHECK: нужна проверка настоящих миграций."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import db
from app.config import BACKEND_ROOT, settings
from app.models import (
    Activity,
    ActivityKind,
    Attempt,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Grade,
)


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


def test_cards_migration_preserves_attempts_and_backfills_one_activity_per_node(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    monkeypatch.setattr(db, "engine", engine)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "20260905_0037")
    with engine.begin() as connection:
        project_id = "11111111111111111111111111111111"
        node_id = "22222222222222222222222222222222"
        attempt_ids = [
            "33333333333333333333333333333333",
            "44444444444444444444444444444444",
        ]
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, template_key, workspace_variant, status, sort_order, program_revision, "
                "enabled_modules, created_at, updated_at) VALUES "
                "(:id, 'exam', 'exam', 'active', 0, 0, '[]', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": project_id},
        )
        connection.execute(
            text(
                "INSERT INTO program_nodes "
                "(id, project_id, node_type, sort_order, title, is_in_current_program, "
                "needs_material, is_archived, origin_kind, created_at, updated_at) VALUES "
                "(:id, :project, 'topic', 0, 'Вопрос', 1, 0, 0, 'manual', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": node_id, "project": project_id},
        )
        for index, attempt_id in enumerate(attempt_ids, 1):
            connection.execute(
                text(
                    "INSERT INTO attempts "
                    "(id, project_id, program_node_id, ordinal, text, persona, strictness, "
                    "context_snapshot, created_at) VALUES "
                    "(:id, :project, :node, :ordinal, 'Ответ', 'neutral_examiner', "
                    "'normal', '{}', CURRENT_TIMESTAMP)"
                ),
                {
                    "id": attempt_id,
                    "project": project_id,
                    "node": node_id,
                    "ordinal": index,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO grades "
                    "(attempt_id, outcome, method, credited_points, missed_points, "
                    "wrong_points, summary, created_at, updated_at) VALUES "
                    "(:id, 'passed', 'exact_match', '[]', '[]', '[]', '', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": attempt_id},
            )
    command.upgrade(config, "head")
    with Session(engine) as session:
        attempts = list(session.scalars(select(Attempt).order_by(Attempt.ordinal)))
        assert len(attempts) == 2
        assert attempts[0].program_node_id == attempts[1].program_node_id
        assert session.scalar(select(Grade).where(Grade.attempt_id == attempts[0].id))
        activities = list(
            session.scalars(
                select(Activity).where(Activity.kind == ActivityKind.FREE_ANSWER)
            )
        )
        assert len(activities) == 1
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
