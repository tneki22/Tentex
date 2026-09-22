"""Бизнес-логика политики хранения и управляемых полных копий."""

from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, job_write_transaction, retry_on_locked
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    BackupArchive,
    BackupArchiveState,
    BackupKind,
    Material,
    StorageSettings,
    TransferArtifact,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from app.storage import archive, maintenance
from app.storage.schemas import (
    BackupArchiveRead,
    BackupCreateRead,
    BackupPolicyRead,
    BackupPolicyWrite,
    MaintenanceResult,
    StorageBreakdown,
    StorageSnapshot,
)

WAIT_INTERVAL_SECONDS = 0.5


def _policy(session: Session) -> StorageSettings:
    row = session.get(StorageSettings, 1)
    if row is None:
        row = StorageSettings(id=1)
        session.add(row)
        session.flush()
    return row


def backup_directory(row: StorageSettings) -> Path:
    candidate = Path(row.backup_directory) if row.backup_directory else settings.default_backup_dir
    return maintenance.ensure_directory(candidate)


def read_policy(session: Session) -> BackupPolicyRead:
    row = _policy(session)
    return BackupPolicyRead(
        automatic_enabled=row.automatic_enabled,
        daily_time=row.daily_time,
        retention_days=row.retention_days,
        backup_directory=row.backup_directory,
        last_automatic_date=row.last_automatic_date,
    )


def update_policy(session: Session, command: BackupPolicyWrite) -> BackupPolicyRead:
    """Путь проверяется записью до транзакции, чтобы не сохранить тупиковое значение."""
    normalized = None
    if command.backup_directory:
        normalized = str(maintenance.ensure_directory(Path(command.backup_directory)))
    with session.begin():
        row = _policy(session)
        row.automatic_enabled = command.automatic_enabled
        row.daily_time = command.daily_time
        row.retention_days = command.retention_days
        row.backup_directory = normalized
        row.updated_at = utc_now()
    session.expire_all()
    return read_policy(session)


def _tree_size(path: Path, *, exclude: set[str] | None = None) -> int:
    if not path.exists():
        return 0
    excluded = exclude or set()
    total = 0
    for item in path.rglob("*"):
        try:
            relative = item.relative_to(path)
            if relative.parts and relative.parts[0] in excluded:
                continue
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def storage_snapshot(session: Session) -> StorageSnapshot:
    policy_row = _policy(session)
    backups = backup_directory(policy_row)
    database = settings.database_path.stat().st_size if settings.database_path.exists() else 0
    # Не обходить bind-mounted каталоги на каждый GET: на Windows/Docker Desktop
    # stat для тысяч производных файлов блокирует экран на десятки секунд. База
    # уже хранит размеры исходников и управляемых архивов, поэтому их сводка
    # получается мгновенно; очистка/проверка остаются точными операциями по кнопке.
    files = int(session.scalar(select(func.coalesce(func.sum(Material.size_bytes), 0))) or 0)
    temporary = int(
        session.scalar(select(func.coalesce(func.sum(TransferArtifact.size_bytes), 0))) or 0
    )
    # В отличие от `storage/` (тысячи страниц и фрагментов) моделей и
    # Typst-пакетов немного и они крупные: обход дерева здесь остаётся быстрым.
    models = _tree_size(settings.embedding_models_dir) + _tree_size(
        settings.typst_package_cache_dir
    )
    backup_bytes = int(
        session.scalar(
            select(func.coalesce(func.sum(BackupArchive.size_bytes), 0)).where(
                BackupArchive.state == BackupArchiveState.READY
            )
        )
        or 0
    )
    usage = shutil.disk_usage(settings.data_dir)
    latest = session.scalar(
        select(func.max(BackupArchive.completed_at)).where(
            BackupArchive.state == BackupArchiveState.READY
        )
    )
    return StorageSnapshot(
        data_directory=str(settings.data_dir.resolve()),
        backup_directory=str(backups),
        same_disk_warning=Path(settings.data_dir).drive == backups.drive,
        used_bytes=database + files + temporary + models + backup_bytes,
        free_bytes=usage.free,
        breakdown=StorageBreakdown(
            database=database,
            files=files,
            models=models,
            backups=backup_bytes,
            temporary=temporary,
        ),
        policy=read_policy(session),
        last_backup_at=latest,
        maintenance=maintenance.active(),
    )


