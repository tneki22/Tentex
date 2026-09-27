"""Сводка «Состояние»: сценарии из плана вкладки и журнал сбоев."""

import errno
import logging
import sqlite3
from collections import namedtuple
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, get_session, retry_on_locked
from app.main import create_app
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    AiSettings,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    BackupArchive,
    BackupArchiveState,
    BackupKind,
    EmbeddingBackendKind,
    EmbeddingProfile,
    Material,
    MaterialSourceKind,
    MaterialState,
    OcrSettings,
    ParserMode,
    RetrievalIndex,
    RetrievalIndexState,
    RetrievalSettings,
    StorageSettings,
    utc_now,
)
from app.ocr import downloads as ocr_downloads
from app.storage import service as storage_service
from app.system import diagnostics, service
from app.system.schemas import SystemStatusRead

GIB = 1024**3
DiskUsage = namedtuple("DiskUsage", "total used free")


@pytest.fixture
def status_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Установка во временной папке: сводка открывает саму базу по пути из настроек."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.storage_dir.mkdir(parents=True)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        service.shutil, "disk_usage", lambda _: DiskUsage(500 * GIB, 300 * GIB, 200 * GIB)
    )
    monkeypatch.setattr(service, "_models_size_cache", None)
    monkeypatch.setattr(ocr_downloads, "engine_ready", lambda engine: True)
    diagnostics.touch_worker_heartbeat()
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _codes(status: SystemStatusRead) -> dict[str, str]:
    return {item.code: item.level for item in status.items}


def _item(status: SystemStatusRead, code: str):
    return next(item for item in status.items if item.code == code)


