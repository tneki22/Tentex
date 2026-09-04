"""Чистые расчёты времени: объединение интервалов, сон и учебные сутки."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.preparation.schemas import PreparationConfig

DAY_SECONDS = 86400


def utc(value: datetime) -> datetime:
    """Старые SQLite timestamps хранят UTC без tzinfo."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def naive_utc(value: datetime) -> datetime:
    """На запись сохраняется существующий формат времени SQLite."""
    return utc(value).replace(tzinfo=None)


def study_date(value: datetime, config: PreparationConfig) -> date:
    """Ночь до границы суток относится к предыдущему учебному дню."""
    local = utc(value).astimezone(ZoneInfo(config.timezone))
    shift = timedelta(hours=config.day_boundary.hour, minutes=config.day_boundary.minute)
    return (local - shift).date()


def day_bounds(day: date, config: PreparationConfig) -> tuple[datetime, datetime]:
    """Границы создаются в местной зоне, поэтому переход DST не равен всегда 24 часам."""
    zone = ZoneInfo(config.timezone)
    return (
        datetime.combine(day, config.day_boundary, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), config.day_boundary, zone).astimezone(UTC),
    )


def union_seconds(intervals: list[tuple[datetime, datetime]]) -> int:
    """Сон, занятость и несколько вкладок не должны вычитаться/считаться дважды."""
    end = None
    seconds = 0.0
    for left, right in sorted((utc(a), utc(b)) for a, b in intervals if b > a):
        start = max(left, end) if end is not None else left
        seconds += max(0, (right - start).total_seconds())
        end = max(end, right) if end is not None else right
    return int(seconds)


def _window(day: date, start: time, end: time, zone: ZoneInfo):
    left = datetime.combine(day, start, zone).astimezone(UTC)
    last_day = day + timedelta(days=int(end <= start))
    return left, datetime.combine(last_day, end, zone).astimezone(UTC)


def budget_minutes(day: date, config: PreparationConfig, deadline: date | None) -> int:
    """Явное исключение даты имеет приоритет над недельным бюджетом."""
    if day in config.rest_dates or (deadline and day > deadline):
        return 0
    if deadline == day and not config.exam_day_enabled:
        return 0
    budget = config.date_minutes.get(
        day, config.weekday_minutes.get(day.weekday(), config.daily_minutes or 0)
    )
    if deadline and day == deadline - timedelta(days=1) and day not in config.date_minutes:
        budget = int(budget * config.final_day_ratio)
    return budget


def capacity_minutes(
    day: date,
    config: PreparationConfig,
    deadline: date | None,
    exam_time: time | None,
    *,
    now: datetime | None = None,
    used_seconds: int = 0,
) -> int:
    """Будущий бюджет ограничен свободным временем и остатком дневного лимита."""
    left, right = day_bounds(day, config)
    if now is not None:
        left = max(left, utc(now))
    zone = ZoneInfo(config.timezone)
    if deadline:
        # Резерв может начинаться в предыдущие учебные сутки (например, экзамен в 01:00).
        exam_midnight = datetime.combine(deadline, time.min, zone).astimezone(UTC)
        if exam_time is not None:
            cutoff = datetime.combine(deadline, exam_time, zone).astimezone(UTC)
            right = min(right, cutoff - timedelta(minutes=config.exam_reserve_minutes))
        if exam_time is None or not config.exam_day_enabled:
            right = min(right, exam_midnight)
    if right <= left:
        return 0
    blocked = []
    for offset in (-1, 0, 1):
        civil_day = day + timedelta(days=offset)
        windows = [(config.sleep_start, config.sleep_end)]
        for busy in config.busy_windows:
            matches = (
                busy.on_date == civil_day
                if busy.on_date
                else (busy.weekday is None or busy.weekday == civil_day.weekday())
            )
            if matches:
                windows.append((busy.start, busy.end))
        for start, end in windows:
            a, b = _window(civil_day, start, end, zone)
            blocked.append((max(left, a), min(right, b)))
    free = max(0, int((right - left).total_seconds()) - union_seconds(blocked))
    budget = max(0, budget_minutes(day, config, deadline) * 60 - used_seconds)
    return min(free, budget) // 60


def dates_between(start: date, end: date) -> list[date]:
    """Расчёт конечного диапазона используется календарём и планировщиком."""
    return [start + timedelta(days=i) for i in range(max(0, (end - start).days + 1))]