def list_backups(session: Session) -> list[BackupArchiveRead]:
    rows = session.scalars(select(BackupArchive).order_by(BackupArchive.created_at.desc()))
    return [BackupArchiveRead.model_validate(row) for row in rows]


def backup_or_404(session: Session, backup_id: UUID) -> BackupArchive:
    row = session.get(BackupArchive, backup_id)
    if row is None:
        raise ProjectNotFoundError("Резервная копия не найдена", code="backup_not_found")
    return row


def start_backup(session: Session, kind: BackupKind = BackupKind.MANUAL) -> BackupCreateRead:
    if maintenance.active():
        raise ProjectConflictError(
            "Другая операция уже использует хранилище", code="maintenance_busy"
        )
    with session.begin():
        existing = session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.kind == BackgroundJobKind.BACKUP_CREATE,
                BackgroundJob.state.in_(
                    [BackgroundJobState.QUEUED, BackgroundJobState.RUNNING]
                ),
            )
        )
        if existing is not None:
            archive_row = session.scalar(
                select(BackupArchive).where(BackupArchive.job_id == existing.id)
            )
            if archive_row is not None:
                return BackupCreateRead(backup_id=archive_row.id, job_id=existing.id)
        backup_id = uuid4()
        job = BackgroundJob(
            id=uuid4(),
            kind=BackgroundJobKind.BACKUP_CREATE,
            state=BackgroundJobState.QUEUED,
            checkpoint={"backup_id": str(backup_id)},
            diagnostics=[],
        )
        row = BackupArchive(
            id=backup_id,
            kind=kind,
            state=BackupArchiveState.QUEUED,
            job_id=job.id,
        )
        session.add_all([job, row])
    return BackupCreateRead(backup_id=backup_id, job_id=job.id)


def _wait_for_other_jobs(job_id: UUID) -> None:
    """Не отменять работу: обслуживание начнётся, когда остальные leases завершатся."""
    while True:
        with SessionLocal() as session:
            active_count = session.scalar(
                select(func.count()).select_from(BackgroundJob).where(
                    BackgroundJob.id != job_id,
                    BackgroundJob.state == BackgroundJobState.RUNNING,
                )
            )
        if not active_count:
            return
        time.sleep(WAIT_INTERVAL_SECONDS)


def _update_progress(job_id: UUID, done: int, total: int) -> None:
    def write() -> None:
        with SessionLocal() as session, job_write_transaction(session, job_id):
            job = session.get(BackgroundJob, job_id)
            if job is not None:
                job.done = done
                job.total = total
                job.updated_at = utc_now()

    retry_on_locked(write)


def process_backup_job(session: Session, detached_job: BackgroundJob) -> None:
    """Worker-путь: дождаться покоя, снять SQLite и упаковать файловый слой.

    Каждый переход состояния ретраится через `retry_on_locked`: параллельные
    AI-задачи (полоса `ai`, до 8 одновременно) держат writer короткими
    транзакциями, и однократная запись сюда иногда попадает в чужой busy-момент —
    22.09.2026 так падало само создание копии на первом же `CREATING`.
    """
    job_id = detached_job.id
    backup_id = UUID(str(detached_job.checkpoint["backup_id"]))
    try:
        def _mark_creating() -> None:
            if session.in_transaction():
                session.rollback()
            with session.begin():
                row = session.get(BackupArchive, backup_id)
                if row is None:
                    raise ProjectNotFoundError(
                        "Резервная копия не найдена", code="backup_not_found"
                    )
                row.state = BackupArchiveState.CREATING

        retry_on_locked(_mark_creating)
        with maintenance.lock("backup", backup_id):
            _wait_for_other_jobs(job_id)
            with SessionLocal() as read_session:
                row = backup_or_404(read_session, backup_id)
                directory = backup_directory(_policy(read_session))
                kind = row.kind
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            file_name = f"tentex-{kind.value}-{stamp}-{str(backup_id)[:8]}.tentex-backup"
            destination = directory / file_name
            manifest = archive.create_backup(
                destination,
                backup_id=backup_id,
                kind=kind,
                progress=lambda done, total: _update_progress(job_id, done, total),
            )
        def _mark_ready() -> None:
            if session.in_transaction():
                session.rollback()
            with job_write_transaction(session, job_id):
                row = session.get(BackupArchive, backup_id)
                job = session.get(BackgroundJob, job_id)
                assert row is not None and job is not None
                row.state = BackupArchiveState.READY
                row.file_path = str(destination)
                row.file_name = file_name
                row.size_bytes = destination.stat().st_size
                row.sha256 = archive.sha256_file(destination)
                row.manifest = manifest
                row.completed_at = utc_now()
                job.state = BackgroundJobState.COMPLETED
                job.done = job.total
                job.completed_at = utc_now()
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = utc_now()

        retry_on_locked(_mark_ready)
    except Exception as error:
        session.rollback()
        error_message = str(error)

        def _mark_failed() -> None:
            if session.in_transaction():
                session.rollback()
            with job_write_transaction(session, job_id):
                row = session.get(BackupArchive, backup_id)
                job = session.get(BackgroundJob, job_id)
                if row is not None:
                    row.state = BackupArchiveState.FAILED
                    row.error = "Не удалось создать резервную копию"
                if job is not None:
                    job.state = BackgroundJobState.FAILED
                    job.error = error_message
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.updated_at = utc_now()

        retry_on_locked(_mark_failed)
        raise


