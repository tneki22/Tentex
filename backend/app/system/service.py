"""Сводка «Состояние»: лёгкие независимые проверки установки.

Каждая проверка читает уже существующие настройки и таблицы и падает сама по
себе: её отказ превращается в строку «Не удалось проверить …», остальные
продолжают. Тяжёлого здесь нет — полная проверка SQLite и обход файлов
хранилища остаются фоновой задачей `storage_verify`, а сводка лишь читает её
последний итог. Контракт — `docs/architecture/system-status.md`.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    AiRun,
    AiSettings,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    BackupArchive,
    BackupArchiveState,
    EmbeddingProfile,
    Material,
    OcrSettings,
    ParserMode,
    Project,
    RetrievalIndex,
    RetrievalSettings,
    StorageSettings,
    TransferArtifact,
    utc_now,
)
from app.ocr import downloads as ocr_downloads
from app.ocr import settings as ocr_settings
from app.projects.demo import DEMO_PROJECT_ID
from app.storage import maintenance
from app.storage import service as storage_service
from app.system import diagnostics
from app.system.resources import resource_summary
from app.system.schemas import (
    StatusCommand,
    StatusLevel,
    StatusSection,
    SystemProbeRead,
    SystemStatusItem,
    SystemStatusRead,
    SystemStatusTarget,
    SystemStorageRead,
)

log = logging.getLogger("tentex.system")

GIB = 1024**3
#: Меньше гигабайта — уже не влезет ни копия, ни крупный скан.
DISK_DANGER_BYTES = 1 * GIB
DISK_WARNING_BYTES = 5 * GIB
#: Воркер отмечается раз в 15 с; шесть пропусков подряд — он не работает.
WORKER_SILENT_AFTER = timedelta(seconds=90)
#: Живой воркер забирает задачу с истёкшим лизом за секунду. Две минуты
#: с истёкшим лизом — задачу никто не ведёт.
STUCK_JOB_GRACE = timedelta(minutes=2)
#: Автокопия ставится при первом опросе после своего времени, даже если
#: компьютер был выключен. Двое суток без неё — расписание не срабатывает.
AUTOMATIC_BACKUP_OVERDUE = timedelta(hours=48)
AI_LIMIT_NEAR_SHARE = Decimal("0.8")
PROBE_TIMEOUT_SECONDS = 2.0
#: Размер моделей меняется только установкой — обходить каталоги на каждый
#: опрос сводки незачем.
MODELS_SIZE_TTL_SECONDS = 600.0

LEVEL_RANK: dict[str, int] = {"danger": 0, "warning": 1, "unknown": 2, "info": 3, "ok": 4}
SECTION_RANK: dict[str, int] = {"attention": 0, "storage": 1, "capabilities": 2}
ATTENTION_LEVELS = frozenset({"danger", "warning", "unknown"})
#: Задачи обслуживания со своими строками в сводке: в общий счётчик упавших
#: они не попадают, чтобы один сбой не звучал дважды.
OWN_ROW_JOB_KINDS = frozenset({BackgroundJobKind.BACKUP_CREATE, BackgroundJobKind.STORAGE_VERIFY})

AI_OVERVIEW = "/setup?section=ai&subsection=overview"
AI_PROVIDERS = "/setup?section=ai&subsection=providers"
AI_DEFAULTS = "/setup?section=ai&subsection=defaults"
AI_LIMITS = "/setup?section=ai&subsection=limits"
OCR_ENGINES = "/setup?section=ocr&subsection=engines"
OCR_MODELS = "/setup?section=ocr&subsection=models"
SEARCH_INDEX = "/setup?section=search&subsection=index"
SEARCH_MODELS = "/setup?section=search&subsection=models"
STORAGE_OVERVIEW = "/setup?section=storage&subsection=overview"
STORAGE_BACKUPS = "/setup?section=storage&subsection=backups"
STORAGE_MAINTENANCE = "/setup?section=storage&subsection=maintenance"

_models_size_cache: tuple[float, int] | None = None


def _link(label: str, href: str) -> SystemStatusTarget:
    return SystemStatusTarget(kind="link", label=label, href=href)


def _command(label: str, command: StatusCommand) -> SystemStatusTarget:
    return SystemStatusTarget(kind="command", label=label, command=command)


def _aware(value: datetime | None) -> datetime | None:
    """В базе время хранится наивным UTC; наружу — с зоной, чтобы браузер не сдвигал."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _plural(count: int, one: str, few: str, many: str) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        return many
    if count % 10 == 1:
        return one
    if 2 <= count % 10 <= 4:
        return few
    return many


