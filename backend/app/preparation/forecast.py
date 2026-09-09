"""Эмпирический прогноз сохранения подтверждённых знаний, не вероятности сдачи."""

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from app.preparation.calendar import study_date, utc
from app.preparation.evidence import sm2
from app.preparation.schemas import MemoryForecast, MemoryScenario

OBSERVATION_DAYS = 90
MIN_DISTINCT_TOPICS = 20
MIN_HISTORY_DAYS = 7
MIN_BIN_OBSERVATIONS = 5
WILSON_Z = 1.959963984540054  # Двусторонний 95% интервал доли.


def wilson(successes: int, count: int) -> tuple[float, float]:
    """Интервал Уилсона остаётся ненулевой ширины и при всех успешных ответах."""
    if count <= 0:
        raise ValueError("Нужно хотя бы одно наблюдение")
    p = successes / count
    z2 = WILSON_Z**2
    denominator = 1 + z2 / count
    center = (p + z2 / (2 * count)) / denominator
    margin = WILSON_Z * math.sqrt(p * (1 - p) / count + z2 / (4 * count**2)) / denominator
    return max(0, center - margin), min(1, center + margin)


def _bin(ratio: float) -> int:
    return 0 if ratio <= 1 else 1 if ratio <= 2 else 2


def _scenario(confirmed, evidence, bins, items, unit_map, config, exam_at, now, *, with_plan):
    """Будущие успешные повторения симулируются на копиях состояния, не записываются."""
    lower, upper = 0.0, 0.0
    for topic in confirmed:
        current = evidence[topic.node_id]
        state = current.state
        last_at = utc(current.last_at)
        if with_plan:
            for item in sorted(items, key=lambda i: i.on_date):
                unit = unit_map.get(item.unit_id)
                if unit is None or topic.node_id not in unit.topic_ids or item.kind == "learn":
                    continue
                if not study_date(now, config) <= item.on_date < study_date(exam_at, config):
                    continue
                from app.preparation.calendar import day_bounds

                # Консервативно используем начало будущего учебного дня.
                next_at = day_bounds(item.on_date, config)[0]
                if next_at > last_at:
                    state = sm2(state, 4, config.max_interval_days)
                    last_at = next_at
        ratio = max(0, (exam_at - last_at).total_seconds()) / (86400 * max(1, state.interval))
        sample = bins[_bin(ratio)]
        if len(sample) < MIN_BIN_OBSERVATIONS:
            return None
        a, b = wilson(sum(o.passed for o in sample), len(sample))
        lower += a
        upper += b
    denominator = max(1, len(confirmed))
    return MemoryScenario(
        lower_percent=round(lower / denominator * 100, 1),
        upper_percent=round(upper / denominator * 100, 1),
        estimated_topics=len(confirmed),
    )


def memory_forecast(
    topics, evidence, units, items, config, deadline, exam_time, *, now: datetime | None = None
) -> MemoryForecast:
    """Публикуется лишь при достаточной собственной истории сопоставимых проверок."""
    from zoneinfo import ZoneInfo

    now = now or datetime.now(UTC)
    confirmed = [
        t
        for t in topics
        if t.status in {"practiced", "mastered"}
        and t.node_id in evidence
        and evidence[t.node_id].last_at is not None
    ]
    latest = []
    for ev in evidence.values():
        candidates = [
            o for o in ev.observations if now - timedelta(days=OBSERVATION_DAYS) <= o.at <= now
        ]
        if candidates:
            latest.append(max(candidates, key=lambda o: o.at))
    observed_days = (
        (max(o.at for o in latest) - min(o.at for o in latest)).days + 1 if latest else 0
    )
    result = MemoryForecast(
        available=False,
        reason="",
        observations=len(latest),
        distinct_topics=len(latest),
        observed_days=observed_days,
        confirmed_topics=len(confirmed),
        unknown_topics=len(topics) - len(confirmed),
    )
    if deadline is None or exam_time is None:
        result.reason = "Для прогноза укажите дату и время экзамена"
        return result
    if len(latest) < MIN_DISTINCT_TOPICS or observed_days < MIN_HISTORY_DAYS:
        result.reason = (
            f"Нужны отложенные проверки по {MIN_DISTINCT_TOPICS} разным вопросам "
            f"за {MIN_HISTORY_DAYS} дней; сейчас {len(latest)} и {observed_days}"
        )
        return result
    if not confirmed:
        result.reason = "Пока нет подтверждённых самостоятельными ответами вопросов"
        return result
    exam_at = datetime.combine(deadline, exam_time, ZoneInfo(config.timezone)).astimezone(UTC)
    if exam_at <= now:
        result.reason = "Экзамен уже прошёл; доступны фактические результаты"
        return result
    bins = defaultdict(list)
    for observation in latest:
        bins[_bin(observation.ratio)].append(observation)
    arguments = (confirmed, evidence, bins, items, {u.id: u for u in units}, config, exam_at, now)
    result.with_plan = _scenario(*arguments, with_plan=True)
    result.without_study = _scenario(*arguments, with_plan=False)
    if result.with_plan is None or result.without_study is None:
        result.reason = (
            "Недостаточно сопоставимых перерывов: нужно 5 проверок в каждой используемой группе"
        )
        result.with_plan = result.without_study = None
        return result
    result.available = True
    result.reason = (
        "Диапазон сохранения уже подтверждённых знаний. Эмпирическая гипотеза; "
        "сценарий плана предполагает успешные повторения, не вероятность сдачи."
    )
    return result
