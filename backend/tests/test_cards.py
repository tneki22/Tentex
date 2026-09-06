"""Карточки не планируют даты и сохраняют каждое действие сеанса."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cards import service
from app.cards.router import router
from app.cards.schemas import (
    CardBulkWrite,
    CardCreate,
    CardSessionCreate,
    CardSourceWrite,
    CardUpdate,
    SessionDeferWrite,
    SessionRetryWrite,
    SessionReviewWrite,
)
from app.db import get_session
from app.models import (
    Activity,
    Attempt,
    Card,
    ExamKind,
    Grade,
    NodeType,
    ProgramNode,
    ProjectStatus,
    utc_now,
)
from app.preparation.calendar import study_date
from app.preparation.data import get_settings
from app.preparation.models import PreparationPlan, StudyActivity
from app.preparation.schemas import PlanItem
from app.projects.errors import ProjectConflictError, ProjectDomainError


def _create(session, project, node=None, *, front="Вопрос", source=None):
    return service.create_card(
        session,
        project.id,
        CardCreate(
            program_node_id=node.id if node else None,
            front=front,
            back="Ответ",
            source=source or CardSourceWrite(),
        ),
    )


def test_crud_search_order_revision_and_soft_delete(session):
    project = make_exam_project(session)
    project_id = project.id
    first = make_topic_node(session, project, title="Первый")
    second = make_topic_node(session, project, title="Второй")
    linked = _create(session, project, second, front="Транзакция")
    unlinked = _create(session, project, front="Личная заметка")

    found = service.list_cards(session, project_id, query="второй")
    assert [item.id for item in found.items] == [linked.id]
    ordered = service.list_cards(session, project_id)
    assert ordered.items[-1].id == unlinked.id
    session.rollback()

    changed = service.update_card(
        session,
        project_id,
        linked.id,
        CardUpdate(expected_revision=linked.revision, front="Новый вопрос"),
    )
    assert changed.front == "Новый вопрос" and changed.revision == 2
    with pytest.raises(ProjectConflictError) as stale:
        service.update_card(
            session,
            project_id,
            linked.id,
            CardUpdate(expected_revision=1, front="Потерянная правка"),
        )
    assert stale.value.code == "stale_card_revision"

    deleted = service.bulk_cards(
        session,
        project_id,
        CardBulkWrite(
            action="delete",
            items=[{"id": changed.id, "expected_revision": changed.revision}],
        ),
    )
    removed = next(item for item in deleted.items if item.id == changed.id)
    assert removed.deleted_at is not None
    session.rollback()
    restored = service.bulk_cards(
        session,
        project_id,
        CardBulkWrite(
            action="restore",
            items=[{"id": removed.id, "expected_revision": removed.revision}],
        ),
    )
    assert next(item for item in restored.items if item.id == removed.id).deleted_at is None
    assert first.id != second.id


def test_project_isolation_archived_write_and_fragment_snapshot(session):
    project = make_exam_project(session)
    other = make_exam_project(session)
    project_id = project.id
    other_id = other.id
    node = make_topic_node(session, project, title="Индексы")
    node_id = node.id
    material = make_material(session, "cafe")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Точный фрагмент"]
    )
    fragment_id = page.fragment_ids[0]
    prefill = service.fragment_prefill(session, project_id, fragment_id)
    assert prefill.back == "Точный фрагмент"
    with pytest.raises(ProjectDomainError) as inaccessible:
        service.fragment_prefill(session, other_id, fragment_id)
    assert inaccessible.value.code == "card_fragment_not_found"
    session.rollback()

    card = service.create_card(
        session,
        project_id,
        CardCreate(
            program_node_id=node_id,
            front="Вопрос",
            back="Ответ",
            source=CardSourceWrite(kind="fragment", fragment_id=fragment_id),
        ),
    )
    assert card.source.text_snapshot == "Точный фрагмент"
    project.status = ProjectStatus.ARCHIVED
    session.commit()
    with pytest.raises(ProjectDomainError) as read_only:
        service.create_card(
            session,
            project_id,
            CardCreate(program_node_id=node_id, front="Вопрос", back="Ответ"),
        )
    assert read_only.value.code == "project_read_only"


def test_overview_uses_only_calendar_reviews_and_reports_partial_coverage(session):
    project = make_exam_project(session)
    covered = make_topic_node(session, project, title="Покрыт")
    missing = make_topic_node(session, project, title="Без карточки")
    _create(session, project, covered)
    today = study_date(datetime.now(UTC), get_settings(session, project.id).config)
    items = [
        PlanItem(id=uuid4(), unit_id=node.id, on_date=today, kind="review", order=index)
        for index, node in enumerate((covered, missing))
    ]
    session.add(
        PreparationPlan(
            project_id=project.id,
            revision=1,
            program_revision=project.program_revision,
            settings_revision=0,
            phases=[],
            items=[item.model_dump(mode="json") for item in items],
        )
    )
    session.commit()

    result = service.overview(session, project.id, 7)
    assert [item.unit.id for item in result.today_units] == [covered.id, missing.id]
    assert result.covered_unit_count == 1
    assert result.estimated_minutes == 1


def test_session_review_is_idempotent_defer_has_no_grade_and_plan_is_unchanged(session):
    project = make_exam_project(session)
    project_id = project.id
    node = make_topic_node(session, project, title="ACID")
    first = _create(session, project, node, front="A")
    second = _create(session, project, node, front="B")
    created = service.create_session(
        session,
        project_id,
        CardSessionCreate(scope="all", pace="fast", limit_minutes=5),
    )
    original_plan = session.get(PreparationPlan, project_id)
    session.rollback()
    event_id = uuid4()
    reviewed = service.review_card(
        session,
        project_id,
        created.id,
        first.id,
        SessionReviewWrite(
            id=event_id,
            expected_revision=created.revision,
            confidence=2,
            active_seconds=30,
        ),
    )
    assert reviewed.position == 1 and reviewed.queue[0].confidence == 2
    assert session.scalar(select(Grade.confidence).where(Grade.attempt_id == event_id)) == 2
    session.rollback()
    duplicate = service.review_card(
        session,
        project_id,
        created.id,
        first.id,
        SessionReviewWrite(
            id=event_id,
            expected_revision=created.revision,
            confidence=2,
            active_seconds=30,
        ),
    )
    assert duplicate.position == 1
    assert session.scalar(select(Attempt).where(Attempt.id == event_id)) is not None
    session.rollback()

    deferred_id = uuid4()
    deferred = service.defer_card(
        session,
        project_id,
        reviewed.id,
        second.id,
        SessionDeferWrite(
            id=deferred_id,
            expected_revision=reviewed.revision,
            active_seconds=10,
        ),
    )
    assert deferred.queue[1].state == "deferred"
    assert session.get(Attempt, deferred_id) is not None
    assert session.get(Grade, deferred_id) is None
    assert session.get(PreparationPlan, project_id) is original_plan
    session.rollback()

    retry = service.retry_session(
        session,
        project_id,
        deferred.id,
        SessionRetryWrite(expected_revision=deferred.revision),
    )
    assert retry.position == 0
    assert [item.card_id for item in retry.queue] == [first.id, second.id]
    assert all(item.state == "pending" for item in retry.queue)
    session.rollback()

    analytics = service.overview(session, project_id, 7).analytics
    assert analytics.observation_count == 1
    assert analytics.distribution[1].count == 1
    assert analytics.hard_card_count == 1
    assert session.scalar(select(Activity.program_node_id).join(Card)) == node.id


def test_active_session_requires_explicit_replacement(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    _create(session, project, node)
    service.create_session(session, project.id, CardSessionCreate(scope="all"))
    with pytest.raises(ProjectConflictError) as conflict:
        service.create_session(session, project.id, CardSessionCreate(scope="all"))
    assert conflict.value.code == "active_card_session_exists"


def test_ticket_opening_marks_all_topics_once(session):
    project = make_exam_project(session)
    now = utc_now()
    ticket = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        node_type=NodeType.SECTION,
        exam_kind=ExamKind.TICKET,
        sort_order=0,
        title="Билет 1",
        is_in_current_program=True,
        needs_material=False,
        is_archived=False,
        created_at=now,
        updated_at=now,
    )
    topics = [
        ProgramNode(
            id=uuid4(),
            project_id=project.id,
            parent_id=ticket.id,
            node_type=NodeType.TOPIC,
            sort_order=index,
            title=title,
            is_in_current_program=True,
            needs_material=False,
            is_archived=False,
            created_at=now,
            updated_at=now,
        )
        for index, title in enumerate(("Тема A", "Тема B"))
    ]
    session.add_all([ticket, *topics])
    session.commit()
    _create(session, project, ticket)
    card_session = service.create_session(
        session, project.id, CardSessionCreate(scope="all")
    )
    project_id = project.id
    session_id = card_session.id
    revision = card_session.revision
    session.rollback()

    service.open_current_unit(session, project_id, session_id, revision)
    session.rollback()
    service.open_current_unit(session, project_id, session_id, revision)
    opened = list(
        session.scalars(
            select(StudyActivity).where(
                StudyActivity.project_id == project_id,
                StudyActivity.kind == "view",
            )
        )
    )
    assert {item.node_id for item in opened} == {item.id for item in topics}
    assert len(opened) == 2


def test_card_http_crud_uses_generated_contract(session):
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Нормальные формы")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    created = client.post(
        f"/api/projects/{project.id}/cards",
        json={
            "program_node_id": str(node.id),
            "front": "Что такое 3НФ?",
            "back": "Нормальная форма без транзитивных зависимостей.",
            "source": {"kind": "none"},
            "state": "active",
        },
    )
    assert created.status_code == 201
    card = created.json()
    session.rollback()

    listed = client.get(
        f"/api/projects/{project.id}/cards", params={"query": "транзитивных"}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [card["id"]]
    session.rollback()

    changed = client.patch(
        f"/api/projects/{project.id}/cards/{card['id']}",
        json={"expected_revision": card["revision"], "hint": "Зависимости"},
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2