def _format_bytes(value: int) -> str:
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    text = f"{amount:.0f}" if amount >= 10 or unit == "Б" else f"{amount:.1f}"
    return f"{text.replace('.', ',')} {unit}"


def _money(value: Decimal) -> str:
    return f"${value:.2f}"


@dataclass(slots=True)
class _Entry:
    item: SystemStatusItem
    cause: str | None


@dataclass(slots=True)
class _Report:
    """Строки сводки с общей причиной: из строк одной причины остаётся самая
    серьёзная, чтобы, например, выключенные модели не звучали и в «ИИ», и в
    «Распознавании»."""

    entries: list[_Entry] = field(default_factory=list)

    def add(
        self,
        code: str,
        level: StatusLevel,
        home: StatusSection,
        title: str,
        action: str | None = None,
        target: SystemStatusTarget | None = None,
        *,
        cause: str | None = None,
        last_failure_at: datetime | None = None,
        occurrences: int | None = None,
    ) -> None:
        item = SystemStatusItem(
            code=code,
            level=level,
            section=home,
            title=title,
            action=action,
            target=target,
            last_failure_at=_aware(last_failure_at),
            occurrences=occurrences,
        )
        self.entries.append(_Entry(item=item, cause=cause))

    def unchecked(self, code: str, what: str, home: StatusSection) -> None:
        self.add(
            f"{code}_unchecked",
            "unknown",
            home,
            f"Не удалось проверить {what}",
            "обновите сводку чуть позже",
        )

    def items(self) -> list[SystemStatusItem]:
        best: dict[str, int] = {}
        for index, entry in enumerate(self.entries):
            if entry.cause is None:
                continue
            current = best.get(entry.cause)
            if current is None or (
                LEVEL_RANK[entry.item.level] < LEVEL_RANK[self.entries[current].item.level]
            ):
                best[entry.cause] = index
        kept: list[tuple[int, SystemStatusItem]] = []
        for index, entry in enumerate(self.entries):
            if entry.cause is not None and best[entry.cause] != index:
                continue
            item = entry.item
            if item.level in ATTENTION_LEVELS:
                item = item.model_copy(update={"section": "attention"})
            kept.append((index, item))
        kept.sort(
            key=lambda pair: (
                SECTION_RANK[pair[1].section],
                LEVEL_RANK[pair[1].level] if pair[1].section == "attention" else 0,
                pair[0],
            )
        )
        return [item for _, item in kept]


def _guarded(
    report: _Report,
    session: Session | None,
    code: str,
    what: str,
    home: StatusSection,
    check: Callable[[], None],
) -> bool:
    """Выполнить одну проверку; её отказ не должен остановить остальные."""
    try:
        check()
    except Exception:
        if session is not None:
            session.rollback()
        # WARNING, а не exception: проверка сводки — не упавшая операция, и
        # в журнал сбоев она попадать не должна.
        log.warning("system status check %s failed", code, exc_info=True)
        report.unchecked(code, what, home)
        return False
    return True


# --- База данных и журнал ---------------------------------------------------


def _check_database(report: _Report) -> bool:
    """Короткое чтение отдельным соединением с малым таймаутом, мимо пула API."""
    path = settings.database_path
    if not path.exists():
        report.add(
            "database_missing",
            "danger",
            "attention",
            "Файл базы данных не найден",
            "проверьте папку данных или восстановите резервную копию",
            _link("Резервные копии", STORAGE_BACKUPS),
            cause="database",
        )
        return False
    try:
        connection = sqlite3.connect(str(path), timeout=PROBE_TIMEOUT_SECONDS)
        try:
            connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as error:
        if diagnostics.record_error(error) is None:
            diagnostics.record_failure("database_io")
        report.add(
            "database_unavailable",
            "danger",
            "attention",
            "База данных не отвечает",
            "остановите зависшую операцию и проверьте хранилище",
            _command("Проверить", "probe_database"),
            cause="database",
            last_failure_at=utc_now(),
        )
        return False
    return True


