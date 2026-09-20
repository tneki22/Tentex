"""Миграция имени материала сохраняет старые строки и допускает откат."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app import db
from app.config import BACKEND_ROOT, settings


def test_material_metadata_migration_backfills_display_name(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    monkeypatch.setattr(db, "engine", engine)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "20260918_0049")
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO materials
            (id, sha256, original_name, storage_path, media_type, source_kind,
             size_bytes, status, active_parse_revision, scan_page_count,
             ocr_low_page_count, outline, diagnostics, created_at, updated_at)
            VALUES ('11111111111111111111111111111111',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    'lecture.pdf', 'materials/lecture.pdf', 'application/pdf', 'file',
                    10, 'ready_to_process', 0, 0, 0, '[]', '[]',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
        )

    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT display_name, subject FROM materials")
        ).one() == ("lecture.pdf", None)

    command.downgrade(config, "20260918_0049")
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(materials)"))}
        assert "display_name" not in columns
        assert "subject" not in columns
        assert connection.execute(text("PRAGMA quick_check")).scalar() == "ok"
    engine.dispose()