def backup_file(session: Session, backup_id: UUID) -> Path:
    row = backup_or_404(session, backup_id)
    if row.state != BackupArchiveState.READY or not row.file_path:
        raise ProjectConflictError("Копия ещё не готова", code="backup_not_ready")
    path = Path(row.file_path).resolve()
    if not path.is_file():
        raise ProjectConflictError("Файл копии не найден на диске", code="backup_file_missing")
    return path


def delete_backup(session: Session, backup_id: UUID) -> None:
    row = backup_or_404(session, backup_id)
    if row.state == BackupArchiveState.CREATING:
        raise ProjectConflictError("Идущую копию нельзя удалить", code="backup_busy")
    path = Path(row.file_path).resolve() if row.file_path else None
    session.rollback()
    with session.begin():
        row = backup_or_404(session, backup_id)
        session.delete(row)
    if path and path.is_file():
        path.unlink()


def _start_maintenance_job(
    session: Session, kind: BackgroundJobKind
) -> UUID:
    """Проверка и очистка идут воркером: `PRAGMA quick_check` по базе в
    сотни мегабайт на Windows bind-mount под Docker Desktop занимает минуты —
    22.09.2026 такой вызов из HTTP-запроса завис на 105с без обратной связи.
    """
    if maintenance.active():
        raise ProjectConflictError(
            "Другая операция уже использует хранилище", code="maintenance_busy"
        )
    with session.begin():
        existing = session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.kind == kind,
                BackgroundJob.state.in_(
                    [BackgroundJobState.QUEUED, BackgroundJobState.RUNNING]
                ),
            )
        )
        if existing is not None:
            return existing.id
        job = BackgroundJob(
            id=uuid4(), kind=kind, state=BackgroundJobState.QUEUED, checkpoint={}
        )
        session.add(job)
    return job.id


def start_storage_verify(session: Session) -> UUID:
    return _start_maintenance_job(session, BackgroundJobKind.STORAGE_VERIFY)


def start_storage_cleanup(session: Session) -> UUID:
    return _start_maintenance_job(session, BackgroundJobKind.STORAGE_CLEANUP)


def verify_storage() -> MaintenanceResult:
    connection = sqlite3.connect(str(settings.database_path))
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            return MaintenanceResult(ok=False, detail="SQLite сообщила об ошибке целостности")
        paths = [row[0] for row in connection.execute("SELECT storage_path FROM materials")]
    finally:
        connection.close()
    missing = [relative for relative in paths if not (settings.storage_dir / relative).is_file()]
    return MaintenanceResult(
        ok=not missing,
        detail=("Хранилище исправно" if not missing else "Часть исходных файлов не найдена"),
        checked_files=len(paths),
        missing_files=missing[:100],
    )