JOURNAL_TEXTS: dict[str, tuple[str, str]] = {
    "database_locked": (
        "База данных не отвечает: запись заблокирована",
        "остановите зависшую операцию и проверьте хранилище",
    ),
    "database_io": (
        "База данных не отвечает: ошибка чтения или записи",
        "проверьте диск и папку данных, затем нажмите «Проверить»",
    ),
    "disk_full": (
        "Запись не удалась: диск переполнен",
        "освободите место и нажмите «Проверить»",
    ),
    "database_corrupt": (
        "Найдено повреждение базы данных",
        "восстановите копию или запустите проверку хранилища",
    ),
}


def _check_journal(report: _Report) -> None:
    for problem in diagnostics.active_problems():
        title, action = JOURNAL_TEXTS[problem.code]
        integrity = problem.node == "integrity"
        report.add(
            problem.code,
            "danger",
            "attention",
            title,
            action,
            _command("Проверить хранилище", "verify_storage")
            if integrity
            else _command("Проверить", "probe_database"),
            cause=problem.node,
            last_failure_at=problem.last_at,
            occurrences=problem.occurrences,
        )


# --- Фоновая обработка ------------------------------------------------------


def _check_worker(session: Session, report: _Report) -> None:
    beat = diagnostics.worker_heartbeat_at()
    if beat is not None and datetime.now(UTC) - beat <= WORKER_SILENT_AFTER:
        return
    waiting = session.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(BackgroundJob.state.in_([BackgroundJobState.QUEUED, BackgroundJobState.RUNNING]))
    ) or 0
    target = _command("Фоновые задачи", "open_background_jobs")
    if waiting:
        noun = _plural(waiting, "задача ждёт", "задачи ждут", "задач ждут")
        report.add(
            "worker_offline",
            "danger",
            "attention",
            f"Фоновый обработчик не отвечает — {waiting} {noun}",
            "перезапустите Tentex, задачи продолжатся сами",
            target,
            cause="worker",
            last_failure_at=beat,
        )
        return
    report.add(
        "worker_offline",
        "warning",
        "attention",
        "Фоновый обработчик не отвечает",
        "перезапустите Tentex, иначе разбор, копии и ИИ-задачи не начнутся",
        target,
        cause="worker",
        last_failure_at=beat,
    )


def _check_jobs(session: Session, report: _Report) -> None:
    failed_count, failed_at = session.execute(
        select(func.count(), func.max(BackgroundJob.updated_at)).where(
            BackgroundJob.state == BackgroundJobState.FAILED,
            BackgroundJob.reviewed_at.is_(None),
            BackgroundJob.kind.not_in(OWN_ROW_JOB_KINDS),
        )
    ).one()
    target = _command("Фоновые задачи", "open_background_jobs")
    if failed_count:
        noun = _plural(failed_count, "фоновая задача", "фоновые задачи", "фоновых задач")
        single = failed_count == 1
        report.add(
            "jobs_failed",
            "warning",
            "attention",
            "Фоновая задача требует внимания"
            if single
            else f"{failed_count} {noun} требуют внимания",
            f"откройте {'её' if single else 'их'} и повторите действие",
            target,
            last_failure_at=failed_at,
            occurrences=failed_count,
        )
    stuck = session.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(
            BackgroundJob.state == BackgroundJobState.RUNNING,
            BackgroundJob.lease_expires_at < utc_now() - STUCK_JOB_GRACE,
        )
    ) or 0
    if stuck:
        report.add(
            "jobs_stuck",
            "warning",
            "attention",
            "Фоновая задача зависла" if stuck == 1 else f"Зависли фоновые задачи: {stuck}",
            "откройте её и повторите действие, а если не поможет — перезапустите Tentex",
            target,
            cause="worker",
        )


# --- Хранилище и копии ------------------------------------------------------


def _models_bytes() -> int:
    global _models_size_cache
    now = time.monotonic()
    if _models_size_cache is not None and now - _models_size_cache[0] < MODELS_SIZE_TTL_SECONDS:
        return _models_size_cache[1]
    value = storage_service.models_bytes()
    _models_size_cache = (now, value)
    return value


def _database_bytes() -> int:
    total = 0
    for suffix in ("", "-wal"):
        path = Path(f"{settings.database_path}{suffix}")
        if path.exists():
            total += path.stat().st_size
    return total


