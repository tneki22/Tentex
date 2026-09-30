"""HTTP-контракт раздела «Хранилище»."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.background.schemas import BackgroundJobStartRead
from app.db import get_session
from app.models import BackupKind
from app.storage import project_transfer, restore, service, uploads
from app.storage.schemas import (
    BackupArchiveRead,
    BackupCreateRead,
    BackupPolicyRead,
    BackupPolicyWrite,
    ProjectExportCommand,
    ProjectExportRead,
    ProjectImportCommand,
    ProjectImportRead,
    RestoreStartRead,
    RestoreStatusRead,
    StorageSnapshot,
    TransferUploadRead,
)

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api", tags=["storage"])


@router.get("/settings/storage", response_model=StorageSnapshot)
def get_storage_settings(session: SessionDependency) -> StorageSnapshot:
    return service.storage_snapshot(session)


@router.put("/settings/storage/backup-policy", response_model=BackupPolicyRead)
def put_backup_policy(
    command: BackupPolicyWrite, session: SessionDependency
) -> BackupPolicyRead:
    return service.update_policy(session, command)


@router.get("/backups", response_model=list[BackupArchiveRead])
def get_backups(session: SessionDependency) -> list[BackupArchiveRead]:
    return service.list_backups(session)


@router.post(
    "/backups", response_model=BackupCreateRead, status_code=status.HTTP_202_ACCEPTED
)
def post_backup(session: SessionDependency) -> BackupCreateRead:
    return service.start_backup(session, BackupKind.MANUAL)


@router.get("/backups/{backup_id}", response_model=BackupArchiveRead)
def get_backup(backup_id: UUID, session: SessionDependency) -> BackupArchiveRead:
    return BackupArchiveRead.model_validate(service.backup_or_404(session, backup_id))


@router.get("/backups/{backup_id}/file", response_class=FileResponse)
def download_backup(backup_id: UUID, session: SessionDependency) -> FileResponse:
    path = service.backup_file(session, backup_id)
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.delete("/backups/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(backup_id: UUID, session: SessionDependency) -> Response:
    service.delete_backup(session, backup_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/backups/{backup_id}/restore",
    response_model=RestoreStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def restore_managed_backup(backup_id: UUID, session: SessionDependency) -> RestoreStartRead:
    return restore.start_managed_backup_restore(session, backup_id)


@router.post("/storage/transfers", response_model=TransferUploadRead)
async def upload_transfer(
    session: SessionDependency, file: Annotated[UploadFile, File()]
) -> TransferUploadRead:
    return await uploads.upload_transfer(session, file)


@router.post(
    "/storage/transfers/{artifact_id}/restore",
    response_model=RestoreStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def restore_backup(artifact_id: UUID, session: SessionDependency) -> RestoreStartRead:
    return restore.start_restore(session, artifact_id)


@router.get("/storage/restores/{operation_id}", response_model=RestoreStatusRead)
def get_restore_status(operation_id: UUID) -> RestoreStatusRead:
    return restore.status(operation_id)


@router.post(
    "/projects/{project_id}/exports",
    response_model=ProjectExportRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_project(
    project_id: UUID, command: ProjectExportCommand, session: SessionDependency
) -> ProjectExportRead:
    artifact = project_transfer.start_project_export(session, project_id, command.profile)
    assert artifact.job_id is not None
    return ProjectExportRead(artifact_id=artifact.id, job_id=artifact.job_id)


@router.get("/storage/transfers/{artifact_id}/file", response_class=FileResponse)
def download_transfer(artifact_id: UUID, session: SessionDependency) -> FileResponse:
    artifact = project_transfer.artifact_or_404(session, artifact_id)
    path = project_transfer.artifact_file(session, artifact_id)
    return FileResponse(path, filename=artifact.file_name, media_type="application/zip")


@router.post(
    "/storage/transfers/{artifact_id}/import-project",
    response_model=ProjectImportRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def import_project(
    artifact_id: UUID, command: ProjectImportCommand, session: SessionDependency
) -> ProjectImportRead:
    artifact = project_transfer.start_project_import(
        session, artifact_id, allow_duplicate=command.allow_duplicate
    )
    assert artifact.job_id is not None
    return ProjectImportRead(artifact_id=artifact.id, job_id=artifact.job_id)


@router.post(
    "/storage/verify",
    response_model=BackgroundJobStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def verify_storage(session: SessionDependency) -> BackgroundJobStartRead:
    """Полная проверка SQLite синхронно занимает минуты на медленном диске —
    результат приходит через `GET /api/background-jobs/{id}/result`."""
    return BackgroundJobStartRead(job_id=service.start_storage_verify(session))


@router.post(
    "/storage/cleanup",
    response_model=BackgroundJobStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def cleanup_storage(session: SessionDependency) -> BackgroundJobStartRead:
    return BackgroundJobStartRead(job_id=service.start_storage_cleanup(session))
