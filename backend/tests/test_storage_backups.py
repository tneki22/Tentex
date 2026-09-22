"""Переносимые копии установки и пакеты одного проекта."""

import json
import sqlite3
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import (
    AiProviderConnection,
    BackupKind,
    EmbeddingBackendKind,
    EmbeddingProfile,
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
from app.projects.errors import ProjectDomainError
from app.storage import archive, project_transfer


@pytest.fixture
def storage_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.storage_dir.mkdir(parents=True)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _seed_project(session: Session) -> tuple[Project, Material]:
    project = Project(
        id=uuid4(),
        template_key=TemplateKey.TEXTBOOK,
        workspace_variant=WorkspaceVariant.TEXTBOOK,
        status=ProjectStatus.ACTIVE,
        name="Передаваемый проект",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    material = Material(
        id=uuid4(),
        sha256="a" * 64,
        original_name="source.txt",
        display_name="Источник",
        storage_path="materials/aa/source.txt",
        media_type="text/plain",
        source_kind=MaterialSourceKind.TEXT,
        size_bytes=8,
        status=MaterialState.READY_TO_PROCESS,
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
    source.write_text("учебник", encoding="utf-8")
    return project, material


def test_backup_uses_sqlite_snapshot_and_excludes_secrets_and_models(
    storage_session: Session,
) -> None:
    project, _ = _seed_project(storage_session)
    provider = AiProviderConnection(
        id=uuid4(),
        label="Provider",
        catalog_profile="openai_compatible",
        base_url="https://example.test/v1",
        api_key_ciphertext=b"secret",
    )
    profile = EmbeddingProfile(
        id=uuid4(),
        label="Local",
        backend_kind=EmbeddingBackendKind.LOCAL_HF,
        model_id="test/model",
        installed=True,
    )
    storage_session.add_all([provider, profile])
    storage_session.commit()
    (settings.storage_dir / "tmp").mkdir()
    (settings.storage_dir / "tmp" / "ignored.bin").write_bytes(b"ignored")
    settings.embedding_models_dir.joinpath("weights.bin").write_bytes(b"weights")

    destination = settings.default_backup_dir / "copy.tentex-backup"
    manifest = archive.create_backup(
        destination, backup_id=uuid4(), kind=BackupKind.MANUAL
    )

    assert manifest["counts"]["projects"] == 1
    assert archive.validate_backup(destination)["format"] == "tentex-backup"
    with zipfile.ZipFile(destination) as package:
        assert "storage/materials/aa/source.txt" in package.namelist()
        assert "storage/tmp/ignored.bin" not in package.namelist()
        assert not any(name.startswith("models/") for name in package.namelist())
        extracted = settings.data_dir / "snapshot.sqlite"
        extracted.write_bytes(package.read("database/tentex.sqlite"))
    connection = sqlite3.connect(str(extracted))
    try:
        assert connection.execute(
            "SELECT api_key_ciphertext FROM ai_provider_connections"
        ).fetchone()[0] is None
        assert connection.execute("SELECT installed FROM embedding_profiles").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM projects").fetchone()[0] == project.name
    finally:
        connection.close()


def test_backup_rejects_path_traversal(storage_session: Session) -> None:
    malicious = settings.data_dir / "bad.tentex-backup"
    with zipfile.ZipFile(malicious, "w") as package:
        package.writestr("../escape", b"bad")
        package.writestr(
            "manifest.json",
            json.dumps({"format": "tentex-backup", "format_version": 1, "entries": []}),
        )
    with pytest.raises(ProjectDomainError) as caught:
        archive.validate_backup(malicious)
    assert caught.value.code == "backup_corrupt"


def test_project_package_imports_next_to_existing_and_reuses_material(
    storage_session: Session,
) -> None:
    project, material = _seed_project(storage_session)
    package_id = uuid4()
    package = settings.transfer_dir / "project.tentex-project"
    manifest = project_transfer.create_project_package(
        package,
        package_id=package_id,
        project_id=project.id,
        profile=TransferProfile.SHARE,
    )
    artifact = TransferArtifact(
        id=uuid4(),
        kind=TransferKind.PROJECT,
        profile=TransferProfile.SHARE,
        package_id=package_id,
        file_path=str(package),
        file_name=package.name,
        size_bytes=package.stat().st_size,
        sha256=archive.sha256_file(package),
        manifest=manifest,
        expires_at=utc_now(),
    )
    storage_session.add(artifact)
    storage_session.commit()

    imported_id, warnings = project_transfer.import_project_package(storage_session, artifact)

    assert imported_id != project.id
    assert storage_session.get(Project, imported_id).name.endswith("— импорт")
    assert storage_session.scalar(select(func.count()).select_from(Project)) == 2
    assert storage_session.scalar(select(func.count()).select_from(Material)) == 1
    assert storage_session.scalar(
        select(func.count()).select_from(ProjectMaterial).where(
            ProjectMaterial.project_id == imported_id,
            ProjectMaterial.material_id == material.id,
        )
    ) == 1
    assert warnings
