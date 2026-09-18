"""Аддитивность 0049 и ограничения SQLite проверяются на реальной старой схеме."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app import db
from app.config import BACKEND_ROOT, settings


def test_upgrade_downgrade_on_disposable_copy_preserves_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    monkeypatch.setattr(db, "engine", engine)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "20260915_0048")
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO background_jobs
            (id, kind, state, done, total, checkpoint, diagnostics,
             pause_requested, created_at, updated_at)
            VALUES ('11111111111111111111111111111111', 'parse', 'paused', 1, 2, '{}', '[]', 0,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
        )
    for revision in ("head", "20260915_0048", "head"):
        if revision == "head":
            command.upgrade(config, revision)
            command.check(config)
        else:
            command.downgrade(config, revision)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT kind, state, done, total FROM background_jobs")
            ).one() == ("parse", "paused", 1, 2)
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert connection.execute(text("PRAGMA quick_check")).scalar() == "ok"
    engine.dispose()
