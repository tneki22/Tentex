from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.models import AttemptOutcome, GradeMethod
from app.preparation.evidence import MemoryState, Observation, TopicEvidence, effective_quality, sm2
from app.preparation.forecast import memory_forecast
from app.preparation.schemas import PreparationConfig, TopicProgress


def test_sm2_uses_published_intervals_and_failure_resets_repetitions() -> None:
    first = sm2(MemoryState(), 5)
    second = sm2(first, 5)
    third = sm2(second, 5)
    failed = sm2(third, 1)

    assert (first.interval, first.repetitions, first.easiness) == (1, 1, 2.6)
    assert (second.interval, second.repetitions) == (6, 2)
    assert (third.interval, third.repetitions) == (17, 3)  # ceil(6 * 2.7)
    assert (failed.interval, failed.repetitions) == (1, 0)


def test_only_memory_answers_with_resolved_grade_have_review_quality() -> None:
    memory_attempt = SimpleNamespace(answer_mode="memory")
    supported_attempt = SimpleNamespace(answer_mode="supported")
    ambiguous = SimpleNamespace(
        method=GradeMethod.KEY_TERMS, outcome=AttemptOutcome.PARTIAL, self_assessment=None
    )
    self_assessed = SimpleNamespace(
        method=GradeMethod.KEY_TERMS,
        outcome=AttemptOutcome.PARTIAL,
        self_assessment=AttemptOutcome.PASSED,
    )

    assert effective_quality(supported_attempt, self_assessed, None) is None
    assert effective_quality(memory_attempt, None, None) is None
    assert effective_quality(memory_attempt, ambiguous, None) is None
    assert effective_quality(memory_attempt, self_assessed, None) == 4
    assert effective_quality(memory_attempt, self_assessed, 0) == 0


def test_memory_forecast_needs_twenty_topics_seven_days_and_never_uses_future_observations() -> (
    None
):
    now = datetime(2026, 6, 1, 12, tzinfo=UTC)
    config = PreparationConfig(timezone="UTC")
    topics, evidence = [], {}
    for index in range(20):
        node_id = uuid4()
        at = now - timedelta(days=index % 7 + 1)
        observation = Observation(uuid4(), node_id, at, 0.8, True)
        evidence[node_id] = TopicEvidence(
            MemoryState(interval=30, repetitions=2), at, 2, 1, "passed", [observation]
        )
        topics.append(
            TopicProgress(
                node_id=node_id,
                title=str(index),
                path=[],
                unit_id=node_id,
                target_level="understanding",
                status="practiced",
                has_material=False,
                successful_attempts=2,
                required_successes=2,
                latest_outcome="passed",
                due=None,
                interval_days=6,
                reason="",
                missed_points=[],
                active_seconds=0,
            )
        )

    forecast = memory_forecast(
        topics, evidence, [], [], config, date(2026, 6, 20), time(10), now=now
    )
    assert forecast.available is True
    assert forecast.observations == 20
    assert forecast.observed_days == 7

    future_id = uuid4()
    evidence[future_id] = TopicEvidence(
        MemoryState(interval=6, repetitions=2),
        now,
        2,
        1,
        "passed",
        [Observation(uuid4(), future_id, now + timedelta(days=1), 0.8, True)],
    )
    topics.append(
        TopicProgress(
            node_id=future_id,
            title="future",
            path=[],
            unit_id=future_id,
            target_level="understanding",
            status="practiced",
            has_material=False,
            successful_attempts=2,
            required_successes=2,
            latest_outcome="passed",
            due=None,
            interval_days=6,
            reason="",
            missed_points=[],
            active_seconds=0,
        )
    )
    without_exam_time = memory_forecast(
        topics, evidence, [], [], config, date(2026, 6, 20), None, now=now
    )
    assert without_exam_time.observations == 20
    assert without_exam_time.available is False
    assert without_exam_time.reason == "Для прогноза укажите дату и время экзамена"
