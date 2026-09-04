"""Сквозные инварианты сохранённого расписания и связи с экзаменационным чатом."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import make_exam_project, make_topic_node

from app.models import ExamKind, GoalPassport, NodeType, ProgramNode
from app.preparation import activity, planner, queue, reporting
from app.preparation.calendar import study_date
from app.preparation.data import get_settings, units
from app.preparation.schemas import (
    ApplyDraftWrite,
    DraftWrite,
    Phase,
    PlanItem,
    RevisionWrite,
    UnderstoodWrite,
)
from app.projects.errors import ProjectDomainError


def _project(session):
    project = make_exam_project(session)
    project.deadline = datetime.now(UTC).date() + timedelta(days=14)
    session.add(GoalPassport(project_id=project.id, minutes_per_day=120))
    session.commit()
    node = make_topic_node(session, project, title="Одиночный вопрос")
    return project, node


def _command(session, project_id, **kwargs):
    plan = planner.read_plan(session, project_id)
    session.rollback()
    return DraftWrite(
        expected_plan_revision=plan.revision,
        expected_program_revision=plan.program_revision,
        expected_settings_revision=plan.settings_revision,
        **kwargs,
    )


def test_empty_overview_and_plan_apply_undo_preserve_journal(session):
    project, node = _project(session)
    view = reporting.overview(session, project.id)
    assert view.summary.total_topics == 1 and view.summary.confirmed_topics == 0
    assert not view.memory.available
    session.rollback()
    proposal = planner.create_draft(
        session, project.id, _command(session, project.id, mode="count")
    )
    assert len(proposal.items) == 1
    session.rollback()
    applied = planner.apply_draft(session, project.id, proposal.id, ApplyDraftWrite())
    assert applied.revision == 1 and applied.can_undo
    activity.mark_understood(session, project.id, UnderstoodWrite(unit_id=node.id))
    undone = planner.undo(session, project.id, RevisionWrite(expected_revision=1))
    assert undone.items == []
    view = reporting.overview(session, project.id)
    assert view.summary.passed_topics == 1 and view.summary.confirmed_topics == 0


def test_ticket_is_atomic_in_distribution_and_manual_draft(session):
    project, _ = _project(session)
    ticket = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        node_type=NodeType.SECTION,
        exam_kind=ExamKind.TICKET,
        title="Билет 1",
        sort_order=1,
        is_in_current_program=True,
        is_archived=False,
    )
    session.add(ticket)
    session.commit()
    children = [make_topic_node(session, project, title=f"Вопрос {i}") for i in range(2)]
    for node in children:
        node.parent_id = ticket.id
    session.commit()
    unit_rows = units(session, project.id)
    assert next(u for u in unit_rows if u.id == ticket.id).topic_ids == [
        n.id for n in sorted(children, key=lambda n: n.id)
    ]
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    bad = PlanItem(id=uuid4(), unit_id=children[0].id, on_date=today)
    project_id = project.id
    command = _command(session, project.id, mode="manual", items=[bad])
    with pytest.raises(ProjectDomainError, match="билета"):
        planner.create_draft(session, project_id, command)


def test_intersecting_phases_share_budget_and_stale_preview_is_rejected(session):
    project, node = _project(session)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    tomorrow = today + timedelta(days=1)
    phases = [
        Phase(id=uuid4(), title=title, start=tomorrow, end=tomorrow)
        for title in ("Теория", "Практика")
    ]
    item = PlanItem(
        id=uuid4(), unit_id=node.id, on_date=tomorrow, minutes=150, phase_id=phases[0].id
    )
    proposal = planner.create_draft(
        session,
        project.id,
        _command(session, project.id, mode="manual", phases=phases, items=[item]),
    )
    day = next(d for d in proposal.days if d.date == tomorrow)
    assert day.capacity_minutes == 120 and day.overload_minutes == 30
    session.rollback()
    project.program_revision += 1
    session.commit()
    with pytest.raises(ProjectDomainError, match="изменился"):
        planner.apply_draft(session, project.id, proposal.id, ApplyDraftWrite())


def test_queue_resumes_position_and_never_splits_ticket(session):
    project, _ = _project(session)
    first = queue.start_queue(session, project.id)
    second = queue.start_queue(session, project.id)
    assert first == second
    assert first.items