def _add_material(session: Session) -> None:
    session.add(
        Material(
            id=uuid4(),
            sha256=uuid4().hex.rjust(64, "0"),
            original_name="Лекции.txt",
            storage_path="materials/lectures.txt",
            media_type="text/plain",
            source_kind=MaterialSourceKind.TEXT,
            size_bytes=1024,
            status=MaterialState.READY,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    session.commit()


def _add_backup(session: Session, *, state: BackupArchiveState, age: timedelta = timedelta()):
    created = utc_now() - age
    session.add(
        BackupArchive(
            id=uuid4(),
            kind=BackupKind.MANUAL,
            state=state,
            size_bytes=2048 if state == BackupArchiveState.READY else None,
            created_at=created,
            completed_at=created,
        )
    )
    session.commit()


def _enable_ai(session: Session, *, with_key: bool = True, with_model: bool = True) -> None:
    from app.ai.credentials import encrypt_secret

    provider_id = uuid4()
    session.add(
        AiProviderConnection(
            id=provider_id,
            label="Тестовый провайдер",
            catalog_profile="openai_compatible",
            base_url="https://example.test/v1",
            api_key_ciphertext=encrypt_secret("secret") if with_key else None,
        )
    )
    session.flush()
    now = utc_now()
    session.add(
        AiModelCatalogEntry(
            provider_id=provider_id,
            model_id="test/text",
            display_name="Тестовая текстовая",
            input_modalities=["text", "image"],
            output_modalities=["text"],
            pricing_snapshot_at=now,
            catalog_snapshot_at=now,
            is_manually_added=True,
            is_available=True,
        )
    )
    session.add(
        AiSettings(
            id=1,
            external_models_enabled=True,
            confirm_input_tokens=20_000,
            default_text_provider_id=provider_id if with_model else None,
            default_text_model_id="test/text" if with_model else None,
            default_vision_provider_id=provider_id,
            default_vision_model_id="test/text",
        )
    )
    session.commit()


def _activate_index(session: Session) -> None:
    profile = EmbeddingProfile(
        id=uuid4(),
        label="E5",
        backend_kind=EmbeddingBackendKind.LOCAL_HF,
        model_id="intfloat/multilingual-e5-base",
        installed=True,
    )
    session.add(profile)
    session.flush()
    index = RetrievalIndex(
        id=uuid4(),
        profile_id=profile.id,
        state=RetrievalIndexState.ACTIVE,
        indexed_material_count=3,
        material_count=3,
    )
    session.add(index)
    session.flush()
    session.add(RetrievalSettings(id=1, active_index_id=index.id, default_profile_id=profile.id))
    session.commit()


def test_healthy_installation_is_ok_with_green_capabilities(status_session: Session) -> None:
    _add_material(status_session)
    _add_backup(status_session, state=BackupArchiveState.READY)
    _enable_ai(status_session)
    _activate_index(status_session)
    status_session.add(
        StorageSettings(id=1, automatic_enabled=True, backup_directory=str(Path.cwd()))
    )
    status_session.commit()

    status = service.system_status(status_session)

    assert status.overall == "ok"
    assert status.attention_count == 0
    codes = _codes(status)
    assert codes["ai_ready"] == "ok"
    assert codes["ocr_ready"] == "ok"
    assert codes["search_semantic_ready"] == "ok"
    assert status.storage is not None
    assert status.storage.last_backup_at is not None
    assert status.storage.last_backup_at.tzinfo is not None
    assert status.storage.automatic_enabled is True
    assert status.storage.used_bytes and status.storage.free_bytes == 200 * GIB


def test_disabled_external_models_and_search_are_neutral(status_session: Session) -> None:
    status = service.system_status(status_session)

    codes = _codes(status)
    assert codes["ai_disabled"] == "info"
    assert codes["search_semantic_off"] == "info"
    # Облачное распознавание не настроено по той же причине — второй строкой не звучит.
    assert "ocr_cloud_off" not in codes
    assert status.overall == "ok"
    assert _item(status, "ai_disabled").target.href.endswith("section=ai&subsection=overview")


def test_enabled_models_without_provider_name_the_first_missing_step(
    status_session: Session,
) -> None:
    status_session.add(AiSettings(id=1, external_models_enabled=True, confirm_input_tokens=1))
    status_session.commit()

    status = service.system_status(status_session)

    item = _item(status, "ai_no_provider")
    assert item.level == "warning" and item.section == "attention"
    assert item.target.href.endswith("subsection=providers")
    assert "ai_no_key" not in _codes(status)
    assert status.overall == "warning"


def test_enabled_models_without_key_or_text_model(status_session: Session) -> None:
    _enable_ai(status_session, with_key=False)
    assert "ai_no_key" in _codes(service.system_status(status_session))


def test_missing_text_model_points_to_defaults(status_session: Session) -> None:
    _enable_ai(status_session, with_model=False)
    item = _item(service.system_status(status_session), "ai_no_text_model")
    assert item.target.href.endswith("subsection=defaults")


def test_cloud_ocr_default_with_models_off_is_one_warning(status_session: Session) -> None:
    status_session.add(OcrSettings(id=1, default_mode=ParserMode.CLOUD))
    status_session.commit()

    status = service.system_status(status_session)

    codes = _codes(status)
    assert codes["ocr_not_ready"] == "warning"
    assert "ai_disabled" not in codes
    assert _item(status, "ocr_not_ready").target.href.endswith("section=ocr&subsection=engines")


def test_fast_ocr_without_models_is_neutral(
    status_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr_downloads, "engine_ready", lambda engine: False)
    status = service.system_status(status_session)
    assert _codes(status)["ocr_fast_no_models"] == "info"
    assert status.overall == "ok"


def test_data_without_backup_asks_for_first_copy(status_session: Session) -> None:
    _add_material(status_session)

    item = _item(service.system_status(status_session), "backup_missing")

    assert item.level == "warning"
    assert item.target.kind == "command" and item.target.command == "create_backup"


def test_first_copy_in_progress_is_not_a_warning(status_session: Session) -> None:
    _add_material(status_session)
    status_session.add(
        BackgroundJob(id=uuid4(), kind=BackgroundJobKind.BACKUP_CREATE, checkpoint={})
    )
    status_session.commit()
    codes = _codes(service.system_status(status_session))
    assert codes["backup_in_progress"] == "info"
    assert "backup_missing" not in codes


def test_disabled_schedule_after_first_copy_is_neutral(status_session: Session) -> None:
    _add_material(status_session)
    _add_backup(status_session, state=BackupArchiveState.READY, age=timedelta(days=30))
    status = service.system_status(status_session)
    assert "backup_missing" not in _codes(status)
    assert "backup_overdue" not in _codes(status)
    assert status.storage is not None and status.storage.automatic_enabled is False


def test_overdue_automatic_copy_and_backups_inside_data(status_session: Session) -> None:
    _add_material(status_session)
    _add_backup(status_session, state=BackupArchiveState.READY, age=timedelta(days=4))
    status_session.add(StorageSettings(id=1, automatic_enabled=True))
    status_session.commit()

    codes = _codes(service.system_status(status_session))

    assert codes["backup_overdue"] == "warning"
    # Каталог по умолчанию лежит в data/ — это достоверно известно, но нейтрально.
    assert codes["backups_inside_data"] == "info"


def test_failed_copy_is_reported_until_a_new_one_succeeds(status_session: Session) -> None:
    _add_backup(status_session, state=BackupArchiveState.FAILED)
    assert "backup_failed" in _codes(service.system_status(status_session))
    _add_backup(status_session, state=BackupArchiveState.READY, age=timedelta(seconds=-1))
    assert "backup_failed" not in _codes(service.system_status(status_session))


def test_failed_first_copy_is_one_row_with_retry(status_session: Session) -> None:
    _add_material(status_session)
    _add_backup(status_session, state=BackupArchiveState.FAILED)

    status = service.system_status(status_session)

    codes = _codes(status)
    assert "backup_missing" not in codes
    item = _item(status, "backup_failed")
    assert item.title == "Не удалось создать первую копию"
    assert item.target.command == "create_backup"
    assert status.attention_count == 1


@pytest.mark.parametrize(("free", "level"), [(3 * GIB, "warning"), (GIB // 2, "danger")])
def test_low_disk_space(
    status_session: Session, monkeypatch: pytest.MonkeyPatch, free: int, level: str
) -> None:
    monkeypatch.setattr(service.shutil, "disk_usage", lambda _: DiskUsage(100 * GIB, 0, free))
    status = service.system_status(status_session)
    item = _item(status, "disk_low")
    assert item.level == level
    assert item.title.startswith("На диске осталось")
    assert item.target.href.endswith("section=storage&subsection=overview")


def test_failed_storage_verify_and_missing_files(status_session: Session) -> None:
    status_session.add(
        BackgroundJob(
            id=uuid4(),
            kind=BackgroundJobKind.STORAGE_VERIFY,
            state=BackgroundJobState.COMPLETED,
            checkpoint={"result": {"ok": False, "detail": "", "missing_files": ["a", "b"]}},
            completed_at=utc_now(),
        )
    )
    status_session.commit()
    item = _item(service.system_status(status_session), "storage_files_missing")
    assert item.title.endswith(": 2")
    assert item.target.href.endswith("subsection=maintenance")


def test_failed_jobs_and_silent_worker(status_session: Session) -> None:
    status_session.add_all(
        [
            BackgroundJob(
                id=uuid4(), kind=BackgroundJobKind.PARSE, state=BackgroundJobState.FAILED,
                checkpoint={},
            ),
            BackgroundJob(id=uuid4(), kind=BackgroundJobKind.PARSE, checkpoint={}),
        ]
    )
    status_session.commit()
    diagnostics._worker_path().unlink()

    status = service.system_status(status_session)

    assert _item(status, "jobs_failed").target.command == "open_background_jobs"
    worker = _item(status, "worker_offline")
    assert worker.level == "danger" and "1 задача ждёт" in worker.title
    assert status.overall == "attention"


def test_single_retried_lock_is_hidden_but_repeated_exhaustion_is_shown(
    status_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostics, "DEDUP_SECONDS", 0.0)
    diagnostics.record_failure("database_locked", kind="exhausted")
    assert "database_locked" not in _codes(service.system_status(status_session))

    diagnostics.record_failure("database_locked", kind="exhausted")
    status = service.system_status(status_session)
    item = _item(status, "database_locked")
    assert item.level == "danger" and item.occurrences == 2
    assert item.target.command == "probe_database"


def test_lock_warning_stays_until_write_probe_succeeds(
    status_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    diagnostics.record_failure("database_locked")
    blocker = sqlite3.connect(str(settings.database_path), isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(service, "PROBE_TIMEOUT_SECONDS", 0.1)
    try:
        failed = service.probe_write_access(status_session)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert failed.ok is False
    assert "database_locked" in _codes(failed.status)

    # Проверка статуса сама сбой не снимает — только подтверждённая запись.
    assert "database_locked" in _codes(service.system_status(status_session))
    recovered = service.probe_write_access(status_session)
    assert recovered.ok is True
    assert "database_locked" not in _codes(recovered.status)


def test_integrity_error_is_cleared_only_by_successful_verify(status_session: Session) -> None:
    diagnostics.record_failure("database_corrupt")
    assert _item(service.system_status(status_session), "database_corrupt").target.command == (
        "verify_storage"
    )
    service.probe_write_access(status_session)
    assert "database_corrupt" in _codes(service.system_status(status_session))

    result = storage_service.verify_storage()

    assert result.ok is True
    assert "database_corrupt" not in _codes(service.system_status(status_session))


def test_missing_database_skips_dependent_checks(
    status_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path / "empty")
    (tmp_path / "empty").mkdir()

    status = service.system_status(status_session)

    codes = _codes(status)
    assert codes["database_missing"] == "danger"
    assert codes["dependent_unchecked"] == "unknown"
    assert "ai_disabled" not in codes
    assert status.storage is not None and status.storage.used_bytes is None
    assert status.overall == "attention"


def test_one_failing_check_does_not_hide_the_others(
    status_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("проверка упала")

    monkeypatch.setattr(service, "_check_ocr", broken)

    status = service.system_status(status_session)

    codes = _codes(status)
    assert codes["ocr_unchecked"] == "unknown"
    assert _item(status, "ocr_unchecked").title == "Не удалось проверить распознавание"
    assert "ai_disabled" in codes and "search_semantic_off" in codes
    # Неизвестное не подменяется зелёным.
    assert status.overall == "warning"


def test_ai_daily_limit(status_session: Session) -> None:
    from app.models import AiRun

    _enable_ai(status_session)
    settings_row = status_session.get(AiSettings, 1)
    settings_row.daily_limit_usd = Decimal("1")
    status_session.add(
        AiRun(
            id=uuid4(),
            role="test",
            modality="text",
            status="succeeded",
            requested_model_id="test/text",
            prompt_version="v1",
            request_hash="hash",
            estimated_input_tokens=1,
            estimated_output_tokens=1,
            actual_cost_usd=Decimal("1.5"),
            created_at=utc_now(),
        )
    )
    status_session.commit()
    item = _item(service.system_status(status_session), "ai_limit_reached")
    assert "$1.50 из $1.00" in item.action


def test_classify_wrapped_sqlite_errors() -> None:
    locked = OperationalError("UPDATE x", {}, sqlite3.OperationalError("database is locked"))
    assert diagnostics.classify(locked) == "database_locked"
    try:
        try:
            raise sqlite3.DatabaseError("database disk image is malformed")
        except sqlite3.DatabaseError as error:
            raise RuntimeError("операция не удалась") from error
    except RuntimeError as wrapped:
        assert diagnostics.classify(wrapped) == "database_corrupt"
    assert diagnostics.classify(OSError(errno.ENOSPC, "No space left")) == "disk_full"
    assert diagnostics.classify(ValueError("database is locked")) is None


def test_logged_failure_is_journaled_without_raw_text(isolated_diagnostics: Path) -> None:
    handler = diagnostics.DiagnosticsHandler()
    logger = logging.getLogger("tentex.test.diagnostics")
    logger.addHandler(handler)
    try:
        try:
            raise sqlite3.OperationalError("disk I/O error at /secret/path.sqlite")
        except sqlite3.OperationalError:
            logger.exception("операция упала")
    finally:
        logger.removeHandler(handler)
    journal = (isolated_diagnostics / "events.jsonl").read_text(encoding="utf-8")
    assert '"code": "database_io"' in journal
    assert "secret" not in journal and "I/O" not in journal


def test_diagnostics_handler_survives_alembic_logging_setup() -> None:
    """Миграции при старте API читают alembic.ini и заменяют обработчики корня."""
    from logging.config import fileConfig

    from app.config import BACKEND_ROOT
    from app.logging_config import configure_logging

    configure_logging()
    fileConfig(str(BACKEND_ROOT / "alembic.ini"), disable_existing_loggers=False)

    handlers = logging.getLogger("tentex").handlers
    assert any(isinstance(handler, diagnostics.DiagnosticsHandler) for handler in handlers)


def test_is_configured_reflects_configure_logging_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Флаг configure_logging не протухает: migrations/env.py использует его для fileConfig."""
    import app.logging_config as logging_config

    monkeypatch.setattr(logging_config, "_CONFIGURED", False)
    assert logging_config.is_configured() is False
    monkeypatch.setattr(logging_config, "_CONFIGURED", True)
    assert logging_config.is_configured() is True


def test_exhausted_retry_is_journaled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.db.time.sleep", lambda _: None)

    def always_locked() -> None:
        raise OperationalError("UPDATE", {}, sqlite3.OperationalError("database is locked"))

    with pytest.raises(OperationalError):
        retry_on_locked(always_locked, attempts=2)
    problems = diagnostics.active_problems()
    # Одна исчерпанная серия — ещё не устойчивая блокировка.
    assert problems == []


def test_status_endpoint(status_session: Session) -> None:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: status_session
    client = TestClient(app)

    response = client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] in {"ok", "warning", "attention"}
    assert {item["section"] for item in body["items"]} <= {"attention", "storage", "capabilities"}
    probe = client.post("/api/system/write-probe")
    assert probe.status_code == 200 and probe.json()["ok"] is True
