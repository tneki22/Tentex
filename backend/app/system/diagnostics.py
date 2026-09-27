"""Журнал классифицированных диагностических событий API и воркера.

Журнал — отдельный JSONL-файл в `data/diagnostics`, а не таблица SQLite: он
нужен как раз тогда, когда база не отвечает. Строка хранит только код сбоя,
источник (`api`/`worker`) и время. Текст исключения, SQL, пути и данные
пользователя сюда не попадают — их место в обычном логе процесса.

Сбой держится в сводке, пока соответствующий узел не пройдёт проверку:
запись в базу — короткой пробой по кнопке «Проверить», целостность — фоновой
проверкой хранилища. Узел отмечается событием `recovered`, и всё, что было до
него, в сводку больше не попадает.
"""

from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy.exc import DBAPIError

from app.config import settings

type DiagnosticSource = Literal["api", "worker"]
#: `failure` — операция не удалась. `exhausted` — повторы при блокировке
#: исчерпаны, но вызывающий код переживёт это и попробует снова позже.
type FailureKind = Literal["failure", "exhausted"]

#: Узел, который проверяется, чтобы снять сбой. Код без узла не пишется.
NODE_BY_CODE: dict[str, str] = {
    "database_locked": "database",
    "database_io": "database",
    "disk_full": "database",
    "database_corrupt": "integrity",
}

#: Фрагменты сообщений SQLite → код. Порядок значим: «disk is full» раньше
#: общего «disk I/O», повреждение раньше «не открыть файл».
_MESSAGE_CODES: tuple[tuple[str, str], ...] = (
    ("database is locked", "database_locked"),
    ("database is busy", "database_locked"),
    ("database table is locked", "database_locked"),
    ("database or disk is full", "disk_full"),
    ("database disk image is malformed", "database_corrupt"),
    ("file is not a database", "database_corrupt"),
    ("disk i/o error", "database_io"),
    ("unable to open database file", "database_io"),
    ("attempt to write a readonly database", "database_io"),
)

#: Одиночный исчерпанный повтор — не повод звать человека: воркер повторит
#: через секунду. Устойчивой блокировкой считаются два и больше.
EXHAUSTED_THRESHOLD = 2
#: Тот же код от того же процесса в этом окне не пишется повторно: одна
#: упавшая операция часто логируется и слоем ниже, и middleware.
DEDUP_SECONDS = 5.0
#: Журнал обрезается до последних строк, когда файл перерастает предел.
MAX_EVENTS = 400
TRIM_BYTES = 64 * 1024

_source: DiagnosticSource = "api"
_lock = threading.Lock()
_recent: dict[tuple[str, str], float] = {}


def set_source(source: DiagnosticSource) -> None:
    """Воркер представляется при старте; по умолчанию события пишет API."""
    global _source
    _source = source


def classify(error: BaseException) -> str | None:
    """Код сбоя по цепочке исключений или `None`, если сбой не наш.

    SQLAlchemy заворачивает ошибку драйвера в `DBAPIError.orig`, а прикладной
    код — в свои исключения через `raise ... from`, поэтому просматривается
    вся цепочка, а не только верхнее исключение.
    """
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        code = _classify_single(current)
        if code is not None:
            return code
        for nested in (getattr(current, "orig", None), current.__cause__, current.__context__):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


def _classify_single(error: BaseException) -> str | None:
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return "disk_full"
    if isinstance(error, sqlite3.DatabaseError | DBAPIError):
        message = str(error).lower()
        for fragment, code in _MESSAGE_CODES:
            if fragment in message:
                return code
    return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _directory() -> Path:
    """Отдельная точка, чтобы тесты не писали в журнал настоящей установки."""
    return settings.diagnostics_dir


def _events_path() -> Path:
    return _directory() / "events.jsonl"


def _worker_path() -> Path:
    return _directory() / "worker.json"


