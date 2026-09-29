"""Версионированный `.tentex-project` без глобальных настроек и dense-индекса."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from sqlalchemy import JSON, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, job_write_transaction
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    Project,
    TransferArtifact,
    TransferKind,
    TransferProfile,
    utc_now,
)
from app.projects.errors import ProjectDomainError, ProjectNotFoundError
from app.retrieval.indexing import queue_incremental_reindex
from app.storage.archive import APP_VERSION, BUFFER_SIZE, sha256_file

FORMAT = "tentex-project"
FORMAT_VERSION = 1
ARTIFACT_TTL = timedelta(hours=24)

# Только предметные таблицы. Глобальные провайдеры, настройки, usage, retrieval
# и реестр управляемых копий не могут попасть в пакет по ошибке.
CORE_TABLES = {
    "projects",
    "goal_passports",
    "materials",
    "project_materials",
    "material_revisions",
    "material_pages",
    "material_blocks",
    "material_fragments",
    "typst_materials",
    "typst_source_chunks",
    "program_nodes",
    "program_node_source_page_ranges",
    "reference_answers",
    "reference_answer_attachments",
    "background_jobs",
    "bindings",
    "coverage_runs",
    "coverage_tasks",
    "coverage_block_results",
    "coverage_findings",
    "coverage_decisions",
    "project_action_log",
    "activities",
    "cards",
    "conspects",
    "conspect_images",
    "lessons",
    "lesson_topics",
    "lesson_blocks",
    "lesson_source_refs",
}
PERSONAL_TABLES = {
    "wizard_drafts",
    "workspace_states",
    "card_sessions",
    "attempts",
    "oral_recordings",
    "grades",
    "chat_sessions",
    "chat_messages",
    "chat_tool_runs",
    "preparation_settings",
    "preparation_plans",
    "preparation_versions",
    "preparation_queues",
    "preparation_reviews",
    "preparation_qualities",
    "preparation_coach",
    "preparation_drafts",
    "study_activities",
    "study_intervals",
}
MATERIAL_TABLES = {
    "materials",
    "material_revisions",
    "material_pages",
    "material_blocks",
    "material_fragments",
    "typst_materials",
    "typst_source_chunks",
}


def _tables(profile: TransferProfile) -> list[str]:
    selected = CORE_TABLES | (PERSONAL_TABLES if profile == TransferProfile.PERSONAL else set())
    return [table.name for table in Base.metadata.sorted_tables if table.name in selected]


def _clone_database(destination: Path) -> None:
    source = sqlite3.connect(str(settings.database_path), timeout=30)
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target, pages=2048)
    finally:
        target.close()
        source.close()


def _prune(connection: sqlite3.Connection, project_id: UUID, profile: TransferProfile) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    value = project_id.hex
    if connection.execute("SELECT 1 FROM projects WHERE id = ?", (value,)).fetchone() is None:
        raise ProjectNotFoundError("Проект не найден", code="project_not_found")
    connection.execute("DELETE FROM projects WHERE id <> ?", (value,))
    connection.execute(
        "DELETE FROM materials WHERE id NOT IN (SELECT material_id FROM project_materials)"
    )
    connection.execute("DELETE FROM background_jobs WHERE project_id IS NULL")
    if profile == TransferProfile.SHARE:
        # Для профиля «Поделиться» фоновые журналы не являются учебными данными.
        # Единственное исключение — задания прохода 2, на которые ссылаются
        # переносимые результаты покрытия.
        connection.execute(
            "DELETE FROM background_jobs WHERE kind <> 'coverage_research'"
        )
        for table in (
            "grades",
            "attempts",
            "card_sessions",
            "chat_tool_runs",
            "chat_messages",
            "chat_sessions",
            "workspace_states",
            "wizard_drafts",
            "study_intervals",
            "study_activities",
            "preparation_reviews",
            "preparation_qualities",
            "preparation_queues",
            "preparation_versions",
            "preparation_plans",
            "preparation_settings",
            "preparation_coach",
            "preparation_drafts",
        ):
            connection.execute(f'DELETE FROM "{table}"')
        connection.execute("UPDATE cards SET state = 'active', deleted_at = NULL")
    connection.commit()


def _encode(value: object, *, json_column: bool) -> object:
    if value is None:
        return None
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if json_column and isinstance(value, str):
        try:
            return {"$json": json.loads(value)}
        except json.JSONDecodeError:
            return {"$json": value}
    return value


def _write_records(
    archive: zipfile.ZipFile, connection: sqlite3.Connection, table_name: str
) -> tuple[int, list[dict[str, object]]]:
    table = Base.metadata.tables[table_name]
    json_columns = {column.name for column in table.columns if isinstance(column.type, JSON)}
    rows = connection.execute(f'SELECT * FROM "{table_name}"')
    names = [item[0] for item in rows.description]
    count = 0
    lines: list[str] = []
    path_values: list[dict[str, object]] = []
    for raw in rows:
        record = {
            name: _encode(value, json_column=name in json_columns)
            for name, value in zip(names, raw, strict=True)
        }
        lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        count += 1
        for name, value in record.items():
            if isinstance(value, str) and (name.endswith("_path") or name == "storage_path"):
                path_values.append({"table": table_name, "column": name, "path": value})
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    archive.writestr(f"records/{table_name}.jsonl", payload)
    return count, path_values


def _collect_blobs(references: list[dict[str, object]]) -> dict[str, Path]:
    blobs: dict[str, Path] = {}
    root = settings.storage_dir.resolve()
    for reference in references:
        raw = str(reference["path"])
        candidate = (root / raw).resolve()
        if root not in candidate.parents or not candidate.is_file():
            continue
        blobs[PurePosixPath(*Path(raw).parts).as_posix()] = candidate
    return blobs


def create_project_package(
    destination: Path,
    *,
    package_id: UUID,
    project_id: UUID,
    profile: TransferProfile,
) -> dict[str, object]:
    """Зафиксировать один проект и только достижимые им файловые объекты."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tentex-project-", dir=destination.parent) as raw_tmp:
        temp_dir = Path(raw_tmp)
        clone = temp_dir / "source.sqlite"
        _clone_database(clone)
        connection = sqlite3.connect(str(clone))
        connection.row_factory = sqlite3.Row
        try:
            _prune(connection, project_id, profile)
            project = connection.execute(
                "SELECT name, template_key, workspace_variant FROM projects WHERE id = ?",
                (project_id.hex,),
            ).fetchone()
            assert project is not None
            temp_archive = temp_dir / destination.name
            counts: dict[str, int] = {}
            references: list[dict[str, object]] = []
            with zipfile.ZipFile(
                temp_archive,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as output:
                for table in _tables(profile):
                    count, table_references = _write_records(output, connection, table)
                    counts[table] = count
                    references.extend(table_references)
                blob_entries: list[dict[str, object]] = []
                for relative, source in _collect_blobs(references).items():
                    member = f"blobs/{relative}"
                    output.write(source, member)
                    blob_entries.append(
                        {
                            "path": relative,
                            "member": member,
                            "size": source.stat().st_size,
                            "sha256": sha256_file(source),
                        }
                    )
                manifest: dict[str, object] = {
                    "format": FORMAT,
                    "format_version": FORMAT_VERSION,
                    "app_version": APP_VERSION,
                    "package_id": str(package_id),
                    "project_id": str(project_id),
                    "project_name": project["name"],
                    "template_key": project["template_key"],
                    "workspace_variant": project["workspace_variant"],
                    "profile": profile.value,
                    "counts": counts,
                    "blobs": blob_entries,
                    "dense_index_included": False,
                    "personal_history_included": profile == TransferProfile.PERSONAL,
                }
                output.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
            shutil.move(temp_archive, destination)
            return manifest
        finally:
            connection.close()


def validate_project_package(path: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
                raise ProjectDomainError(
                    "Эта версия Tentex не поддерживает пакет проекта",
                    status=422,
                    code="project_package_incompatible",
                )
            total = sum(info.file_size for info in archive.infolist())
            if total > settings.transfer_unpacked_max_bytes:
                raise ProjectDomainError(
                    "Распакованный пакет проекта слишком велик",
                    status=413,
                    code="project_package_too_large",
                )
            names = set(archive.namelist())
            if any(
                PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                for name in names
            ):
                raise ValueError("unsafe path")
            for blob in manifest.get("blobs", []):
                member = blob["member"]
                if member not in names:
                    raise ValueError("blob missing")
                digest = hashlib.sha256(archive.read(member)).hexdigest()
                if digest != blob["sha256"]:
                    raise ValueError("blob checksum mismatch")
            return manifest
    except ProjectDomainError:
        raise
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise ProjectDomainError(
            "Пакет проекта повреждён или имеет неизвестный формат",
            status=422,
            code="project_package_corrupt",
        ) from error


def start_project_export(
    session: Session, project_id: UUID, profile: TransferProfile
) -> TransferArtifact:
    if session.get(Project, project_id) is None:
        raise ProjectNotFoundError("Проект не найден", code="project_not_found")
    session.rollback()
    artifact_id = uuid4()
    package_id = uuid4()
    job_id = uuid4()
    destination = settings.transfer_dir / f"{package_id}.tentex-project"
    with session.begin():
        artifact = TransferArtifact(
            id=artifact_id,
            kind=TransferKind.PROJECT,
            profile=profile,
            project_id=project_id,
            package_id=package_id,
            file_path=str(destination),
            file_name=f"project-{str(project_id)[:8]}.tentex-project",
            job_id=job_id,
            expires_at=utc_now() + ARTIFACT_TTL,
        )
        job = BackgroundJob(
            id=job_id,
            project_id=project_id,
            kind=BackgroundJobKind.PROJECT_EXPORT,
            state=BackgroundJobState.QUEUED,
            checkpoint={"artifact_id": str(artifact_id)},
            diagnostics=[],
        )
        session.add_all([artifact, job])
    return artifact


def process_project_export(session: Session, detached_job: BackgroundJob) -> None:
    job_id = detached_job.id
    artifact_id = UUID(str(detached_job.checkpoint["artifact_id"]))
    try:
        artifact = session.get(TransferArtifact, artifact_id)
        if artifact is None or artifact.project_id is None or artifact.profile is None:
            raise ProjectNotFoundError("Экспорт проекта не найден", code="project_export_not_found")
        manifest = create_project_package(
            Path(artifact.file_path),
            package_id=artifact.package_id,
            project_id=artifact.project_id,
            profile=artifact.profile,
        )
        with job_write_transaction(session, job_id):
            artifact = session.get(TransferArtifact, artifact_id)
            job = session.get(BackgroundJob, job_id)
            assert artifact is not None and job is not None
            artifact.manifest = manifest
            artifact.size_bytes = Path(artifact.file_path).stat().st_size
            artifact.sha256 = sha256_file(Path(artifact.file_path))
            job.state = BackgroundJobState.COMPLETED
            job.done = 1
            job.total = 1
            job.completed_at = utc_now()
            job.lease_owner = None
            job.lease_expires_at = None
    except Exception as error:
        session.rollback()
        with job_write_transaction(session, job_id):
            job = session.get(BackgroundJob, job_id)
            if job is not None:
                job.state = BackgroundJobState.FAILED
                job.error = str(error)
                job.lease_owner = None
                job.lease_expires_at = None
        raise


def artifact_or_404(session: Session, artifact_id: UUID) -> TransferArtifact:
    row = session.get(TransferArtifact, artifact_id)
    if row is None:
        raise ProjectNotFoundError("Пакет переноса не найден", code="transfer_not_found")
    return row


def artifact_file(session: Session, artifact_id: UUID) -> Path:
    row = artifact_or_404(session, artifact_id)
    path = Path(row.file_path)
    if not row.sha256 or not path.is_file():
        raise ProjectDomainError("Экспорт ещё не готов", status=409, code="transfer_not_ready")
    return path


def _decode(value: object) -> object:
    if isinstance(value, dict) and set(value) == {"$bytes"}:
        return base64.b64decode(str(value["$bytes"]))
    if isinstance(value, dict) and set(value) == {"$json"}:
        return value["$json"]
    return value


def _records(archive: zipfile.ZipFile, table_name: str) -> list[dict[str, object]]:
    try:
        payload = archive.read(f"records/{table_name}.jsonl").decode("utf-8")
    except KeyError:
        return []
    return [
        {name: _decode(value) for name, value in json.loads(line).items()}
        for line in payload.splitlines()
        if line
    ]


def _uuid_value(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _identity(value: object) -> str:
    parsed = _uuid_value(value)
    return parsed.hex if parsed is not None else str(value)


def _material_map(
    session: Session, records: list[dict[str, object]]
) -> tuple[dict[str, str], set[str], list[str]]:
    mapping: dict[str, str] = {}
    reused: set[str] = set()
    warnings: list[str] = []
    for record in records:
        old_id = _identity(record["id"])
        existing = session.scalar(select(Material).where(Material.sha256 == record["sha256"]))
        if existing is None:
            mapping[old_id] = uuid4().hex
            continue
        mapping[old_id] = existing.id.hex
        reused.add(old_id)
        warnings.append(f"Материал «{record.get('display_name')}» переиспользован по SHA-256")
    return mapping, reused, warnings


def _prepare_mappings(
    session: Session,
    tables: list[str],
    records_by_table: dict[str, list[dict[str, object]]],
) -> tuple[dict[tuple[str, str], str], set[str], list[str]]:
    material_ids, reused, warnings = _material_map(session, records_by_table.get("materials", []))
    mappings: dict[tuple[str, str], str] = {
        ("materials", old): new for old, new in material_ids.items()
    }
    for table_name in tables:
        table = Base.metadata.tables[table_name]
        for column in table.primary_key.columns:
            if column.name == "sequence" or column.name not in table.columns:
                continue
            try:
                is_uuid = column.type.python_type is UUID
            except NotImplementedError:
                is_uuid = False
            if not is_uuid:
                continue
            for record in records_by_table[table_name]:
                old = record.get(column.name)
                if old is not None and (table_name, _identity(old)) not in mappings:
                    mappings[(table_name, _identity(old))] = uuid4().hex
    return mappings, reused, warnings


def _map_record(
    table_name: str,
    record: dict[str, object],
    selected_tables: set[str],
    mappings: dict[tuple[str, str], str],
) -> dict[str, object]:
    table = Base.metadata.tables[table_name]
    result = dict(record)
    for column in table.columns:
        value = result.get(column.name)
        own = mappings.get((table_name, _identity(value))) if value is not None else None
        if own is not None and column.primary_key:
            result[column.name] = own
        for foreign_key in column.foreign_keys:
            target_table = foreign_key.column.table.name
            if target_table not in selected_tables:
                if column.nullable:
                    result[column.name] = None
                continue
            mapped = mappings.get((target_table, _identity(value))) if value is not None else None
            if mapped is not None:
                result[column.name] = mapped
            elif value is not None and foreign_key.column.primary_key and column.nullable:
                result[column.name] = None
    return result


def _driver_values(table_name: str, record: dict[str, object]) -> dict[str, object]:
    """SQLite clone отдаёт даты строками; raw driver сохраняет их без type coercion."""
    table = Base.metadata.tables[table_name]
    return {
        name: (
            json.dumps(value, ensure_ascii=False)
            if isinstance(table.columns[name].type, JSON)
            else value
        )
        for name, value in record.items()
    }


def _restore_blobs(
    archive: zipfile.ZipFile, manifest: dict[str, object], reused_paths: set[str]
) -> None:
    root = settings.storage_dir.resolve()
    for blob in manifest.get("blobs", []):
        assert isinstance(blob, dict)
        relative = str(blob["path"])
        if relative in reused_paths:
            continue
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ProjectDomainError(
                "Пакет содержит небезопасный путь файла",
                status=422,
                code="project_package_corrupt",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha256_file(target) == blob["sha256"]:
            continue
        temporary = target.with_suffix(target.suffix + ".importing")
        with archive.open(str(blob["member"])) as source, temporary.open("wb") as output:
            shutil.copyfileobj(source, output, BUFFER_SIZE)
        temporary.replace(target)


def import_project_package(
    session: Session, artifact: TransferArtifact
) -> tuple[UUID, list[str]]:
    """Импортировать пакет одной транзакцией, переназначив все UUID и FK."""
    manifest = validate_project_package(Path(artifact.file_path))
    profile = TransferProfile(str(manifest["profile"]))
    tables = _tables(profile)
    selected = set(tables)
    with zipfile.ZipFile(artifact.file_path) as archive:
        records_by_table = {table: _records(archive, table) for table in tables}
        mappings, reused_materials, warnings = _prepare_mappings(
            session, tables, records_by_table
        )
        source_project = _identity(manifest["project_id"])
        project_id = UUID(mappings[("projects", source_project)])
        reused_paths = {
            str(record["storage_path"])
            for record in records_by_table.get("materials", [])
            if str(record["id"]) in reused_materials
        }
        session.rollback()
        with session.begin():
            for table_name in tables:
                table = Base.metadata.tables[table_name]
                for record in records_by_table[table_name]:
                    if table_name in MATERIAL_TABLES:
                        material_key = str(
                            record.get("material_id")
                            or (record.get("id") if table_name == "materials" else "")
                        ).replace("-", "")
                        if material_key in reused_materials:
                            continue
                    values = _map_record(table_name, record, selected, mappings)
                    # Автонумеруемый журнал получает новый sequence; ссылки на
                    # него безопасно обнуляются, если пакет их содержал.
                    if table_name == "project_action_log":
                        values.pop("sequence", None)
                    driver_values = _driver_values(table_name, values)
                    columns = ", ".join(f'"{name}"' for name in driver_values)
                    placeholders = ", ".join(f":{name}" for name in driver_values)
                    session.connection().exec_driver_sql(
                        f'INSERT INTO "{table.name}" ({columns}) VALUES ({placeholders})',
                        driver_values,
                    )
            imported = session.get(Project, project_id)
            assert imported is not None
            imported.name = f"{imported.name or 'Проект'} — импорт"
            artifact.imported_project_id = project_id
        _restore_blobs(archive, manifest, reused_paths)
    new_material_ids = [
        UUID(new_id)
        for (table_name, old_id), new_id in mappings.items()
        if table_name == "materials" and old_id not in reused_materials
    ]
    # Инкрементальная очередь поддерживает только совместимый активный локальный
    # профиль. Во всех остальных случаях FTS5 уже готов и остаётся честный BM25.
    with session.begin():
        for material_id in new_material_ids:
            queue_incremental_reindex(session, material_id)
    return project_id, warnings


def start_project_import(
    session: Session, artifact_id: UUID, *, allow_duplicate: bool
) -> TransferArtifact:
    artifact = artifact_or_404(session, artifact_id)
    if artifact.kind != TransferKind.PROJECT:
        raise ProjectDomainError("Это не пакет проекта", status=422, code="transfer_kind_invalid")
    if artifact.imported_project_id is not None and not allow_duplicate:
        raise ProjectDomainError(
            "Этот пакет уже импортирован; подтвердите создание ещё одной копии",
            status=409,
            code="project_package_already_imported",
        )
    job_id = uuid4()
    session.rollback()
    with session.begin():
        artifact = artifact_or_404(session, artifact_id)
        artifact.job_id = job_id
        session.add(
            BackgroundJob(
                id=job_id,
                kind=BackgroundJobKind.PROJECT_IMPORT,
                state=BackgroundJobState.QUEUED,
                checkpoint={"artifact_id": str(artifact_id)},
                diagnostics=[],
            )
        )
    return artifact


def process_project_import(session: Session, detached_job: BackgroundJob) -> None:
    job_id = detached_job.id
    artifact_id = UUID(str(detached_job.checkpoint["artifact_id"]))
    try:
        artifact = artifact_or_404(session, artifact_id)
        project_id, warnings = import_project_package(session, artifact)
        with job_write_transaction(session, job_id):
            job = session.get(BackgroundJob, job_id)
            artifact = session.get(TransferArtifact, artifact_id)
            assert job is not None and artifact is not None
            artifact.imported_project_id = project_id
            job.state = BackgroundJobState.COMPLETED
            job.done = 1
            job.total = 1
            job.checkpoint = {**job.checkpoint, "project_id": str(project_id), "warnings": warnings}
            job.completed_at = utc_now()
            job.lease_owner = None
            job.lease_expires_at = None
    except Exception as error:
        session.rollback()
        with job_write_transaction(session, job_id):
            job = session.get(BackgroundJob, job_id)
            if job is not None:
                job.state = BackgroundJobState.FAILED
                job.error = str(error)
                job.lease_owner = None
                job.lease_expires_at = None
        raise
