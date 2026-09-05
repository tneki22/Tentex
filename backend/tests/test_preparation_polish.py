"""Регрессии кнопок экрана: план, долг, начало дня и честные факты графиков."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import make_topic_node
from sqlalchemy import select
from test_preparation_plan import _command, _project

from app.models import GoalPassport
from app.preparation import planner, progress, queue, reporting
from app.preparation.calendar import study_date
from app.preparation.data import get_settings
from app.preparation.models import StudyActivity
from app.preparation.schemas import ApplyDraftWrite, Phase, PlanItem, RevisionWrite


def _apply(session, project_id, **values):
    """Тот же путь draft → apply, который вызывают кнопки в браузере."""
    draft = planner.create_draft(session, project_id, _command(session, project_id, **values))
    session.rollback()
    return planner.apply_draft(session, project_id, draft.id, ApplyDraftWrite(apply_phases=False))


def test_count_without_blocks_applies_and_repeated_distribution_preserves_dates(session):
    project, _ = _project(session)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    first = _apply(session, project.id, mode="count")
    assert first.items and not first.phases
    assert all(today < i.on_date < project.deadline for i in first.items)
    other = make_topic_node(session, project, title="Новый вопрос")
    second = _apply(session, project.id, mode="count")
    assert first.items[0] in second.items
    added = next(i for i in second.items if i.unit_id == other.id)
    assert added.on_date not in {i.on_date for i in first.items}


@pytest.mark.parametrize("days,allowed", [(2, True), (4, True), (5, False), (9, False)])
def test_short_deadline_keeps_the_last_day_available(days, allowed):
    today = datetime.now(UTC).date()
    exam = today + timedelta(days=days)
    assert planner.allocation_date(exam - timedelta(days=1), today, exam) == allowed
    assert not planner.allocation_date(exam, today, exam)
    assert not planner.allocation_date(today, today, exam)


@pytest.mark.parametrize("mode", ["dismiss", "catch_up"])
def test_debt_action_changes_plan_and_undo_preserves_journal(session, mode):
    project, node = _project(session)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    old = PlanItem(id=uuid4(), unit_id=node.id, on_date=today - timedelta(days=1), pinned=True)
    initial = _apply(session, project.id, mode="manual", items=[old])
    progress.record_opening(session, project.id, node.id)
    changed = _apply(
        session, project.id, mode=mode, include_pinned=True, start=today + timedelta(days=2)
    )
    if mode == "dismiss":
        assert changed.items == []
    else:
        assert len(changed.items) == 1 and changed.items[0].on_date >= today + timedelta(days=2)
    restored = planner.undo(session, project.id, RevisionWrite(expected_revision=changed.revision))
    assert restored.items == initial.items
    assert session.scalar(select(StudyActivity.id).where(StudyActivity.kind == "view"))


def test_dismiss_does_not_require_a_daily_budget(session):
    project, node = _project(session)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    _apply(
        session,
        project.id,
        mode="manual",
        items=[PlanItem(id=uuid4(), unit_id=node.id, on_date=today - timedelta(days=1))],
    )
    passport = session.get(GoalPassport, project.id)
    passport.minutes_per_day = None
    session.commit()
    assert not _apply(session, project.id, mode="dismiss").items


def test_opening_completes_only_its_day_and_both_kinds_without_starting_timer(session):
    project, node = _project(session)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    items = [
        PlanItem(id=uuid4(), unit_id=node.id, on_date=day, kind=kind)
        for day, kind in [
            (today - timedelta(days=1), "learn"),
            (today, "learn"),
            (today, "review"),
            (today + timedelta(days=1), "review"),
        ]
    ]
    _apply(session, project.id, mode="manual", items=items)
    progress.record_opening(session, project.id, node.id)
    progress.record_opening(session, project.id, node.id)
    view = reporting.overview(session, project.id)
    assert set(view.plan.completed_ids) == {items[1].id, items[2].id}
    assert not view.day_started and view.summary.today_seconds == 0
    day = next(d for d in view.days if d.date == today)
    assert day.opened_new_count == day.opened_review_count == day.passed_count == 1


def test_start_day_is_idempotent_and_queue_contains_only_todays_plan(session):
    project, node = _project(session)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    _apply(
        session,
        project.id,
        mode="manual",
        items=[PlanItem(id=uuid4(), unit_id=node.id, on_date=today)],
    )
    first = queue.start_queue(session, project.id)
    second = queue.start_queue(session, project.id)
    assert first == second and first.started and len(first.items) == 1
    view = reporting.overview(session, project.id)
    assert view.day_started and view.summary.today_seconds == 0
    assert len([m for m in view.milestones if m.key == "start"]) == 1


def test_block_replacement_does_not_move_legacy_assignments(session):
    project, node = _project(session)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    phase = Phase(id=uuid4(), title="Старый блок", start=today, end=today)
    item = PlanItem(id=uuid4(), unit_id=node.id, on_date=today, phase_id=phase.id)
    _apply(session, project.id, mode="manual", items=[item])
    draft = planner.create_draft(
        session,
        project.id,
        _command(
            session,
            project.id,
            mode="manual",
            phases=[Phase(id=uuid4(), title="Отдых", kind="rest", start=today, end=today)],
        ),
    )
    changed = planner.apply_draft(session, project.id, draft.id, ApplyDraftWrite())
    assert changed.items == [item]
    view = reporting.overview(session, project.id)
    assert next(d for d in view.days if d.date == today).capacity_minutes == 0
    budget = view.budget
    assert (
        budget.base_minutes
        - budget.rest_minutes
        - budget.exception_minutes
        - budget.used_minutes
        - budget.unavailable_minutes
        == budget.remaining_minutes
    )
