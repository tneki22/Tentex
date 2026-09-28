"""Массовая сборка уроков с ИИ: «Черновик» по списку тем одной задачей (FR-L7).

Темы идут в порядке программы, и паспорт каждой собирается перед её вызовом, а не
при постановке: понятия уроков, собранных этой же задачей раньше, попадают в
«уже известно» следующей темы. Каждая тема — свой вызов, свой урок и своя запись
`lesson_create`; готовые темы лежат в `checkpoint.topics`, поэтому продолжение
после сбоя или исчерпанного предела не пересобирает их. Плана нет — результат
только черновики.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.job_budget import JobBudget, spent
from app.ai.schemas import AiModelSelection
from app.ai.settings import AiGatewayError, resolve_model
from app.background.schemas import BackgroundJobStartRead
from app.lessons import ai_build
from app.lessons.ai_schemas import (
    LessonAiBuildWrite,
    LessonAiBulkOrder,
    LessonAiBulkPreflightRead,
    LessonAiBulkResult,
    LessonAiBulkTopicRead,
    LessonAiBulkTopicResult,
    LessonAiBulkWrite,
)
from app.lessons.ai_steps import update_checkpoint
from app.lessons.ai_writer import save_lesson
from app.lessons.service import _load_program, _require_lessons_project, _require_study_node
from app.models import BackgroundJob, LessonBasis, ProgramNode, Project
from app.projects.errors import ProjectConflictError, ProjectDomainError

SUBTYPE = "bulk"
CALLS_SLACK = 2
NO_MATERIAL = "по теме не нашлось материала, а основа — только материалы"


def _ordered(session: Session, project_id: UUID, node_ids: list[UUID]) -> list[ProgramNode]:
    """Темы списка в порядке программы — так «уже известно» копится по порядку."""
    if len(set(node_ids)) != len(node_ids):
        raise ProjectDomainError("Тема встречается в списке дважды", status=422,
                                 code="lesson_bulk_duplicate")
    nodes = [_require_study_node(session, project_id, node_id) for node_id in node_ids]
    program = _load_program(session, project_id)
    return sorted(nodes, key=lambda node: program.index_of(node.id))


def _topic_order(order: LessonAiBulkOrder, node_id: UUID, model: AiModelSelection | None
                 ) -> LessonAiBuildWrite:
    return LessonAiBuildWrite(
        program_node_id=node_id, template=order.template, level="draft", basis=order.basis,
        model=model,
    )


async def preflight(
    session: Session, project_id: UUID, order: LessonAiBulkOrder
) -> LessonAiBulkPreflightRead:
    """Куски каждой темы и общая оценка черновиков — без вызова модели."""
    project = _require_lessons_project(session, project_id, writable=False)
    nodes = _ordered(session, project_id, order.program_node_ids)
    topics: list[LessonAiBulkTopicRead] = []
    requests = []
    for node in nodes:
        topic = _topic_order(order, node.id, order.model)
        prepared = await ai_build._prepare(session, project, node, topic)
        items = prepared.found.candidates
        topics.append(LessonAiBulkTopicRead(
            program_node_id=node.id, title=node.title, candidates=len(items),
            sources_available=bool(items),
        ))
        if items or order.basis != LessonBasis.SOURCES:
            requests.append(ai_build._draft_request(project_id, prepared.brief, items,
                                                    order.model))
    try:
        resolved = resolve_model(session, ai_build.ROLE, order.model)
        gateway = ModelGateway(session)
        costs = [(await gateway.preflight(request)).estimated_cost_usd for request in requests]
    except AiGatewayError as error:
        return LessonAiBulkPreflightRead(
            topics=topics, calls=len(requests), cost_usd=None, models_available=False,
            models_unavailable_reason=error.detail, model_label=None, price_known=False,
        )
    cost = None if any(item is None for item in costs) else sum(costs, Decimal(0))
    return LessonAiBulkPreflightRead(
        topics=topics, calls=len(requests), cost_usd=cost, models_available=True,
        models_unavailable_reason=None,
        model_label=resolved.model.display_name or resolved.model_id,
        price_known=cost is not None,
    )


async def start(
    session: Session, project_id: UUID, command: LessonAiBulkWrite
) -> BackgroundJobStartRead:
    _require_lessons_project(session, project_id, writable=True)
    estimate = await preflight(session, project_id, command)
    if not estimate.models_available:
        raise ProjectConflictError(
            estimate.models_unavailable_reason or "Внешние модели недоступны",
            code="ai_disabled",
        )
    if estimate.calls == 0:
        raise ProjectConflictError(
            "Ни по одной теме не нашлось материала — выберите основу со знаниями модели",
            code="lesson_ai_no_material",
        )
    resolved = resolve_model(session, ai_build.ROLE, command.model)
    if estimate.cost_usd is None and not command.confirm_unknown_price:
        raise ProjectConflictError(
            "Цена модели неизвестна: подтвердите запуск без оценки стоимости",
            code="ai_price_unknown", context={"model_id": resolved.model_id},
        )
    selection = command.model or AiModelSelection(
        provider_id=resolved.provider.id, model_id=resolved.model_id
    )
    topics = estimate.topics
    return ai_build._add_job(
        session, project_id, subtype=SUBTYPE, total=len(topics),
        checkpoint={
            "command": command.model_dump(mode="json"),
            "node_ids": [str(item.program_node_id) for item in topics],
            "topic_title": f"{len(topics)} тем",
            "topics": {},
            "model": selection.model_dump(mode="json"),
            "model_label": resolved.model.display_name or resolved.model_id,
        },
        max_cost=command.max_cost_usd or estimate.cost_usd,
        max_calls=len(topics) + CALLS_SLACK,
        allow_unknown_price=command.confirm_unknown_price,
    )


def _result(job: BackgroundJob) -> LessonAiBulkResult:
    topics: dict[str, dict[str, Any]] = job.checkpoint.get("topics") or {}
    return LessonAiBulkResult(
        lessons=[
            LessonAiBulkTopicResult(
                program_node_id=UUID(node_id), topic_title=item["title"],
                lesson_id=UUID(item["lesson_id"]) if item.get("lesson_id") else None,
                skipped=item.get("skipped"), dropped=list(item.get("dropped") or []),
            )
            for node_id in job.checkpoint["node_ids"]
            if (item := topics.get(node_id)) is not None
        ],
        cost_usd=spent(job.checkpoint.get("budget") or {}),
    )


async def run(session: Session, gateway: ModelGateway, job_id: UUID) -> LessonAiBulkResult:
    job = session.get(BackgroundJob, job_id)
    assert job is not None and job.project_id is not None
    project_id = job.project_id
    command = LessonAiBulkWrite.model_validate(job.checkpoint["command"])
    model = AiModelSelection.model_validate(job.checkpoint["model"])
    for raw_id in job.checkpoint["node_ids"]:
        session.expire_all()
        job = session.get(BackgroundJob, job_id)
        assert job is not None
        topics: dict[str, dict[str, Any]] = dict(job.checkpoint.get("topics") or {})
        if raw_id in topics:
            continue
        if job.pause_requested:
            break
        project = session.get(Project, project_id)
        node = session.get(ProgramNode, UUID(raw_id))
        if project is None or node is None or node.project_id != project_id:
            topics[raw_id] = {"title": "тема удалена", "skipped": "темы больше нет в программе"}
            update_checkpoint(session, job_id, topics=topics, done=len(topics))
            continue
        order = _topic_order(command, node.id, model)
        prepared = await ai_build._prepare(session, project, node, order)
        items = prepared.found.candidates
        if command.basis == LessonBasis.SOURCES and not items:
            topics[raw_id] = {"title": node.title, "skipped": NO_MATERIAL}
            update_checkpoint(session, job_id, topics=topics, done=len(topics))
            continue
        result = await gateway.complete(ai_build._draft_request(
            project_id, prepared.brief, items, model,
            job_id=job_id, budget_context=JobBudget(session, job_id),
        ))
        session.expire_all()
        job = session.get(BackgroundJob, job_id)
        assert job is not None
        saved = save_lesson(
            session, job, ai_build.draft_of(result), model_id=result.actual_model_id,
            cost=result.usage.actual_cost_usd, command=order, candidates=items,
        )
        topics = dict(session.get(BackgroundJob, job_id).checkpoint.get("topics") or {})
        topics[raw_id] = {"title": node.title, "lesson_id": str(saved.lesson_id),
                          "dropped": saved.dropped}
        update_checkpoint(session, job_id, topics=topics, done=len(topics))
    session.expire_all()
    job = session.get(BackgroundJob, job_id)
    assert job is not None
    return _result(job)
