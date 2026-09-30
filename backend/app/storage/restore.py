"""Полное восстановление установки с внешним журналом и откатом."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal, dispose_engines, upgrade_database
from app.models import (
    BackgroundJob,
    BackgroundJobState,
    BackupArchive,
    BackupArchiveState,
    BackupKind,
    TransferArtifact,
    TransferKind,
    utc_now,
)
from app.projects.errors import ProjectDomainError
from app.storage import archive, maintenance
from app.storage.schemas import RestoreStartRead, RestoreStatusRead
from app.storage.service import _policy, backup_directory


def _write_journal(payload: dict[str, object]) -> None:
    settings.restore_journal_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = settings.restore_journal_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(settings.restore_journal_path)


def _update(operation_id: UUID, state: str, detail: str, **extra: object) -> None:
    current = read_journal() or {"operation_id": str(operation_id)}
    current.update({"state": state, "detail": detail, **extra})
    _write_journal(current)


def read_journal() -> dict[str, object] | None:
    try:
        return json.loads(settings.restore_journal_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def status(operation_id: UUID) -> RestoreStatusRead:
    row = read_journal()
    if row is None or row.get("operation_id") != str(operation_id):
        raise ProjectDomainError(
            "Операция восстановления не найдена", status=404, code="restore_not_found"
        )
    return RestoreStatusRead.model_validate(row)


def _start_restore_source(session, source: Path) -> RestoreStartRead:
    if not source.is_file():
        raise ProjectDomainError(
            "Файл резервной копии не найден", status=404, code="backup_not_found"
        )
    manifest = archive.validate_backup(source)
    required = int(manifest.get("unpacked_size", source.stat().st_size * 2))
    if shutil.disk_usage(settings.data_dir).free < required * 2:
        raise ProjectDomainError(
            "Недостаточно места для staging и страховочной копии",
            status=422,
            code="insufficient_space",
        )
    operation_id = uuid4()
    _write_journal(
        {
            "operation_id": str(operation_id),
            "state": "waiting",
            "detail": "Ожидаем завершения фоновых задач",
            "source": str(source),
            "safety_backup_id": None,
            "completed_at": None,
        }
    )
    Thread(
        target=_run_restore,
        args=(operation_id, source),
        name=f"restore-{str(operation_id)[:8]}",
        daemon=True,
    ).start()
    return RestoreStartRead(operation_id=operation_id, state="waiting")


def start_restore(session, artifact_id: UUID) -> RestoreStartRead:
    """Запустить восстановление загруженного `.tentex-backup`."""
    artifact = session.get(TransferArtifact, artifact_id)
    if artifact is None or artifact.kind != TransferKind.BACKUP:
        raise ProjectDomainError(
            "Загруженная резервная копия не найдена", status=404, code="backup_not_found"
        )
    return _start_restore_source(session, Path(artifact.file_path))


def start_managed_backup_restore(session, backup_id: UUID) -> RestoreStartRead:
    """Запустить восстановление копии из истории без повторной загрузки файла."""
    row = session.get(BackupArchive, backup_id)
    if row is None or row.state != BackupArchiveState.READY or not row.file_path:
        raise ProjectDomainError(
            "Готовая резервная копия не найдена", status=404, code="backup_not_found"
        )
    return _start_restore_source(session, Path(row.file_path))


def _active_jobs() -> int:
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count()).select_from(BackgroundJob).where(
                    BackgroundJob.state == BackgroundJobState.RUNNING
                )
            )
            or 0
        )


def _safety_backup(operation_id: UUID) -> tuple[UUID, Path, dict[str, object]]:
    with SessionLocal() as session:
        directory = backup_directory(_policy(session))
    backup_id = uuid4()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"tentex-pre-restore-{stamp}-{str(backup_id)[:8]}.tentex-backup"
    manifest = archive.create_backup(
        path, backup_id=backup_id, kind=BackupKind.PRE_RESTORE
    )
    _update(
        operation_id,
        "running",
        "Страховочная копия создана",
        safety_backup_id=str(backup_id),
    )
    return backup_id, path, manifest


def _check_database(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if not result or result[0] != "ok":
        raise ProjectDomainError(
            "База из архива не прошла проверку", status=422, code="backup_corrupt"
        )


def _switch(staging: Path, rollback: Path) -> None:
    """Заменить два поколения после закрытия соединений; rollback остаётся рядом."""
    rollback.mkdir(parents=True, exist_ok=False)
    dispose_engines()
    database_old = rollback / "tentex.sqlite"
    storage_old = rollback / "storage"
    if settings.database_path.exists():
        settings.database_path.replace(database_old)
    if settings.storage_dir.exists():
        settings.storage_dir.replace(storage_old)
    (staging / "database" / "tentex.sqlite").replace(settings.database_path)
    restored_storage = staging / "storage"
    if restored_storage.exists():
        restored_storage.replace(settings.storage_dir)
    else:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)


def _rollback(rollback: Path) -> None:
    dispose_engines()
    if settings.database_path.exists():
        settings.database_path.unlink()
    if settings.storage_dir.exists():
        shutil.rmtree(settings.storage_dir)
    if (rollback / "tentex.sqlite").exists():
        (rollback / "tentex.sqlite").replace(settings.database_path)
    if (rollback / "storage").exists():
        (rollback / "storage").replace(settings.storage_dir)


def _register_safety(backup_id: UUID, path: Path, manifest: dict[str, object]) -> None:
    with SessionLocal() as session, session.begin():
        session.add(
            BackupArchive(
                id=backup_id,
                kind=BackupKind.PRE_RESTORE,
                state=BackupArchiveState.READY,
                file_path=str(path),
                file_name=path.name,
                size_bytes=path.stat().st_size,
                sha256=archive.sha256_file(path),
                manifest=manifest,
                completed_at=utc_now(),
            )
        )


def _run_restore(operation_id: UUID, source: Path) -> None:
    rollback: Path | None = None
    switched = False
    try:
        maintenance.begin("restore", operation_id)
        while _active_jobs():
            _update(operation_id, "waiting", "Ожидаем завершения фоновых задач")
            import time

            time.sleep(0.5)
        _update(operation_id, "running", "Создаём страховочную копию")
        backup_id, safety_path, safety_manifest = _safety_backup(operation_id)
        with tempfile.TemporaryDirectory(
            prefix="tentex-restore-", dir=settings.data_dir
        ) as raw_staging:
            staging_root = Path(raw_staging)
            extracted = staging_root / "extracted"
            archive.extract_backup(source, extracted)
            _check_database(extracted / "database" / "tentex.sqlite")
            rollback = settings.data_dir / f"restore-rollback-{operation_id}"
            _update(operation_id, "running", "Переключаем поколение данных")
            _switch(extracted, rollback)
            switched = True
            upgrade_database()
            _check_database(settings.database_path)
            _register_safety(backup_id, safety_path, safety_manifest)
        if rollback.exists():
            shutil.rmtree(rollback)
        _update(
            operation_id,
            "completed",
            "Установка восстановлена",
            completed_at=datetime.now(UTC).isoformat(),
        )
    except Exception as error:
        if switched and rollback is not None and rollback.exists():
            try:
                _rollback(rollback)
                _update(
                    operation_id,
                    "rolled_back",
                    "Восстановление не удалось; прежние данные возвращены",
                    completed_at=datetime.now(UTC).isoformat(),
                )
            except OSError:
                _update(
                    operation_id,
                    "failed",
                    "Автоматический откат не завершён; данные сохранены в rollback-каталоге",
                    completed_at=datetime.now(UTC).isoformat(),
                )
        else:
            _update(
                operation_id,
                "failed",
                f"Восстановление не выполнено: {type(error).__name__}",
                completed_at=datetime.now(UTC).isoformat(),
            )
    finally:
        maintenance.finish(operation_id)


def recover_interrupted_restore() -> None:
    """На старте вернуть старое поколение, если процесс умер после переключения."""
    row = read_journal()
    if not row or row.get("state") not in {"waiting", "running"}:
        return
    operation_id = UUID(str(row["operation_id"]))
    rollback = settings.data_dir / f"restore-rollback-{operation_id}"
    if rollback.exists():
        _rollback(rollback)
        _update(
            operation_id,
            "rolled_back",
            "Прерванное восстановление автоматически отменено при запуске",
            completed_at=datetime.now(UTC).isoformat(),
        )
    maintenance.finish(operation_id)
