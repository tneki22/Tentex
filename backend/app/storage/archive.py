"""Формат `.tentex-backup`: SQLite-снимок, файлы и проверяемый manifest."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from app.config import settings
from app.models import BackupKind
from app.projects.errors import ProjectDomainError

FORMAT = "tentex-backup"
FORMAT_VERSION = 1
APP_VERSION = "0.1.0"
BUFFER_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Хешировать потоково: рабочие архивы значительно больше памяти процесса."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def iter_storage_files(root: Path) -> Iterable[tuple[Path, str]]:
    """Архивировать всё устойчивое; `tmp/` всегда можно построить заново."""
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == "tmp":
            continue
        yield path, PurePosixPath("storage", *relative.parts).as_posix()


def snapshot_database(source: Path, destination: Path) -> tuple[dict[str, int], str]:
    """Получить согласованный SQLite-снимок и убрать машинные секреты/реестры."""
    source_connection = sqlite3.connect(str(source), timeout=30)
    target_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(target_connection, pages=2048)
    finally:
        target_connection.close()
        source_connection.close()

    connection = sqlite3.connect(str(destination))
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("UPDATE ai_provider_connections SET api_key_ciphertext = NULL")
        connection.execute("UPDATE storage_settings SET backup_directory = NULL")
        connection.execute(
            "UPDATE embedding_profiles SET installed = 0 WHERE backend_kind = 'local_hf'"
        )
        connection.execute("DELETE FROM backup_archives")
        connection.execute("DELETE FROM transfer_artifacts")
        connection.execute(
            "DELETE FROM background_jobs WHERE kind IN "
            "('backup_create', 'project_export', 'project_import', "
            "'storage_verify', 'storage_cleanup')"
        )
        connection.commit()
        result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise ProjectDomainError(
                "SQLite не прошла проверку перед упаковкой",
                status=500,
                code="backup_corrupt",
            )
        has_alembic = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
        ).fetchone()
        revision = (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if has_alembic
            else None
        )
        return (
            {
                "projects": connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "materials": connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
                "indexes": connection.execute(
                    "SELECT COUNT(*) FROM retrieval_indexes"
                ).fetchone()[0],
            },
            revision[0] if revision else "unknown",
        )
    finally:
        connection.close()


def create_backup(
    destination: Path,
    *,
    backup_id: UUID,
    kind: BackupKind,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Создать ZIP64 рядом с конечным путём и опубликовать атомарным rename."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = list(iter_storage_files(settings.storage_dir))
    total = len(files) + 1
    entries: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="tentex-backup-", dir=destination.parent) as raw_tmp:
        temp_dir = Path(raw_tmp)
        database_copy = temp_dir / "tentex.sqlite"
        counts, alembic_revision = snapshot_database(settings.database_path, database_copy)
        temp_archive = temp_dir / destination.name
        with zipfile.ZipFile(
            temp_archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            members = [(database_copy, "database/tentex.sqlite"), *files]
            for index, (path, member_name) in enumerate(members, start=1):
                file_hash = sha256_file(path)
                size = path.stat().st_size
                archive.write(path, member_name)
                entries.append({"path": member_name, "size": size, "sha256": file_hash})
                if progress:
                    progress(index, total)
            manifest: dict[str, object] = {
                "format": FORMAT,
                "format_version": FORMAT_VERSION,
                "app_version": APP_VERSION,
                "backup_id": str(backup_id),
                "kind": kind.value,
                "created_at": datetime.now(UTC).isoformat(),
                "counts": counts,
                "alembic_revision": alembic_revision,
                "entries": entries,
                "excluded": [
                    "API-ключи",
                    "installation.secret",
                    "локальные OCR- и embedding-модели",
                    "Typst-пакеты",
                    "временные файлы",
                    "настройки браузера",
                ],
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        shutil.move(temp_archive, destination)
    return manifest


def _safe_member(info: zipfile.ZipInfo) -> bool:
    path = PurePosixPath(info.filename)
    unix_mode = info.external_attr >> 16
    return (
        bool(path.parts)
        and not path.is_absolute()
        and ".." not in path.parts
        and not stat.S_ISLNK(unix_mode)
    )


def validate_backup(path: Path, *, verify_hashes: bool = True) -> dict[str, object]:
    """Проверить тип, пути, объём и checksum до любого извлечения."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if any(not _safe_member(info) for info in infos):
                raise ValueError("unsafe archive member")
            total = sum(info.file_size for info in infos)
            if total > settings.transfer_unpacked_max_bytes:
                raise ProjectDomainError(
                    "Распакованный архив превышает допустимый размер",
                    status=413,
                    code="backup_too_large",
                )
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
                raise ProjectDomainError(
                    "Эта версия Tentex не поддерживает формат копии",
                    status=422,
                    code="backup_incompatible",
                )
            entries = manifest.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries missing")
            known = {info.filename: info for info in infos}
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("path") not in known:
                    raise ValueError("manifest member missing")
                if int(entry.get("size", -1)) != known[str(entry["path"])].file_size:
                    raise ValueError("manifest size mismatch")
                if verify_hashes:
                    digest = hashlib.sha256()
                    with archive.open(str(entry["path"])) as source:
                        while chunk := source.read(BUFFER_SIZE):
                            digest.update(chunk)
                    if digest.hexdigest() != entry.get("sha256"):
                        raise ValueError("manifest checksum mismatch")
            return manifest
    except ProjectDomainError:
        raise
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise ProjectDomainError(
            "Файл резервной копии повреждён или имеет неизвестный формат",
            status=422,
            code="backup_corrupt",
        ) from error


def extract_backup(path: Path, destination: Path) -> dict[str, object]:
    """Извлечь только уже проверенный архив в пустой staging-каталог."""
    manifest = validate_backup(path)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.filename == "manifest.json":
                continue
            target = destination.joinpath(*PurePosixPath(info.filename).parts).resolve()
            if destination.resolve() not in target.parents:
                raise ProjectDomainError(
                    "Архив пытается записать файл вне staging-каталога",
                    status=422,
                    code="backup_corrupt",
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, BUFFER_SIZE)
    return manifest
