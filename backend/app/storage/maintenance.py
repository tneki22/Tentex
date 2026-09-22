"""Файловая координация API и worker для операций над всей установкой."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.config import settings
from app.projects.errors import ProjectConflictError


def active() -> bool:
    """Флаг читается без SQLite: база может прямо сейчас заменяться."""
    return settings.maintenance_path.exists()


def read_state() -> dict[str, object] | None:
    try:
        return json.loads(settings.maintenance_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def begin(operation: str, operation_id: UUID) -> None:
    """Атомарно занять установку одной глобальной операцией."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "operation": operation,
        "operation_id": str(operation_id),
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        descriptor = os.open(
            settings.maintenance_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise ProjectConflictError(
            "Хранилище уже занято другой служебной операцией",
            code="maintenance_busy",
        ) from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False)


def finish(operation_id: UUID) -> None:
    """Снять только собственную блокировку, не чужую более новую."""
    state = read_state()
    if state and state.get("operation_id") == str(operation_id):
        settings.maintenance_path.unlink(missing_ok=True)


@contextmanager
def lock(operation: str, operation_id: UUID) -> Iterator[None]:
    begin(operation, operation_id)
    try:
        yield
    finally:
        finish(operation_id)


def ensure_directory(path: Path) -> Path:
    """Создать каталог и проверить реальную запись, а не только права в ACL."""
    resolved = path.expanduser().resolve()
    storage_root = settings.storage_dir.resolve()
    if resolved == storage_root or storage_root in resolved.parents:
        raise ProjectConflictError(
            "Папка копий не может находиться внутри файлового хранилища",
            code="storage_path_invalid",
        )
    resolved.mkdir(parents=True, exist_ok=True)
    probe = resolved / ".tentex-write-test"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as error:
        raise ProjectConflictError(
            "Tentex не может записывать в выбранную папку копий",
            code="storage_path_invalid",
        ) from error
    return resolved