def _sum(session: Session, column: Any, *conditions: Any) -> int:
    """Сумма колонки SQLAlchemy по условиям; пустая таблица — ноль."""
    return int(session.scalar(select(func.coalesce(func.sum(column), 0)).where(*conditions)) or 0)


@dataclass(slots=True)
class _StorageFacts:
    read: SystemStorageRead
    #: Сколько займёт следующая полная копия — база и исходники.
    next_backup_bytes: int = 0
    has_data: bool = False
    backups_directory: Path | None = None
    latest_ready_at: datetime | None = None


def _storage_facts(session: Session | None) -> _StorageFacts:
    usage = shutil.disk_usage(settings.data_dir)
    if session is None:
        return _StorageFacts(
            read=SystemStorageRead(
                used_bytes=None,
                free_bytes=usage.free,
                total_bytes=usage.total,
                last_backup_at=None,
                backup_in_progress=False,
                automatic_enabled=None,
                daily_time=None,
                retention_days=None,
            )
        )
    policy = session.get(StorageSettings, 1)
    database = _database_bytes()
    files = _sum(session, Material.size_bytes)
    temporary = _sum(session, TransferArtifact.size_bytes)
    backups = _sum(
        session, BackupArchive.size_bytes, BackupArchive.state == BackupArchiveState.READY
    )
    latest_ready = session.scalar(
        select(func.max(BackupArchive.completed_at)).where(
            BackupArchive.state == BackupArchiveState.READY
        )
    )
    in_progress = session.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(
            BackgroundJob.kind == BackgroundJobKind.BACKUP_CREATE,
            BackgroundJob.state.in_([BackgroundJobState.QUEUED, BackgroundJobState.RUNNING]),
        )
    )
    has_data = bool(
        session.scalar(select(Material.id).limit(1))
        or session.scalar(select(Project.id).where(Project.id != DEMO_PROJECT_ID).limit(1))
    )
    directory = (
        Path(policy.backup_directory)
        if policy is not None and policy.backup_directory
        else settings.default_backup_dir
    )
    return _StorageFacts(
        read=SystemStorageRead(
            used_bytes=database + files + temporary + backups + _models_bytes(),
            free_bytes=usage.free,
            total_bytes=usage.total,
            last_backup_at=_aware(latest_ready),
            backup_in_progress=bool(in_progress),
            automatic_enabled=policy.automatic_enabled if policy else False,
            daily_time=policy.daily_time if policy else "03:00",
            retention_days=policy.retention_days if policy else 7,
        ),
        next_backup_bytes=database + files,
        has_data=has_data,
        backups_directory=directory,
        latest_ready_at=latest_ready,
    )


def _check_disk(facts: _StorageFacts, report: _Report) -> None:
    free = facts.read.free_bytes
    target = _link("Хранилище", STORAGE_OVERVIEW)
    text = f"На диске осталось {_format_bytes(free)}"
    if free < DISK_DANGER_BYTES:
        report.add(
            "disk_low", "danger", "attention", text,
            "освободите место — новые материалы и копии могут не записаться", target,
        )
    elif free < DISK_WARNING_BYTES or free < facts.next_backup_bytes:
        report.add(
            "disk_low", "warning", "attention", text,
            "освободите место для материалов и копий", target,
        )


