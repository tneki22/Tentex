"""Задания урока от модели: «Добавить практику» и задания сборки урока (FR-L11).

Модель читает урок целиком блоками `B*` (куски — урезанными до бюджета) и
предлагает задания семи форм с местом в уроке. Сервер проверяет форму каждого
(`tasks.prepare`), невалидные отбрасывает с причиной. «Добавить практику» к
готовому уроку даёт предложение (`checkpoint.result`, применяет
`proposals.apply`); «Обычный» и «Подробный» ставят задания в собранный урок
сразу, отдельного действия журнала нет — отмена сборки уносит урок целиком.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.job_budget import KEY as BUDGET_KEY
from app.ai.job_budget import JobBudget, budget_state, spent
from app.ai.schemas import AiMessage, AiModelSelection
from app.ai.settings import AiGatewayError, resolve_model
from app.background.schemas import BackgroundJobStartRead
from app.db import project_write_transaction
from app.lessons import ai_context, tasks
from app.lessons.ai_enrich import _block_text, _brief, lesson_view
from app.lessons.ai_prompts import PracticeReply, practice_instructions
from app.lessons.ai_schemas import (
    LessonAiBuildResult,
    LessonAiBuildWrite,
    LessonEnrichOrder,
    LessonEnrichPreflightRead,
    LessonProposalOp,
    LessonProposalRead,
    LessonProposalSource,
)
from app.lessons.ai_steps import update_checkpoint
from app.lessons.service import _require_lesson, _require_lessons_project, _require_revision
from app.lessons.task_schemas import LessonPracticeOrder, LessonPracticeWrite
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Lesson,
    LessonBasis,
    LessonTopic,
)
from app.projects.errors import ProjectConflictError

ROLE = "lesson_practice"
SUBTYPE = "practice"
#: Урок целиком в одном вызове: длинные куски урезаются, пояснения — нет.
LESSON_TOKENS = 9_000
OUTPUT_TOKENS = 6_000
CALLS_SLACK = 1
#: Сколько заданий ставит сборка урока сама.
BUILD_TASKS = {"standard": 4, "detailed": 8}
#: Оценка вызова заданий при сборке — до того, как урок написан.
BUILD_CALL = (LESSON_TOKENS + 2_000, OUTPUT_TOKENS)
FORM_LABELS = {
    "single_choice": "выбор одного", "multiple_choice": "несколько верных",
    "fill_blanks": "пропуски", "numeric": "числовой ответ", "ordering": "порядок шагов",
    "matching": "сопоставление", "open_answer": "открытый ответ",
}
DIFFICULTY_LABELS = {"remember": "вспомнить", "understand": "понять", "apply": "применить"}


def _trimmed(view: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Куски урезаются поровну, чтобы урок с пояснениями влез в бюджет вызова."""
    total = sum(item["tokens"] for item in view)
    if total <= LESSON_TOKENS:
        return view
    notes = sum(item["tokens"] for item in view if item["kind"] != "source")
    sources = [item for item in view if item["kind"] == "source"]
    share = max(200, (LESSON_TOKENS - notes) // max(len(sources), 1))
    result = []
    for item in view:
        if item["kind"] == "source" and item["tokens"] > share:
            words = item["text"].split(" ")
            keep = int(len(words) * share / item["tokens"])
            item = {**item, "text": " ".join(words[:keep]) + " …(кусок урезан)"}
        result.append(item)
    return result


def practice_request(
    project_id: UUID, brief: dict[str, Any], view: list[dict[str, Any]], *, count: int,
    basis: str, template: str | None, request: str, model: AiModelSelection | None,
    **context: Any,
) -> AiTextRequest[PracticeReply]:
    shown = _trimmed(view)
    existing = [item["text"] for item in view if item["kind"] == "activity"]
    user = "\n\n".join([
        f"<brief>\n{ai_context.render_brief(brief, compact=True)}\n</brief>",
        "<lesson>\n" + "\n\n".join(_block_text(item) for item in shown) + "\n</lesson>",
        "<existing_tasks>\n" + ("\n".join(f"- {item}" for item in existing) or "нет")
        + "\n</existing_tasks>",
        f"<request>\n{request.strip() or 'Задания на понимание урока.'}\n</request>",
        f"Составь {count} заданий.",
    ])
    return AiTextRequest(
        role=ROLE,
        messages=[
            AiMessage(role="system", content=practice_instructions(template, basis, count)),
            AiMessage(role="user", content=user),
        ],
        response_model=PracticeReply,
        project_id=project_id,
        context_manifest=[
            {"kind": "stage", "stage": "practice"},
            {"kind": "brief", "sha256": hashlib.sha256(
                ai_context.render_brief(brief, compact=True).encode()).hexdigest()},
            *({"kind": "lesson_block", "id": item["label"], "block_id": item["block_id"]}
              for item in view),
        ],
        request_model_override=model,
        confirmed=True,
        parameters={"max_output_tokens": OUTPUT_TOKENS},
        **context,
    )


def _enrich_order(order: LessonPracticeOrder) -> LessonEnrichOrder:
    """Паспорт заданий собирается так же, как паспорт «Дополнить»."""
    return LessonEnrichOrder(basis=order.basis, request=order.request, model=order.model)


def _template(lesson: Lesson) -> str | None:
    return (lesson.build_meta or {}).get("template")


# --- «Добавить практику» -----------------------------------------------------------------


async def preflight(
    session: Session, project_id: UUID, lesson_id: UUID, order: LessonPracticeOrder
) -> LessonEnrichPreflightRead:
    project = _require_lessons_project(session, project_id, writable=False)
    lesson = _require_lesson(session, project_id, lesson_id)
    view = lesson_view(session, lesson)
    brief = _brief(session, project, lesson, _enrich_order(order))
    try:
        resolved = resolve_model(session, ROLE, order.model)
        estimate = await ModelGateway(session).preflight(practice_request(
            project_id, brief, view, count=order.count, basis=order.basis.value,
            template=_template(lesson), request=order.request, model=order.model,
        ))
    except AiGatewayError as error:
        return LessonEnrichPreflightRead(
            portions=1, calls=1, input_tokens=0, cost_usd=None, models_available=False,
            models_unavailable_reason=error.detail, model_label=None, price_known=False,
        )
    return LessonEnrichPreflightRead(
        portions=1, calls=1, input_tokens=estimate.estimated_input_tokens,
        cost_usd=estimate.estimated_cost_usd, models_available=True,
        models_unavailable_reason=None,
        model_label=resolved.model.display_name or resolved.model_id,
        price_known=estimate.estimated_cost_usd is not None,
    )


async def start(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonPracticeWrite
) -> BackgroundJobStartRead:
    project = _require_lessons_project(session, project_id, writable=True)
    lesson = _require_lesson(session, project_id, lesson_id)
    _require_revision(lesson, command.expected_revision)
    view = lesson_view(session, lesson)
    if not any(item["kind"] in {"note", "source"} for item in view):
        raise ProjectConflictError("В уроке пока не на чем строить задания",
                                   code="lesson_ai_empty")
    brief = _brief(session, project, lesson, _enrich_order(command))
    resolved = resolve_model(session, ROLE, command.model)
    selection = command.model or AiModelSelection(
        provider_id=resolved.provider.id, model_id=resolved.model_id
    )
    estimate = await ModelGateway(session).preflight(practice_request(
        project_id, brief, view, count=command.count, basis=command.basis.value,
        template=_template(lesson), request=command.request, model=selection,
    ))
    cost = estimate.estimated_cost_usd
    if cost is None and not command.confirm_unknown_price:
        raise ProjectConflictError(
            "Цена модели неизвестна: подтвердите запуск без оценки стоимости",
            code="ai_price_unknown", context={"model_id": resolved.model_id},
        )
    node_id = session.scalar(
        select(LessonTopic.program_node_id).where(LessonTopic.lesson_id == lesson.id)
        .order_by(LessonTopic.sort_order).limit(1)
    )
    with project_write_transaction(session, project_id):
        job = BackgroundJob(
            kind=BackgroundJobKind.AI_LESSON, project_id=project_id,
            state=BackgroundJobState.QUEUED, done=0, total=1,
            checkpoint={
                "subtype": SUBTYPE,
                "command": command.model_dump(mode="json"),
                "lesson_id": str(lesson.id),
                "program_node_id": str(node_id),
                "topic_title": lesson.title,
                "lesson_revision": lesson.revision,
                "template": _template(lesson),
                "view": view,
                "brief": brief,
                "model": selection.model_dump(mode="json"),
                "model_label": resolved.model.display_name or resolved.model_id,
                BUDGET_KEY: budget_state(
                    max_cost_usd=command.max_cost_usd or cost, max_calls=1 + CALLS_SLACK,
                    allow_unknown_price=command.confirm_unknown_price,
                ),
            },
            diagnostics=[], pause_requested=False,
        )
        session.add(job)
        session.flush()
        return BackgroundJobStartRead(job_id=job.id)


def checked_tasks(
    reply: PracticeReply, view: list[dict[str, Any]], basis: LessonBasis,
    run_id: UUID | None, dropped: list[str],
) -> list[LessonProposalOp]:
    """Задания против снимка урока: невалидная форма и чужой блок — с причиной в `dropped`."""
    by_label = {item["label"]: item for item in view}
    known = {item["source"] for item in view if item["kind"] == "source"}
    result: list[LessonProposalOp] = []
    for number, draft in enumerate(reply.tasks, start=1):
        target = by_label.get(draft.after_block) if draft.after_block else None
        if draft.after_block and target is None:
            dropped.append(f"Задание {number}: блока {draft.after_block} в уроке нет — "
                           "поставлено в конец")
        prepared = tasks.prepare(draft, known, basis)
        if isinstance(prepared, str):
            dropped.append(f"Задание {number} ({FORM_LABELS[draft.form]}): {prepared}")
            continue
        result.append(LessonProposalOp(
            id=uuid4().hex[:12], op="insert_task",
            block_id=UUID(target["block_id"]) if target else None, after_fragment_id=None,
            variant=None, body_md=None, supports=prepared.supports, basis=prepared.basis,
            collapsed=None, text=None,
            reason=f"{FORM_LABELS[draft.form].capitalize()} · "
                   f"{DIFFICULTY_LABELS[draft.difficulty]}",
            run_id=run_id, task=prepared,
        ))
    return result


def _sources(view: list[dict[str, Any]]) -> list[LessonProposalSource]:
    return [
        LessonProposalSource(
            label=item["source"], block_id=UUID(item["block_id"]),
            source_name=item["source_name"], page_from=item["page_from"],
            page_to=item["page_to"],
        )
        for item in view if item["kind"] == "source"
    ]


async def run(session: Session, gateway: ModelGateway, job_id: UUID) -> LessonProposalRead:
    job = session.get(BackgroundJob, job_id)
    assert job is not None and job.project_id is not None
    checkpoint = job.checkpoint
    command = LessonPracticeWrite.model_validate(checkpoint["command"])
    view = checkpoint["view"]
    stored = checkpoint.get("reply")
    if stored is None:
        result = await gateway.complete(practice_request(
            job.project_id, checkpoint["brief"], view, count=command.count,
            basis=command.basis.value, template=checkpoint.get("template"),
            request=command.request,
            model=AiModelSelection.model_validate(checkpoint["model"]),
            job_id=job_id, budget_context=JobBudget(session, job_id),
        ))
        stored = {**result.value.model_dump(mode="json"), "run_id": str(result.run_id)}
        update_checkpoint(session, job_id, reply=stored, done=1)
    session.expire_all()
    job = session.get(BackgroundJob, job_id)
    assert job is not None
    stored = dict(stored)
    run_id = UUID(stored.pop("run_id")) if stored.get("run_id") else None
    reply = PracticeReply.model_validate(stored)
    dropped: list[str] = []
    ops = checked_tasks(reply, view, command.basis, run_id, dropped)
    return LessonProposalRead(
        kind="practice",
        lesson_id=UUID(checkpoint["lesson_id"]),
        program_node_id=UUID(checkpoint["program_node_id"]),
        lesson_revision=int(checkpoint["lesson_revision"]),
        summary=reply.summary, basis=command.basis, ops=ops, sources=_sources(view),
        dropped=dropped, cost_usd=spent(job.checkpoint.get(BUDGET_KEY) or {}),
    )


# --- задания сборки урока ------------------------------------------------------------------


async def attach_to_build(
    session: Session, gateway: ModelGateway, job_id: UUID, result: LessonAiBuildResult,
) -> LessonAiBuildResult:
    """«Обычный» и «Подробный» ставят задания в собранный урок одним вызовом.

    Сбой вызова урок не отменяет: задания можно добавить потом «Добавить практику»,
    причина уходит в `dropped`. Повтор задачи задания второй раз не ставит.
    """
    job = session.get(BackgroundJob, job_id)
    assert job is not None and job.project_id is not None
    command = LessonAiBuildWrite.model_validate(job.checkpoint["command"])
    count = BUILD_TASKS.get(command.level)
    if count is None or result.lesson_id is None or job.checkpoint.get("tasks_state"):
        return result
    lesson = session.get(Lesson, result.lesson_id)
    if lesson is None:
        return result
    view = lesson_view(session, lesson)
    brief = job.checkpoint["brief"]
    dropped: list[str] = []
    try:
        reply = await gateway.complete(practice_request(
            job.project_id, brief, view, count=count, basis=command.basis.value,
            template=command.template, request="",
            model=AiModelSelection.model_validate(job.checkpoint["model"]),
            job_id=job_id, budget_context=JobBudget(session, job_id),
        ))
    except AiGatewayError as error:
        dropped.append(f"Задания не добавились: {error.detail} — «Добавить практику» в уроке")
        reply = None
    session.expire_all()
    with project_write_transaction(session, job.project_id):
        lesson = session.get(Lesson, result.lesson_id)
        stored_job = session.get(BackgroundJob, job_id)
        assert lesson is not None and stored_job is not None
        if reply is not None:
            ops = checked_tasks(reply.value, view, command.basis, reply.run_id, dropped)
            node_id = session.scalar(
                select(LessonTopic.program_node_id).where(LessonTopic.lesson_id == lesson.id)
                .order_by(LessonTopic.sort_order).limit(1)
            )
            placer = tasks.TaskPlacer(
                session, lesson, node_id,
                {item["source"]: UUID(item["block_id"]) for item in view
                 if item["kind"] == "source"},
                tasks.profile_of(brief), heading=True,
            )
            for op in ops:
                placer.place(op)
            placer.finish()
        cost = spent(stored_job.checkpoint.get(BUDGET_KEY) or {})
        meta = dict(lesson.build_meta or {})
        meta["dropped"] = list(meta.get("dropped") or []) + dropped
        meta["cost_usd"] = str(cost)
        if reply is not None:
            meta["ai_run_ids"] = list(meta.get("ai_run_ids") or []) + [str(reply.run_id)]
        lesson.build_meta = meta
        lesson.revision += 1
        stored_job.checkpoint = {**stored_job.checkpoint,
                                 "tasks_state": "done" if reply is not None else "failed"}
        session.flush()
    return LessonAiBuildResult(lesson_id=result.lesson_id, dropped=meta["dropped"],
                               cost_usd=Decimal(cost))
