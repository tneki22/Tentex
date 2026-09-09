"""Регрессии, найденные при проверке полного сценария подготовки."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from conftest import make_exam_project, make_topic_node
from sqlalchemy import select

from app.models import (
    Activity,
    ActivityKind,
    ActivityOrigin,
    Attempt,
    AttemptOutcome,
    ExaminerPersona,
    ExaminerStrictness,
    GoalPassport,
    Grade,
    GradeMethod,
)
from app.preparation import activity, planner, queue, reporting
from app.preparation.calendar import capacity_minutes
from app.preparation.evidence import project_attempts, replay, synchronize_review
from app.preparation.models import ReviewQuality
from app.preparation.schemas import (
    ApplyDraftWrite,
    DraftWrite,
    PlanItem,
    PreparationConfig,
    TimeBatchWrite,
    TimeIntervalWrite,
)


def _answer(session, project, node, at, outcome=None, mode="memory"):
    evidence = session.scalar(
        select(Activity).where(
            Activity.project_id == project.id,
            Activity.program_node_id == node.id,
            Activity.kind == ActivityKind.FREE_ANSWER,
        )
    )
    if evidence is None:
        evidence = Activity(
            project_id=project.id,
            program_node_id=node.id,
            kind=ActivityKind.FREE_ANSWER,
            evidence_strength=1,
            origin=ActivityOrigin.EXAM_CHAT,
            created_at=at.replace(tzinfo=None),
        )
        session.add(evidence)
        session.flush()
    attempt = Attempt(
        id=uuid4(),
        project_id=project.id,
        activity_id=evidence.id,
        ordinal=1,
        text="Самостоятельный ответ",
        persona=ExaminerPersona.NEUTRAL_EXAMINER,
        strictness=ExaminerStrictness.NORMAL,
        answer_mode=mode,
        created_at=at.replace(tzinfo=None),
        context_snapshot={"question": "Исходный вопрос"},
    )
    session.add(attempt)
    session.flush()
    if outcome:
        session.add(
            Grade(
                attempt_id=attempt.id,
                outcome=outcome,
                method=GradeMethod.EXACT_MATCH,
                created_at=at.replace(tzinfo=None),
                updated_at=at.replace(tzinfo=None),
                missed_points=[{"point": "Определение"}]
                if outcome != AttemptOutcome.PASSED
                else [],
            )
        )
    session.commit()
    return attempt


def test_pending_attempt_is_not_lost_and_regrading_does_not_duplicate_history(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    attempt = _answer(session, project, node, datetime.now(UTC) - timedelta(hours=1))
    pending = activity.history(session, project.id, outcome="pending")
    assert pending.total == 1 and pending.items[0].title == "Исходный вопрос"
    session.add(
        Grade(attempt_id=attempt.id, outcome=AttemptOutcome.FAILED, method=GradeMethod.EXACT_MATCH)
    )
    session.commit()
    synchronize_review(session, attempt)
    session.commit()
    synchronize_review(session, attempt)
    session.commit()
    assert activity.history(session, project.id, kind="answer").total == 1
    assert activity.history(session, project.id, outcome="pending").total == 0


def test_future_grade_and_quality_do_not_leak_into_historical_evidence(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    at = datetime.now(UTC) - timedelta(days=3)
    attempt = _answer(session, project, node, at, AttemptOutcome.PASSED)
    session.add(
        ReviewQuality(
            attempt_id=attempt.id,
            quality=0,
            updated_at=(at + timedelta(days=2)).replace(tzinfo=None),
        )
    )
    session.commit()
    historical = project_attempts(session, project.id, at + timedelta(days=1))
    assert historical[0][2] is None
    assert replay(historical, PreparationConfig())[node.id].state.repetitions == 1
    session.get(Grade, attempt.id).updated_at = (at + timedelta(days=2)).replace(tzinfo=None)
    session.commit()
    assert project_attempts(session, project.id, at + timedelta(days=1))[0][1] is None


def test_interval_crossing_study_boundary_is_split_without_increasing_readiness(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Чтение")
    at = (datetime.now(UTC) - timedelta(days=1)).replace(hour=0, minute=59, second=0, microsecond=0)
    queue.start_queue(session, project.id, now=at)
    queue.start_queue(session, project.id, now=at + timedelta(minutes=1))
    activity.add_intervals(
        session,
        project.id,
        TimeBatchWrite(
            intervals=[
                TimeIntervalWrite(
                    id=uuid4(),
                    session_id=uuid4(),
                    node_id=node.id,
                    kind="reading",
                    started_at=at,
                    ended_at=at + timedelta(minutes=2),
                )
            ]
        ),
    )
    rows = activity.history(session, project.id, kind="reading").items
    assert sorted(row.seconds for row in rows) == [60, 60]
    view = reporting.overview(session, project.id)
    assert view.summary.confirmed_topics == view.summary.passed_topics == 0
    assert sum(view.summary.seconds_by_kind.values()) == 120


def test_repeated_omission_counts_attempts_and_supported_answers_stay_separate(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    at = datetime.now(UTC) - timedelta(days=4)
    _answer(session, project, node, at, AttemptOutcome.PARTIAL)
    _answer(session, project, node, at + timedelta(days=1), AttemptOutcome.PARTIAL)
    _answer(session, project, node, at + timedelta(days=2), AttemptOutcome.PASSED, "supported")
    view = reporting.overview(session, project.id)
    assert view.topics[0].recurring_omissions == {"Определение": 2}
    assert view.summary.results_by_mode["supported"]["passed"] == 1
    assert view.summary.confirmed_topics == 0
    assert not view.memory.available


def test_early_exam_reserve_reaches_previous_study_day():
    config = PreparationConfig(
        timezone="UTC",
        daily_minutes=1440,
        final_day_ratio=1,
        sleep_start=time(2),
        sleep_end=time(3),
        exam_day_enabled=True,
    )
    # Экзамен в 01:00: резерв закрывает время с 23:00 предыдущего дня.
    assert capacity_minutes(date(2026, 6, 1), config, date(2026, 6, 2), time(1)) == 19 * 60
    assert capacity_minutes(date(2026, 6, 2), config, date(2026, 6, 2), time(1)) == 0


def test_correction_linked_to_an_attempt_never_becomes_a_delayed_memory_check(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    at = datetime.now(UTC) - timedelta(days=4)
    original = _answer(session, project, node, at, AttemptOutcome.PASSED)
    correction = _answer(session, project, node, at + timedelta(days=2), AttemptOutcome.PASSED)
    correction.parent_attempt_id = original.id
    session.commit()
    state = replay(project_attempts(session, project.id), PreparationConfig())[node.id]
    assert state.success_count == 1 and state.delayed_successes == 0
    assert state.state.interval == 1 and state.observations == []


def test_answer_interval_is_not_a_second_history_entry_for_the_saved_attempt(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    at = datetime.now(UTC) - timedelta(minutes=3)
    queue.start_queue(session, project.id, now=at)
    activity.add_intervals(
        session,
        project.id,
        TimeBatchWrite(
            intervals=[
                TimeIntervalWrite(
                    id=uuid4(),
                    session_id=uuid4(),
                    node_id=node.id,
                    kind="answer",
                    started_at=at,
                    ended_at=at + timedelta(minutes=1),
                )
            ]
        ),
    )
    attempt = _answer(session, project, node, at + timedelta(minutes=1), AttemptOutcome.PASSED)
    rows = activity.history(session, project.id, kind="answer").items
    assert len(rows) == 1 and rows[0].attempt_id == attempt.id
    assert reporting.overview(session, project.id).summary.seconds_by_kind["answer"] == 60


def test_sm2_quality_does_not_replace_the_grade_for_confirmed_knowledge(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    at = datetime.now(UTC) - timedelta(hours=1)
    attempt = _answer(session, project, node, at, AttemptOutcome.FAILED)
    session.add(ReviewQuality(attempt_id=attempt.id, quality=5))
    session.commit()
    result = replay(project_attempts(session, project.id), PreparationConfig())[node.id]
    assert result.state.repetitions == 1
    assert result.success_count == 0


def test_complete_answer_missed_day_redistribution_and_pinned_work(session):
    project = make_exam_project(session)
    project.deadline = datetime.now(UTC).date() + timedelta(days=7)
    session.add(GoalPassport(project_id=project.id, minutes_per_day=120))
    session.commit()
    first, missed, pinned = [
        make_topic_node(session, project, title=title)
        for title in ("Сдал", "Пропустил", "Закрепил")
    ]
    day = datetime.now(UTC).date() - timedelta(days=2)
    items = [
        PlanItem(id=uuid4(), unit_id=node.id, on_date=day, kind="answer", pinned=node == pinned)
        for node in (first, missed, pinned)
    ]

    def command(**kwargs):
        plan = planner.read_plan(session, project.id)
        session.rollback()
        return DraftWrite(
            expected_plan_revision=plan.revision,
            expected_program_revision=plan.program_revision,
            expected_settings_revision=plan.settings_revision,
            **kwargs,
        )

    draft = planner.create_draft(session, project.id, command(items=items))
    planner.apply_draft(session, project.id, draft.id, ApplyDraftWrite())
    _answer(session, project, first, datetime.combine(day, time(12), UTC), AttemptOutcome.FAILED)
    changed = planner.create_draft(session, project.id, command(mode="spread"))
    by_unit = {i.unit_id: i for i in changed.items if i.kind == "answer"}
    assert by_unit[first.id].on_date == by_unit[pinned.id].on_date == day
    assert by_unit[missed.id].on_date >= datetime.now(UTC).date()
    assert by_unit[missed.id].on_date < project.deadline - timedelta(days=1)
    applied = planner.apply_draft(session, project.id, changed.id, ApplyDraftWrite())
    assert items[0].id in applied.completed_ids
    assert reporting.overview(session, project.id).summary.confirmed_topics == 0
    session.rollback()
    # Явное снятие долга сохраняет закрепления и состоявшуюся неуспешную работу.
    dismissed = planner.create_draft(session, project.id, command(mode="dismiss"))
    assert any(i.id == items[2].id for i in dismissed.items)
    assert any(i.id == items[0].id for i in dismissed.items)