def _check_backups(session: Session, facts: _StorageFacts, report: _Report) -> None:
    backups_link = _link("Резервные копии", STORAGE_BACKUPS)
    latest = session.scalar(
        select(BackupArchive).order_by(BackupArchive.created_at.desc()).limit(1)
    )
    failed_at = (
        latest.completed_at or latest.created_at
        if latest is not None and latest.state == BackupArchiveState.FAILED
        else None
    )
    if facts.latest_ready_at is None and facts.has_data:
        # Одна причина — одна строка: «копий нет» и «последняя упала» вместе
        # читаются как «первая копия не получилась», и повтор — прямо здесь.
        if facts.read.backup_in_progress:
            report.add(
                "backup_in_progress", "info", "storage",
                "Создаётся первая резервная копия", "ход — в «Фоновых задачах»",
                _command("Фоновые задачи", "open_background_jobs"),
            )
        elif failed_at is not None:
            report.add(
                "backup_failed", "warning", "attention",
                "Не удалось создать первую копию",
                "проверьте свободное место и папку копий, затем повторите",
                _command("Повторить", "create_backup"),
                last_failure_at=failed_at,
            )
        else:
            report.add(
                "backup_missing", "warning", "attention",
                "Резервных копий ещё нет", "создайте первую",
                _command("Создать копию", "create_backup"),
            )
    elif failed_at is not None and not facts.read.backup_in_progress:
        report.add(
            "backup_failed", "warning", "attention",
            "Не удалось создать копию",
            "проверьте свободное место и папку копий, затем повторите",
            backups_link,
            last_failure_at=failed_at,
        )
    overdue = (
        facts.read.automatic_enabled
        and facts.latest_ready_at is not None
        and not facts.read.backup_in_progress
        and utc_now() - facts.latest_ready_at > AUTOMATIC_BACKUP_OVERDUE
    )
    if overdue:
        assert facts.latest_ready_at is not None
        days = (utc_now() - facts.latest_ready_at).days
        report.add(
            "backup_overdue", "warning", "attention",
            f"Автоматической копии нет уже {days} {_plural(days, 'день', 'дня', 'дней')}",
            "проверьте, что Tentex и фоновый обработчик запущены",
            backups_link,
            cause="worker",
        )
    directory = facts.backups_directory
    if (
        facts.latest_ready_at is not None
        and directory is not None
        and storage_service.backups_inside_data_dir(directory)
    ):
        report.add(
            "backups_inside_data", "info", "storage",
            "Копии лежат внутри папки рабочих данных",
            "при поломке диска пропадут вместе с ней — выберите папку на другом диске",
            backups_link,
        )


def _check_storage_verify(session: Session, report: _Report) -> None:
    job = session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == BackgroundJobKind.STORAGE_VERIFY,
            BackgroundJob.state.in_([BackgroundJobState.COMPLETED, BackgroundJobState.FAILED]),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        return
    if job.state == BackgroundJobState.FAILED:
        report.add(
            "storage_verify_failed", "warning", "attention",
            "Не удалось проверить хранилище", "запустите проверку ещё раз",
            _command("Проверить снова", "verify_storage"),
            last_failure_at=job.updated_at,
        )
        return
    result = job.checkpoint.get("result") if isinstance(job.checkpoint, dict) else None
    if not isinstance(result, dict) or result.get("ok") is not False:
        return
    missing = result.get("missing_files") or []
    if missing:
        count = len(missing)
        more = "+" if count >= 100 else ""
        report.add(
            "storage_files_missing", "warning", "attention",
            f"Не найдены файлы материалов: {count}{more}",
            "восстановите копию или загрузите эти материалы заново",
            _link("Обслуживание", STORAGE_MAINTENANCE),
            last_failure_at=job.completed_at,
        )
        return
    report.add(
        "storage_integrity", "danger", "attention",
        "Найдено повреждение базы данных",
        "восстановите последнюю копию",
        _link("Резервные копии", STORAGE_BACKUPS),
        cause="integrity",
        last_failure_at=job.completed_at,
    )


# --- Дополнительные возможности --------------------------------------------


def _today_spent(session: Session) -> Decimal:
    """Та же сумма, что проверяет шлюз перед вызовом (`gateway._check_limits`)."""
    start = datetime.combine(date.today(), day_time.min)
    spent = session.scalar(
        select(func.coalesce(func.sum(AiRun.actual_cost_usd), 0)).where(
            AiRun.status == "succeeded", AiRun.created_at >= start
        )
    )
    return Decimal(spent or 0)


