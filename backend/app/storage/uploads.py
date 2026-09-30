"""Потоковый приём переносимых архивов и безопасный предпросмотр."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import TransferArtifact, TransferKind, TransferProfile, utc_now
from app.projects.errors import ProjectDomainError
from app.storage import archive, project_transfer
from app.storage.schemas import TransferUploadRead

CHUNK_SIZE = 1024 * 1024


async def _store(upload: UploadFile) -> tuple[Path, int, str]:
    settings.transfer_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".tentex-backup", ".tentex-project"}:
        raise ProjectDomainError(
            "Выберите файл .tentex-backup или .tentex-project",
            status=422,
            code="transfer_extension_invalid",
        )
    path = settings.transfer_dir / f"upload-{uuid4().hex}{suffix}"
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("xb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > settings.transfer_upload_max_bytes:
                    raise ProjectDomainError(
                        "Архив превышает допустимый размер загрузки",
                        status=413,
                        code="transfer_too_large",
                    )
                output.write(chunk)
                digest.update(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path, size, digest.hexdigest()


async def upload_transfer(session: Session, upload: UploadFile) -> TransferUploadRead:
    """Проверить весь файл до появления записи, пригодной для подтверждения."""
    path, size, digest = await _store(upload)
    try:
        suffix = path.suffix.lower()
        if suffix == ".tentex-backup":
            manifest = archive.validate_backup(path)
            kind = TransferKind.BACKUP
            profile = None
            manifest["unpacked_size"] = sum(
                int(item.get("size", 0)) for item in manifest.get("entries", [])
            )
        else:
            manifest = project_transfer.validate_project_package(path)
            kind = TransferKind.PROJECT
            profile = TransferProfile(str(manifest["profile"]))
        package_id = uuid4()
        if raw_package_id := manifest.get("package_id") or manifest.get("backup_id"):
            from uuid import UUID

            package_id = UUID(str(raw_package_id))
        repeated = session.scalar(
            select(TransferArtifact.id).where(TransferArtifact.package_id == package_id).limit(1)
        ) is not None
        artifact = TransferArtifact(
            id=uuid4(),
            kind=kind,
            profile=profile,
            package_id=package_id,
            file_path=str(path),
            file_name=Path(upload.filename or path.name).name,
            size_bytes=size,
            sha256=digest,
            manifest=manifest,
            expires_at=utc_now() + timedelta(hours=24),
        )
        session.rollback()
        with session.begin():
            session.add(artifact)
        return TransferUploadRead(
            id=artifact.id,
            kind=artifact.kind.value,
            file_name=artifact.file_name,
            size_bytes=artifact.size_bytes,
            manifest=artifact.manifest,
            repeated=repeated,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
