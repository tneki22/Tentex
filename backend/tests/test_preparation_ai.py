"""Регрессии контрактов ИИ: модель не обходит ограничения локального планировщика."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy import select

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.models import (
    AiSettings,
    ExamKind,
    NodeType,
    ProgramNode,
)
from app.preparation import ai
from app.preparation.ai_context import batch_program, build_context, unit_batches
from app.preparation.models import PreparationCoach, PreparationDraft, PreparationSettings
from app.preparation.schemas import PreparationAiWrite, PreparationConfig
from app.projects.errors import ProjectDomainError


@pytest.fixture
def preparation(session):
    project = make_exam_project(session)
    project.deadline = datetime.now(UTC).date() + timedelta(days=10)
    topic = make_topic_node(session, project, title="Тема")
    topic.exam_kind = ExamKind.QUESTION
    session.add(
        PreparationSettings(
            project_id=project.id,
            revision=0,
            config=PreparationConfig(daily_minutes=120).model_dump(mode="json"),
        )
    )
    session.commit()
    command = PreparationAiWrite(
        action="full",
        expected_plan_revision=0,
        expected_program_revision=project.program_revision,
        expected_settings_revision=0,
    )
    return project, topic, command


def completion(value):
    return ProviderCompletion(
        content=json.dumps(value),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=10, output_tokens=10, cost_usd=Decimal("0.0001")),
    )


def phase_payload(day, phase_id):
    return {
        "phases": [
            {
                "id": str(phase_id),
                "title": "Учиться",
                "start": str(day),
                "end": str(day + timedelta(days=3)),
                "kind": "learn",
                "origin": "ai",
            }
        ]
    }


def distribution(unit_id, day, phase_id=None, minutes=30):
    return {
        "items": [
            {
                "unit_id": str(unit_id),
                "on_date": str(day),
                "phase_id": str(phase_id) if phase_id else None,
                "minutes": minutes,
                "reason": "В свободный день",
            }
        ],
        "unassigned": [],
    }


@pytest.mark.asyncio
async def test_large_program_uses_whole_batches_then_merges_phases(
    session, ai_config, preparation, monkeypatch
):
    from app.preparation import ai_context

    project, first, command = preparation
    second = make_topic_node(session, project, title="Второй вопрос")
    monkeypatch.setattr(ai_context, "BATCH_UNITS", 1)
    day = datetime.now(UTC).date() + timedelta(days=1)
    phase_id = uuid4()
    context = build_context(session, project.id, command)
    batch_ids = [batch[0].id for batch in unit_batches(context)]
    fake = FakeTransport(
        completions=[
            *[completion(phase_payload(day, phase_id)) for _ in range(3)],
            completion(distribution(batch_ids[0], day, phase_id)),
            completion(
                {
                    "items": [],
                    "unassigned": [
                        {"unit_id": str(batch_ids[1]), "reason": "Нужен отдельный день"}
                    ],
                }
            ),
        ]
    )
    gateway = ModelGateway(session, fake)
    preview = await ai.preflight(session, gateway, project.id, command)
    assert len(preview.calls) == 5
    draft = await ai.run(session, gateway, project.id, command)
    sent = [json.loads(request["messages"][1]["content"]) for request in fake.complete_requests]
    analyzed = {unit["id"] for request in sent[:2] for unit in request["units"]}
    assert analyzed == {str(first.id), str(second.id)}
    assert len(sent[2]["phase_proposals"]) == 2
    assert draft.unassigned_reasons[str(batch_ids[1])] == "Нужен отдельный день"


@pytest.mark.asyncio
async def test_full_runs_phases_then_distribution_and_only_creates_draft(
    session, ai_config, preparation
):
    project, topic, command = preparation
    day = datetime.now(UTC).date() + timedelta(days=1)
    phase_id = uuid4()
    fake = FakeTransport(
        completions=[
            completion(phase_payload(day, phase_id)),
            completion(distribution(topic.id, day, phase_id)),
        ]
    )
    gateway = ModelGateway(session, fake)
    preview = await ai.preflight(session, gateway, project.id, command)
    assert len(preview.calls) == 2
    assert [node.id for node in preview.context] == [topic.id]
    draft = await ai.run(session, gateway, project.id, command)
    assert draft.origin == "ai" and len(draft.items) == 1
    assert session.get(PreparationDraft, draft.id)
    assert ai.planner.read_plan(session, project.id).items == []
    sent = json.loads(fake.complete_requests[1]["messages"][1]["content"])
    assert sent["phases"][0]["id"] == str(phase_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "unknown", "duplicate", "budget", "final"])
async def test_distribution_rejects_invalid_proposal(session, ai_config, preparation, case):
    project, topic, command = preparation
    command.action = "distribute"
    day = datetime.now(UTC).date() + timedelta(days=1)
    value = distribution(topic.id, day)
    if case == "missing":
        value["items"] = []
    elif case == "unknown":
        value["items"][0]["unit_id"] = str(uuid4())
    elif case == "duplicate":
        value["items"].append(value["items"][0])
    elif case == "budget":
        value["items"][0]["minutes"] = 121
    elif case == "final":
        value["items"][0]["on_date"] = str(project.deadline - timedelta(days=1))
    with pytest.raises(ProjectDomainError):
        await ai.run(
            session,
            ModelGateway(session, FakeTransport(completions=[completion(value)])),
            project.id,
            command,
        )
    assert session.scalar(select(PreparationDraft)) is None


def test_batches_preserve_all_ticket_children_and_context(session, preparation, monkeypatch):
    from app.preparation import ai_context

    project, topic, command = preparation
    ticket = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        node_type=NodeType.SECTION,
        exam_kind=ExamKind.TICKET,
        title="Билет",
        sort_order=0,
    )
    session.add(ticket)
    session.flush()
    topic.parent_id = ticket.id
    second = make_topic_node(session, project, title="Отдельный")
    subpoint = ProgramNode(
        project_id=project.id,
        parent_id=topic.id,
        node_type=NodeType.SUBPOINT,
        title="Подпункт",
        sort_order=0,
    )
    session.add(subpoint)
    session.commit()
    monkeypatch.setattr(ai_context, "BATCH_UNITS", 1)
    context = build_context(session, project.id, command)
    batches = unit_batches(context)
    assert len(batches) == 2
    assert {unit.id for batch in batches for unit in batch} == {ticket.id, second.id}
    ticket_batch = next(batch for batch in batches if batch[0].id == ticket.id)
    assert {node["id"] for node in batch_program(context, ticket_batch)} >= {
        str(ticket.id),
        str(topic.id),
        str(subpoint.id),
    }


@pytest.mark.asyncio
async def test_coach_automatic_once_and_manual_retry(session, ai_config, preparation):
    project, _, command = preparation
    command.action, command.automatic = "coach", True
    fake = FakeTransport(
        completions=[
            completion(
                {
                    "fact_key": "today",
                    "consequence": "Время ограничено.",
                    "next_step": "Откройте план.",
                }
            )
        ]
    )
    gateway = ModelGateway(session, fake)
    started = await ai.start(session, gateway, project.id, command)
    again = await ai.start(session, gateway, project.id, command)
    assert started.job_id is None and again.job_id is None
    assert fake.complete_calls == 0
    command.automatic = False
    retry = await ai.start(session, gateway, project.id, command)
    assert retry.job_id != started.job_id


@pytest.mark.asyncio
async def test_automatic_coach_never_forces_paid_confirmation(session, ai_config, preparation):
    project, _, command = preparation
    command.action, command.automatic, command.confirmed = "coach", True, True
    settings = session.get(AiSettings, 1)
    settings.confirm_cost_usd = Decimal("0")
    session.commit()
    fake = FakeTransport()
    result = await ai.start(session, ModelGateway(session, fake), project.id, command)
    assert result.job_id is None and result.coach is None
    assert result.reason and fake.complete_calls == 0
    row = session.scalar(select(PreparationCoach))
    assert row is None


@pytest.mark.asyncio
async def test_disabled_coach_keeps_local_fallback(session, preparation):
    project, _, command = preparation
    command.action, command.automatic = "coach", True
    result = await ai.start(session, ModelGateway(session, FakeTransport()), project.id, command)
    assert result.coach is None and result.reason


@pytest.mark.asyncio
async def test_stale_revision_prevents_paid_call(session, ai_config, preparation):
    project, _, command = preparation
    command.expected_program_revision += 1
    fake = FakeTransport()
    with pytest.raises(ProjectDomainError):
        await ai.start(session, ModelGateway(session, fake), project.id, command)
    assert fake.complete_calls == 0
