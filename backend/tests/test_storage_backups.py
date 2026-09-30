"""Переносимые копии установки и пакеты одного проекта."""

import json
import sqlite3
import zipfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, get_session
from app.main import create_app
from app.models import (
    AiProviderConnection,
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
from app.storage import archive, maintenance, project_transfer, service


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


def test_snapshot_does_not_restart_when_heartbeat_writes(storage_session: Session) -> None:
    """Каждый шаг меняет источник другим соединением: снимок всё равно конечен."""
    project, _ = _seed_project(storage_session)
    writer = sqlite3.connect(settings.database_path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE padding (data BLOB)")
    writer.execute("INSERT INTO padding VALUES (zeroblob(4194304))")
    writer.commit()
    steps = []

    def heartbeat(done: int, total: int) -> None:
        steps.append(done)
        assert len(steps) <= total // archive.SNAPSHOT_PAGES + 1
        writer.execute("UPDATE projects SET name = 'heartbeat'")
        writer.commit()

    destination = settings.data_dir / "snapshot.sqlite"
    try:
        archive.snapshot_database(settings.database_path, destination, progress=heartbeat)
    finally:
        writer.close()
    assert len(steps) > 1
    assert steps == sorted(set(steps))
    with sqlite3.connect(destination) as snapshot:
        assert snapshot.execute("SELECT name FROM projects").fetchone()[0] == project.name
        assert snapshot.execute("PRAGMA quick_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("state", [BackgroundJobState.QUEUED, BackgroundJobState.RUNNING])
def test_backup_cancellation_and_lock_release(
    storage_session: Session, monkeypatch: pytest.MonkeyPatch, state: BackgroundJobState,
) -> None:
    """Отмена допускается middleware во время backup и снимает lock воркером."""
    def factory():
        return Session(storage_session.bind, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", factory)
    started = service.start_backup(storage_session)
    job = storage_session.get(BackgroundJob, started.job_id)
    job.state = state
    storage_session.commit()
    if state == BackgroundJobState.RUNNING:
        maintenance.begin("backup", started.backup_id)
    app = create_app()
    def session_dependency():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    client = TestClient(app)
    if state == BackgroundJobState.RUNNING:
        unrelated = BackgroundJob(
            id=uuid4(), kind=BackgroundJobKind.STORAGE_VERIFY,
            state=BackgroundJobState.QUEUED, checkpoint={},
        )
        storage_session.add(unrelated)
        storage_session.commit()
        assert client.post(f"/api/background-jobs/{unrelated.id}/cancel").status_code == 409
        assert client.post("/api/backups").status_code == 503
    response = client.post(f"/api/background-jobs/{job.id}/cancel")
    assert response.status_code == 200
    storage_session.expire_all()
    job = storage_session.get(BackgroundJob, started.job_id)
    if state == BackgroundJobState.RUNNING:
        assert response.json()["control_action"] == "cancel"
        maintenance.finish(started.backup_id)
        service.process_backup_job(storage_session, job)
    storage_session.expire_all()
    assert storage_session.get(BackgroundJob, started.job_id).state == BackgroundJobState.CANCELLED
    assert storage_session.get(BackupArchive, started.backup_id).state == BackupArchiveState.FAILED
    assert not maintenance.active()


def test_archive_cancel_during_snapshot_does_not_publish(storage_session: Session) -> None:
    """Исключение из SQLite-callback не публикует частичную копию."""
    destination = settings.default_backup_dir / "cancelled.tentex-backup"

    def cancel(done: int, total: int) -> None:
        raise archive.BackupCancelled()

    with pytest.raises(archive.BackupCancelled):
        archive.create_backup(
            destination, backup_id=uuid4(), kind=BackupKind.MANUAL, snapshot_progress=cancel,
        )
    assert not destination.exists()
    assert not destination.with_suffix(".tentex-backup.partial").exists()


def test_cancel_during_publication_removes_partial_archive(storage_session: Session) -> None:
    """Отмена после упаковки не оставляет файл, который выглядит готовой копией."""
    destination = settings.default_backup_dir / "cancelled.tentex-backup"
    partial = destination.with_suffix(".tentex-backup.partial")

    def check_cancel() -> None:
        if partial.exists():
            raise archive.BackupCancelled()

    with pytest.raises(archive.BackupCancelled):
        archive.create_backup(
            destination, backup_id=uuid4(), kind=BackupKind.MANUAL, check_cancel=check_cancel,
        )
    assert not destination.exists()
    assert not partial.exists()


def test_dead_backup_lock_recovers_without_touching_live_lease(
    storage_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Восстановление снимает только lock с истёкшей арендой задачи."""
    monkeypatch.setattr(service, "SessionLocal", lambda: Session(storage_session.bind))
    started = service.start_backup(storage_session)
    job = storage_session.get(BackgroundJob, started.job_id)
    job.state = BackgroundJobState.RUNNING
    job.lease_expires_at = utc_now() + timedelta(minutes=1)
    storage_session.commit()
    maintenance.begin("backup", started.backup_id)
    service.recover_interrupted_backup()
    assert maintenance.active()
    job.lease_expires_at = utc_now() - timedelta(minutes=1)
    storage_session.commit()
    service.recover_interrupted_backup()
    assert not maintenance.active()
    storage_session.expire_all()
    assert storage_session.get(BackgroundJob, job.id).state == BackgroundJobState.FAILED


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