def _append(event: dict[str, str]) -> None:
    path = _events_path()
    line = json.dumps(event, ensure_ascii=False) + "\n"
    # Журнал вспомогательный: диск может быть полон или недоступен как раз
    # из-за того сбоя, о котором он пишет. Потерять строку лучше, чем уронить
    # обработчик логов или операцию, которая его вызвала.
    with _lock, contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(line)
        if path.stat().st_size > TRIM_BYTES:
            _trim(path)


def _trim(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)[-MAX_EVENTS:]
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text("".join(lines), encoding="utf-8")
    os.replace(temporary, path)


def record_failure(code: str, *, kind: FailureKind = "failure") -> None:
    """Записать классифицированный сбой. Неизвестный код молча пропускается."""
    if code not in NODE_BY_CODE:
        return
    key = (code, kind)
    now = time.monotonic()
    with _lock:
        last = _recent.get(key)
        if last is not None and now - last < DEDUP_SECONDS:
            return
        _recent[key] = now
    _append({"at": _now_iso(), "kind": kind, "code": code, "source": _source})


def record_error(error: BaseException, *, kind: FailureKind = "failure") -> str | None:
    """Классифицировать и записать исключение; вернуть код, если он есть."""
    code = classify(error)
    if code is not None:
        record_failure(code, kind=kind)
    return code


def record_recovered(node: str) -> None:
    """Узел прошёл проверку: всё, что было записано по нему раньше, снято."""
    _append({"at": _now_iso(), "kind": "recovered", "node": node, "source": _source})


@dataclass(frozen=True, slots=True)
class ActiveProblem:
    """Сбой, который ещё не снят успешной проверкой своего узла."""

    code: str
    node: str
    occurrences: int
    last_at: datetime
    sources: tuple[str, ...]


def _read_events() -> list[dict[str, str]]:
    try:
        raw = _events_path().read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return []
    events: list[dict[str, str]] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and isinstance(event.get("at"), str):
            events.append(event)
    return events


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def active_problems() -> list[ActiveProblem]:
    """Неснятые сбои, самые свежие первыми."""
    events = _read_events()
    recovered: dict[str, datetime] = {}
    for event in events:
        at = _parse_time(event["at"])
        node = event.get("node")
        if event.get("kind") == "recovered" and at is not None and node:
            recovered[node] = max(at, recovered.get(node, at))
    grouped: dict[str, list[tuple[datetime, str, str]]] = {}
    for event in events:
        kind = event.get("kind")
        code = event.get("code", "")
        node = NODE_BY_CODE.get(code)
        at = _parse_time(event["at"])
        if kind not in ("failure", "exhausted") or node is None or at is None:
            continue
        if node in recovered and at <= recovered[node]:
            continue
        grouped.setdefault(code, []).append((at, kind, event.get("source", "api")))
    problems: list[ActiveProblem] = []
    for code, items in grouped.items():
        failed = any(kind == "failure" for _, kind, _ in items)
        if not failed and len(items) < EXHAUSTED_THRESHOLD:
            continue
        problems.append(
            ActiveProblem(
                code=code,
                node=NODE_BY_CODE[code],
                occurrences=len(items),
                last_at=max(at for at, _, _ in items),
                sources=tuple(sorted({source for _, _, source in items})),
            )
        )
    problems.sort(key=lambda problem: problem.last_at, reverse=True)
    return problems


def touch_worker_heartbeat() -> None:
    """Воркер жив: время пишется целиком новым файлом, чтобы API не прочёл обрывок."""
    path = _worker_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"at": _now_iso()}), encoding="utf-8")
        os.replace(temporary, path)


def worker_heartbeat_at() -> datetime | None:
    try:
        payload = json.loads(_worker_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    value = payload.get("at") if isinstance(payload, dict) else None
    return _parse_time(value) if isinstance(value, str) else None


class DiagnosticsHandler(logging.Handler):
    """Переводит залогированные исключения в коды журнала.

    Подключается к корневому логгеру на уровне ERROR: всё, что упало и было
    записано через `log.exception`, проходит через классификацию. Сырые
    сообщения и трассировки дальше обычного лога не уходят.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if not record.exc_info or record.exc_info[1] is None:
            return
        with contextlib.suppress(Exception):
            record_error(record.exc_info[1])