def _check_ai(session: Session, report: _Report) -> None:
    row = session.get(AiSettings, 1)
    if row is None or not row.external_models_enabled:
        report.add(
            "ai_disabled", "info", "capabilities",
            "Внешние модели выключены", "включите их, если нужны облачные функции",
            _link("ИИ", AI_OVERVIEW),
            cause="external_off",
        )
        return
    providers_link = _link("Провайдеры", AI_PROVIDERS)
    providers = list(session.scalars(select(AiProviderConnection)))
    if not providers:
        report.add(
            "ai_no_provider", "warning", "capabilities",
            "Внешние модели включены, но провайдер не добавлен",
            "добавьте провайдера и ключ доступа", providers_link, cause="ai_setup",
        )
        return
    if not any(provider.api_key_ciphertext for provider in providers):
        report.add(
            "ai_no_key", "warning", "capabilities",
            "У провайдера нет ключа доступа", "добавьте ключ в карточке провайдера",
            providers_link, cause="ai_setup",
        )
        return
    if not (row.default_text_provider_id and row.default_text_model_id):
        report.add(
            "ai_no_text_model", "warning", "capabilities",
            "Не выбрана текстовая модель", "выберите её — на ней работают чат и проверка ответов",
            _link("По умолчанию", AI_DEFAULTS), cause="ai_setup",
        )
        return
    provider = session.get(AiProviderConnection, row.default_text_provider_id)
    label = provider.label if provider else "текстовой модели"
    if provider is None or not provider.api_key_ciphertext:
        report.add(
            "ai_no_key", "warning", "capabilities",
            f"У провайдера «{label}» нет ключа доступа",
            "добавьте ключ или выберите модель другого провайдера",
            providers_link, cause="ai_setup",
        )
        return
    if provider.last_test_status == "ai_invalid_credentials":
        report.add(
            "ai_key_rejected", "warning", "capabilities",
            f"Провайдер «{label}» отклонил ключ", "обновите ключ и проверьте подключение",
            providers_link, cause="ai_setup", last_failure_at=provider.last_tested_at,
        )
        return
    limit = row.daily_limit_usd
    if limit is not None and limit > 0:
        spent = _today_spent(session)
        usage = f"потрачено {_money(spent)} из {_money(limit)}"
        if spent >= limit:
            report.add(
                "ai_limit_reached", "warning", "capabilities",
                "Дневной лимит расходов исчерпан",
                f"{usage} — поднимите лимит или подождите до завтра",
                _link("Расходы", AI_LIMITS),
            )
        elif spent >= limit * AI_LIMIT_NEAR_SHARE:
            report.add(
                "ai_limit_near", "info", "capabilities",
                "Дневной лимит расходов почти исчерпан", usage, _link("Расходы", AI_LIMITS),
            )
    model = session.get(AiModelCatalogEntry, (provider.id, row.default_text_model_id))
    name = model.display_name if model else row.default_text_model_id
    report.add(
        "ai_ready", "ok", "capabilities",
        "Внешние модели готовы", f"текстовая модель — {name}", _link("ИИ", AI_OVERVIEW),
    )


def _check_ocr(session: Session, report: _Report) -> None:
    row = session.get(OcrSettings, 1)
    mode = row.default_mode if row else ParserMode.FAST
    readiness, _, active = ocr_settings.cloud_readiness(session)
    engines = _link("Распознавание", OCR_ENGINES)
    if mode == ParserMode.CLOUD:
        if readiness == "ready":
            report.add(
                "ocr_ready", "ok", "capabilities",
                "Распознавание «Облако» готово", f"модель страниц — {active}", engines,
            )
        elif readiness == "unavailable":
            report.add(
                "ocr_not_ready", "warning", "capabilities",
                "Распознавание по умолчанию облачное, а внешние модели выключены",
                "включите модели или выберите способ «Быстро»", engines,
                cause="external_off",
            )
        elif readiness == "needs_models":
            report.add(
                "ocr_not_ready", "warning", "capabilities",
                "Распознавание не готово: не выбрана модель страниц",
                "выберите модель или способ «Быстро»", engines,
            )
        else:
            report.add(
                "ocr_not_ready", "warning", "capabilities",
                "Распознавание не готово: у провайдера модели нет ключа",
                "добавьте ключ или выберите способ «Быстро»", engines,
            )
        return
    if ocr_downloads.engine_ready("fast"):
        report.add(
            "ocr_ready", "ok", "capabilities",
            "Распознавание «Быстро» готово", "текст и сканы читаются локально", engines,
        )
    else:
        report.add(
            "ocr_fast_no_models", "info", "capabilities",
            "Модели для сканов не установлены",
            "текст из PDF читается и так; для сканов поставьте набор заранее",
            _link("Установка", OCR_MODELS),
        )
    if readiness != "ready":
        report.add(
            "ocr_cloud_off", "info", "capabilities",
            "Облачное распознавание не настроено",
            "подключите модель, если нужны формулы и сложные сканы", engines,
            cause="external_off" if readiness == "unavailable" else None,
        )