def cleanup_storage(session: Session) -> MaintenanceResult:
    """Удалить только явный staging и просроченные экспортные артефакты."""
    before = _tree_size(settings.storage_dir / "tmp") + _tree_size(settings.transfer_dir)
    shutil.rmtree(settings.storage_dir / "tmp", ignore_errors=True)
    (settings.storage_dir / "tmp").mkdir(parents=True, exist_ok=True)
    now = utc_now()
    expired = list(
        session.scalars(select(TransferArtifact).where(TransferArtifact.expires_at < now))
    )
    expired_items = [(artifact.id, artifact.file_path) for artifact in expired]

    def _delete_expired() -> None:
        if session.in_transaction():
            session.rollback()
        with session.begin():
            for artifact_id, file_path in expired_items:
                artifact = session.get(TransferArtifact, artifact_id)
                if artifact is None:
                    continue
                Path(file_path).unlink(missing_ok=True)
                session.delete(artifact)

    retry_on_locked(_delete_expired)
    after = _tree_size(settings.storage_dir / "tmp") + _tree_size(settings.transfer_dir)
    return MaintenanceResult(
        ok=True,
        detail="Временные файлы очищены",
        freed_bytes=max(0, before - after),
    )


def process_storage_maintenance(session: Session, detached_job: BackgroundJob) -> None:
    """Выполнить отложенную проверку или очистку и сохранить результат в job."""
    job_id = detached_job.id
    try:
        if detached_job.kind == BackgroundJobKind.STORAGE_VERIFY:
            result = verify_storage()
        elif detached_job.kind == BackgroundJobKind.STORAGE_CLEANUP:
            result = cleanup_storage(session)
        else:
            raise ProjectConflictError(
                "Неизвестная операция обслуживания", code="storage_job_invalid"
            )
        def _mark_completed() -> None:
            if session.in_transaction():
                session.rollback()
            with job_write_transaction(session, job_id):
                job = session.get(BackgroundJob, job_id)
                if job is not None:
                    job.checkpoint = {**job.checkpoint, "result": result.model_dump(mode="json")}
                    job.state = BackgroundJobState.COMPLETED
                    job.done = 1
                    job.total = 1
                    job.completed_at = utc_now()
                    job.lease_owner = None
                    job.lease_expires_at = None

        retry_on_locked(_mark_completed)
    except Exception as error:
        session.rollback()
        error_message = str(error)

        def _mark_failed() -> None:
            if session.in_transaction():
                session.rollback()
            with job_write_transaction(session, job_id):
                job = session.get(BackgroundJob, job_id)
                if job is not None:
                    job.state = BackgroundJobState.FAILED
                    job.error = error_message
                    job.lease_owner = None
                    job.lease_expires_at = None

        retry_on_locked(_mark_failed)
        raise


def enqueue_due_automatic_backup() -> None:
    """Один worker ставит пропущенную дневную копию при первом опросе после времени."""
    today = date.today()
    now = datetime.now().time()
    with SessionLocal() as session:
        row = _policy(session)
        hour, minute = (int(part) for part in row.daily_time.split(":"))
        if not row.automatic_enabled or row.last_automatic_date == today:
            session.rollback()
            return
        if now < day_time(hour=hour, minute=minute):
            session.rollback()
            return
        session.rollback()
        start_backup(session, BackupKind.AUTOMATIC)
        with session.begin():
            _policy(session).last_automatic_date = today
        purge_expired_backups(session)


def purge_expired_backups(session: Session) -> None:
    """Ручные копии бессрочны; automatic/pre_restore живут заданное число дней."""
    row = _policy(session)
    threshold = utc_now() - timedelta(days=row.retention_days)
    expired = list(
        session.scalars(
            select(BackupArchive).where(
                BackupArchive.kind.in_([BackupKind.AUTOMATIC, BackupKind.PRE_RESTORE]),
                BackupArchive.created_at < threshold,
                BackupArchive.state != BackupArchiveState.CREATING,
            )
        )
    )
    expired_items = [(item.id, item.file_path) for item in expired]
    paths = [Path(file_path) for _, file_path in expired_items if file_path]
    session.rollback()
    with session.begin():
        for backup_id, _ in expired_items:
            item = session.get(BackupArchive, backup_id)
            if item is not None:
                session.delete(item)
    for path in paths:
        path.unlink(missing_ok=True)
