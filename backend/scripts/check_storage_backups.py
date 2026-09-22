"""Сквозная smoke-проверка переносимой копии и пакета проекта.

Скрипт не использует рабочую `data/`: создаёт минимальную установку во временном
каталоге, снимает `.tentex-backup`, меняет запись, читает согласованный снимок и
затем импортирует `.tentex-project` рядом с исходным проектом.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import (
    BackupKind,
    Material,
    MaterialSourceKind,
    MaterialState,
    Project,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    TemplateKey,
    TransferArtifact,
    TransferKind,
    TransferProfile,
    WorkspaceVariant,
    utc_now,
)
from app.storage import archive, project_transfer


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tentex-storage-check-") as raw_root:
        root = Path(raw_root)
        settings.data_dir = root
        settings.storage_dir.mkdir(parents=True)
        engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as session:
            project = Project(
                id=uuid4(),
                template_key=TemplateKey.TEXTBOOK,
                workspace_variant=WorkspaceVariant.TEXTBOOK,
                status=ProjectStatus.ACTIVE,
                name="Smoke project",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            material = Material(
                id=uuid4(),
                sha256="b" * 64,
                original_name="source.txt",
                display_name="Source",
                storage_path="materials/smoke/source.txt",
                media_type="text/plain",
                source_kind=MaterialSourceKind.TEXT,
                size_bytes=12,
                status=MaterialState.READY,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add_all([project, material])
            session.flush()
            session.add(
                ProjectMaterial(
                    project_id=project.id,
                    material_id=material.id,
                    source_role=SourceRole.ADDITIONAL,
                    priority=0,
                    affects_program=False,
                    purposes=["study_source"],
                    created_at=utc_now(),
                )
            )
            session.commit()
            source = settings.storage_dir / material.storage_path
            source.parent.mkdir(parents=True)
            source.write_text("stable source", encoding="utf-8")
            source_hash = archive.sha256_file(source)

            backup_path = settings.default_backup_dir / "smoke.tentex-backup"
            manifest = archive.create_backup(
                backup_path, backup_id=uuid4(), kind=BackupKind.MANUAL
            )
            archive.validate_backup(backup_path)
            project.name = "Changed after backup"
            session.commit()

            with zipfile.ZipFile(backup_path) as package:
                snapshot = package.read("database/tentex.sqlite")
                (root / "snapshot.sqlite").write_bytes(snapshot)
            snapshot_connection = sqlite3.connect(str(root / "snapshot.sqlite"))
            try:
                assert (
                    snapshot_connection.execute("SELECT name FROM projects").fetchone()[0]
                    == "Smoke project"
                )
            finally:
                snapshot_connection.close()
            assert manifest["counts"]["projects"] == 1
            assert archive.sha256_file(source) == source_hash

            package_path = settings.transfer_dir / "smoke.tentex-project"
            package_manifest = project_transfer.create_project_package(
                package_path,
                package_id=uuid4(),
                project_id=project.id,
                profile=TransferProfile.SHARE,
            )
            artifact = TransferArtifact(
                id=uuid4(),
                kind=TransferKind.PROJECT,
                profile=TransferProfile.SHARE,
                package_id=uuid4(),
                file_path=str(package_path),
                file_name=package_path.name,
                size_bytes=package_path.stat().st_size,
                sha256=archive.sha256_file(package_path),
                manifest=package_manifest,
                expires_at=utc_now(),
            )
            session.add(artifact)
            session.commit()
            imported_id, _ = project_transfer.import_project_package(session, artifact)
            assert imported_id != project.id
            assert session.scalar(select(Project).where(Project.id == imported_id)) is not None
        engine.dispose()
    print("storage/backups smoke: OK (full snapshot + project package round-trip)")


if __name__ == "__main__":
    main()