def _check_search(session: Session, report: _Report) -> None:
    row = session.get(RetrievalSettings, 1)
    active = (
        session.get(RetrievalIndex, row.active_index_id) if row and row.active_index_id else None
    )
    if active is None:
        has_profile = session.scalar(select(EmbeddingProfile.id).limit(1)) is not None
        report.add(
            "search_semantic_off", "info", "capabilities",
            "Поиск по смыслу не настроен",
            "работает поиск по словам; для смыслового соберите индекс",
            _link("Поиск", SEARCH_INDEX if has_profile else SEARCH_MODELS),
        )
        return
    count = active.indexed_material_count
    report.add(
        "search_semantic_ready", "ok", "capabilities",
        "Поиск по смыслу работает",
        f"в индексе {count} {_plural(count, 'материал', 'материала', 'материалов')}",
        _link("Поиск", SEARCH_INDEX),
    )


# --- Сборка сводки ----------------------------------------------------------


def system_status(session: Session) -> SystemStatusRead:
    """Собрать сводку. Ни одна проверка не пишет в базу."""
    report = _Report()
    database_ok = _check_database(report)
    _guarded(report, None, "journal", "журнал сбоев", "attention", lambda: _check_journal(report))
    if maintenance.active():
        report.add(
            "storage_maintenance", "info", "storage",
            "Идёт обслуживание хранилища",
            "копия, проверка или восстановление — изменения подождут пару минут",
        )

    facts: _StorageFacts | None = None

    def load_facts() -> None:
        nonlocal facts
        facts = _storage_facts(session if database_ok else None)

    _guarded(report, session, "storage", "хранилище", "storage", load_facts)
    if facts is not None:
        loaded = facts
        _guarded(report, None, "disk", "свободное место", "storage",
                 lambda: _check_disk(loaded, report))

    if database_ok:
        checks: list[tuple[str, str, StatusSection, Callable[[], None]]] = [
            ("worker", "фоновый обработчик", "attention",
             lambda: _check_worker(session, report)),
            ("jobs", "фоновые задачи", "attention", lambda: _check_jobs(session, report)),
            ("storage_verify", "итог проверки хранилища", "storage",
             lambda: _check_storage_verify(session, report)),
            ("ai", "внешние модели", "capabilities", lambda: _check_ai(session, report)),
            ("ocr", "распознавание", "capabilities", lambda: _check_ocr(session, report)),
            ("search", "поиск", "capabilities", lambda: _check_search(session, report)),
        ]
        if facts is not None:
            loaded_facts = facts
            checks.insert(2, ("backups", "резервные копии", "storage",
                              lambda: _check_backups(session, loaded_facts, report)))
        for code, what, home, check in checks:
            _guarded(report, session, code, what, home, check)
        session.rollback()
    else:
        report.add(
            "dependent_unchecked", "unknown", "attention",
            "Не удалось проверить задачи, копии и настройки",
            "они читаются из базы — сначала верните её",
        )

    items = report.items()
    attention = [item for item in items if item.section == "attention"]
    overall = (
        "attention"
        if any(item.level == "danger" for item in attention)
        else ("warning" if attention else "ok")
    )
    return SystemStatusRead(
        checked_at=datetime.now(UTC),
        overall=overall,
        attention_count=len(attention),
        items=items,
        storage=facts.read if facts is not None else None,
        resources=resource_summary(),
    )


def probe_write_access(session: Session) -> SystemProbeRead:
    """Короткая проба записи без сохранения изменений.

    Резервирует writer SQLite (`BEGIN IMMEDIATE`) и сразу откатывает, затем
    пишет и удаляет крошечный файл в папке данных. Успех снимает сбои записи
    из журнала; неудача записывается в журнал и оставляет строку в сводке.
    """
    ok = True
    try:
        if not settings.database_path.exists():
            raise FileNotFoundError(settings.database_path)
        connection = sqlite3.connect(
            str(settings.database_path), timeout=PROBE_TIMEOUT_SECONDS, isolation_level=None
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ROLLBACK")
        finally:
            connection.close()
        probe = settings.data_dir / ".tentex-write-probe"
        probe.write_bytes(b"ok")
        probe.unlink()
    except (sqlite3.Error, OSError) as error:
        ok = False
        if diagnostics.record_error(error) is None:
            diagnostics.record_failure("database_io")
        log.warning("write probe failed: %s", type(error).__name__)
    if ok:
        diagnostics.record_recovered("database")
    return SystemProbeRead(ok=ok, status=system_status(session))
