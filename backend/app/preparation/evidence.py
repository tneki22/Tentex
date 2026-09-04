"""SM-2 и прогресс: факты попыток не смешиваются с длительностью чтения."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attempt, Grade, GradeMethod
from app.preparation.calendar import naive_utc, study_date, utc
from app.preparation.data import get_settings
from app.preparation.models import ReviewQuality, ReviewState
from app.preparation.schemas import PreparationConfig

DEFAULT_QUALITY = {"passed": 4, "partial": 2, "failed": 1}
TARGET_SUCCESSES = {"awareness": 1, "understanding": 2, "application": 3, "mastery": 4}
INITIAL_EASINESS = 2.5
MIN_EASINESS = 1.3


@dataclass
class MemoryState:
    """Чистое состояние алгоритма для проверок и безопасной симуляции прогноза."""

    easiness: float = INITIAL_EASINESS
    interval: int = 0
    repetitions: int = 0


def sm2(state: MemoryState, quality: int, maximum: int = 365) -> MemoryState:
    """SM-2: интервалы 1, 6, ceil(I*EF), минимум EF=1.3; провал сбрасывает серию."""
    if not 0 <= quality <= 5:
        raise ValueError("Качество должно быть от 0 до 5")
    easiness = max(
        MIN_EASINESS, state.easiness + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    )
    repetitions = state.repetitions + 1 if quality >= 3 else 0
    if quality < 3 or state.repetitions == 0:
        interval = 1
    elif state.repetitions == 1:
        interval = 6
    else:
        interval = math.ceil(state.interval * state.easiness)
    return MemoryState(easiness, min(maximum, interval), repetitions)


def effective_quality(attempt: Attempt, grade: Grade | None, override: int | None) -> int | None:
    """Неоднозначная локальная проверка требует самооценки, опора не подтверждает память."""
    if grade is None or attempt.answer_mode != "memory":
        return None
    if override is not None:
        return override
    outcome = grade.self_assessment or grade.outcome
    if (
        grade.method == GradeMethod.KEY_TERMS
        and outcome.value != "passed"
        and grade.self_assessment is None
    ):
        return None
    return DEFAULT_QUALITY.get(outcome.value)


@dataclass
class Observation:
    """Снимок до проверки позволяет оценивать отложенное воспроизведение без утечки будущего."""

    attempt_id: UUID
    node_id: UUID
    at: datetime
    ratio: float
    passed: bool


@dataclass
class TopicEvidence:
    """Единая проекция используется историей, статусом, SM-2 и прогнозом."""

    state: MemoryState
    last_at: datetime | None
    success_count: int
    delayed_successes: int
    latest_outcome: str | None
    observations: list[Observation]


def project_attempts(session: Session, project_id: UUID, before: datetime | None = None):
    """Стабильный порядок нужен для воспроизводимой отмены качества и графиков."""
    query = (
        select(Attempt, Grade, ReviewQuality.quality)
        .outerjoin(Grade, Grade.attempt_id == Attempt.id)
        .outerjoin(ReviewQuality, ReviewQuality.attempt_id == Attempt.id)
        .where(Attempt.project_id == project_id)
    )
    cutoff = naive_utc(before or datetime.now(UTC))
    query = query.where(Attempt.created_at <= cutoff)
    rows = list(session.execute(query.order_by(Attempt.created_at, Attempt.id)))
    # Поздняя проверка не появляется на графике в момент ещё не проверенного ответа.
    return [
        (attempt, grade if grade is None or grade.updated_at <= cutoff else None, quality)
        for attempt, grade, quality in rows
    ]


def replay(rows, config: PreparationConfig) -> dict[UUID, TopicEvidence]:
    """Перепроверки и исправления в один день не множат интервалы памяти."""
    result = {}
    for attempt, grade, override in rows:
        evidence = result.setdefault(
            attempt.program_node_id, TopicEvidence(MemoryState(), None, 0, 0, None, [])
        )
        if grade is not None:
            evidence.latest_outcome = grade.outcome.value
        quality = effective_quality(attempt, grade, override)
        if quality is None:
            continue
        at = utc(attempt.created_at)
        if quality >= 3:
            evidence.success_count += 1
        previous = evidence.last_at
        delayed = previous is not None and (at - utc(previous)).total_seconds() >= 86400
        if delayed and evidence.state.repetitions > 0 and grade.self_assessment is None:
            ratio = (at - utc(previous)).total_seconds() / (86400 * evidence.state.interval)
            evidence.observations.append(
                Observation(
                    attempt.id, attempt.program_node_id, at, ratio, grade.outcome.value == "passed"
                )
            )
            evidence.delayed_successes += int(quality >= 3)
        # Повторная тренировка сегодня остаётся фактом, но не превращает 1 день в 6.
        same_day = previous is not None and study_date(at, config) == study_date(previous, config)
        if same_day:
            continue
        evidence.state = sm2(evidence.state, quality, config.max_interval_days)
        evidence.last_at = at
    return result


def synchronize_review(session: Session, attempt: Attempt) -> None:
    """Вызывается в транзакции оценки; состояние восстановимо из Attempt/Grade/качества."""
    config = get_settings(session, attempt.project_id).config
    rows = [
        r
        for r in project_attempts(session, attempt.project_id)
        if r[0].program_node_id == attempt.program_node_id
    ]
    evidence = replay(rows, config).get(attempt.program_node_id)
    if evidence is None or evidence.last_at is None:
        return
    key = (attempt.project_id, attempt.program_node_id)
    row = session.get(ReviewState, key)
    if row is None:
        row = ReviewState(project_id=key[0], node_id=key[1])
        session.add(row)
    row.easiness = evidence.state.easiness
    row.interval_days = evidence.state.interval
    row.repetitions = evidence.state.repetitions
    row.last_at = naive_utc(evidence.last_at)
    row.due = study_date(evidence.last_at, config) + timedelta(days=evidence.state.interval)
    row.successful_count = evidence.success_count
    row.delayed_successes = evidence.delayed_successes
