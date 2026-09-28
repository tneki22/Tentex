"""«Собрать урок с ИИ»: оценка перед запуском, фоновые задачи и диспетчер сборки.

Этапы A–B (область и кандидаты) идут без модели при постановке задачи и
замораживаются в `checkpoint` вместе с паспортом урока: все вызовы одной сборки
видят одно и то же. Модель выбирает куски только метками из этого списка,
поэтому ссылка урока всегда лежит внутри переданного ей контекста (FR-L10).

Три пути: «Черновик» — один вызов (`build`); «Обычный»/«Подробный» — задача
плана (`plan`, предложение в редактор плана) и сборка по правленому плану
(`build` с планом), либо сразу `build` без показа плана. Запись урока —
`ai_writer`, план, шаги и рецензент — `ai_steps`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.job_budget import KEY as BUDGET_KEY
from app.ai.job_budget import JobBudget, budget_state
from app.ai.schemas import AiMessage, AiModelSelection
from app.ai.settings import AiGatewayError, ResolvedModel, resolve_model
from app.background.schemas import BackgroundJobStartRead
from app.db import project_write_transaction
from app.lessons import ai_context, ai_enrich, ai_practice, ai_steps
from app.lessons import candidates as candidates_module
from app.lessons.ai_prompts import DraftLesson, LessonPlan, PlanStep, draft_instructions
from app.lessons.ai_schemas import (
    LessonAiBuildResult,
    LessonAiBuildWrite,
    LessonAiCandidateRead,
    LessonAiLevelRead,
    LessonAiMaterialRead,
    LessonAiOrder,
    LessonAiPlanRead,
    LessonAiPlanStep,
    LessonAiPreflightRead,
    LessonAiResumeWrite,
    LessonAiRunWrite,
)
from app.lessons.ai_writer import (
    LessonDraft,
    NoteItem,
    SourceItem,
    existing_result,
    labelled,
    save_lesson,
)
from app.lessons.candidates import Candidate, CandidateSet
from app.lessons.service import (
    ROLE_ORDER,
    _load_program,
    _require_lessons_project,
    _require_study_node,
    _source_name,
)
from app.models import (
    AiModelCatalogEntry,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    GoalPassport,
    LessonBasis,
    Material,
    ProgramNode,
    Project,
    ProjectMaterial,
    SourceRole,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError

ROLE = "lesson_builder"
SUBTYPE_BUILD = "build"
SUBTYPE_PLAN = "plan"
#: Полный текст лучших кусков в черновике; остальные идут началом.
DRAFT_FULL_TOKENS = 7_000
HEAD_WORDS = 80
#: Черновик — один ответ целиком, ему нужен запас на все шаги урока.
DRAFT_OUTPUT_TOKENS = 8_000
#: Бюджеты входа/выхода вызовов (план, §1а) — для оценки до того, как план известен.
PLAN_CALL = (8_000, ai_steps.PLAN_OUTPUT_TOKENS)
STEP_CALL = {"standard": (6_000, 2_000), "detailed": (6_000, 3_000)}
REVIEW_CALL = (12_000, ai_steps.REVIEW_OUTPUT_TOKENS)
#: Шагов в оценке до плана — середина диапазона, который просит промпт плана.
EXPECTED_STEPS = {"standard": 8, "detailed": 11}
#: Повтор после невалидной схемы тоже списывается с предела вызовов.
CALLS_SLACK = 2


@dataclass
class _Prepared:
    project: Project
    node: ProgramNode
    materials: list[LessonAiMaterialRead]
    found: CandidateSet
    brief: dict[str, Any]
    use_conspect: bool
    default_minutes: int | None


# --- этапы A–B: материалы, кандидаты, паспорт ------------------------------------------


def _default_selection(
    links: list[tuple[Material, ProjectMaterial]], ranged: set[UUID]
) -> set[UUID]:
    """С диапазоном темы — они (кроме справочных), иначе все не справочные."""
    main = {m.id for m, link in links if link.source_role != SourceRole.REFERENCE}
    with_range = main & ranged
    return with_range or main


def _materials(
    session: Session, project: Project, node: ProgramNode, order: LessonAiOrder
) -> list[LessonAiMaterialRead]:
    ranges = _load_program(session, project.id).ranges.get(node.id, {})
    links = [
        (material, link)
        for link in session.scalars(
            select(ProjectMaterial).where(ProjectMaterial.project_id == project.id)
        )
        if (material := session.get(Material, link.material_id)) is not None
    ]
    links.sort(key=lambda pair: (ROLE_ORDER[pair[1].source_role], pair[1].priority))
    known = {material.id for material, _ in links}
    if order.material_ids is not None:
        unknown = set(order.material_ids) - known
        if unknown:
            raise ProjectDomainError(
                "Материал не входит в проект", status=422, code="lesson_source_unavailable"
            )
        selected = set(order.material_ids)
    else:
        selected = _default_selection(links, set(ranges))
    result: list[LessonAiMaterialRead] = []
    for material, link in links:
        page_range = ranges.get(material.id)
        entry = ai_context.material_entry(
            material, link, _source_name(material, link, material.original_name), page_range
        )
        result.append(LessonAiMaterialRead(
            material_id=material.id, name=entry["name"], role=link.source_role,
            priority=link.priority, instruction=link.instruction, kind=entry["kind"],
            is_parsed=material.active_parse_revision > 0,
            page_from=page_range[0] if page_range else None,
            page_to=page_range[1] if page_range else None,
            selected=material.id in selected,
        ))
    return result


def _material_state(order: LessonAiOrder, selected: int, found: CandidateSet
                    ) -> ai_context.MaterialState:
    notes = tuple(found.search_notes)
    if order.basis == LessonBasis.MODEL_ONLY:
        return ai_context.MaterialState("материалы не используются: основа — знания модели")
    if not selected:
        return ai_context.MaterialState("материалы не выбраны")
    if not found.candidates:
        return ai_context.MaterialState("поиск не нашёл материала по теме", notes)
    if found.has_outline:
        return ai_context.MaterialState("есть диапазон темы по оглавлению", notes)
    return ai_context.MaterialState("диапазона по оглавлению нет — куски найдены поиском", notes)


def _order_data(order: LessonAiOrder, minutes: int | None) -> dict[str, Any]:
    return {
        "template": order.template,
        "level": order.level,
        "basis": order.basis.value,
        "minutes": order.minutes or minutes,
        "wishes": order.wishes.strip(),
    }


async def _prepare(
    session: Session, project: Project, node: ProgramNode, order: LessonAiOrder
) -> _Prepared:
    materials = _materials(session, project, node, order)
    selected = [item.material_id for item in materials if item.selected]
    if order.basis == LessonBasis.MODEL_ONLY or not selected:
        found = CandidateSet([], has_outline=False, searched=False, search_notes=[])
    else:
        found = await candidates_module.collect(session, node, selected)
    passport = session.get(GoalPassport, project.id)
    default_minutes = passport.session_minutes if passport else None
    words = ai_context.conspect_words(session, project.id, node.id)
    use_conspect = order.use_conspect if order.use_conspect is not None else words > 0
    brief = ai_context.build_brief(
        session,
        project=project,
        node=node,
        order=_order_data(order, default_minutes),
        materials=[
            ai_context.material_entry(
                session.get(Material, item.material_id),
                session.get(ProjectMaterial, (project.id, item.material_id)),
                item.name,
                (item.page_from, item.page_to) if item.page_from else None,
            )
            for item in materials if item.selected
        ],
        material_state=_material_state(order, len(selected), found),
        use_conspect=use_conspect,
    )
    return _Prepared(project, node, materials, found, brief, use_conspect, default_minutes)


# --- промпт черновика ------------------------------------------------------------------


def _sources_text(items: list[Candidate]) -> str:
    """Карта кусков: лучшие целиком в пределах бюджета, остальные — началом."""
    full: set[int] = set()
    used = 0
    for index in sorted(range(len(items)), key=lambda i: -items[i].score):
        if used + items[index].tokens > DRAFT_FULL_TOKENS and full:
            continue
        full.add(index)
        used += items[index].tokens
    parts = []
    for index, (label, item) in enumerate(labelled(items).items()):
        header = candidates_module.header(item, label)
        if index in full:
            parts.append(f"{header}\n{item.text}")
        else:
            head = candidates_module.head_text(item.text, HEAD_WORDS)
            parts.append(f"{header}\n(начало куска; в урок он войдёт целиком)\n{head}")
    return "\n\n---\n\n".join(parts) if parts else "(материалов нет)"


def draft_messages(brief: dict[str, Any], items: list[Candidate]) -> list[AiMessage]:
    order = brief["order"]
    system = draft_instructions(order["template"], order["level"], order["basis"])
    user = (
        f"<brief>\n{ai_context.render_brief(brief)}\n</brief>\n\n"
        f"<sources>\n{_sources_text(items)}\n</sources>\n\n"
        "Составь урок по теме из паспорта."
    )
    return [AiMessage(role="system", content=system), AiMessage(role="user", content=user)]


def _draft_request(
    project_id: UUID, brief: dict[str, Any], items: list[Candidate],
    model: AiModelSelection | None, **context: Any,
) -> AiTextRequest[DraftLesson]:
    brief_hash = hashlib.sha256(ai_context.render_brief(brief).encode()).hexdigest()
    return AiTextRequest(
        role=ROLE,
        messages=draft_messages(brief, items),
        response_model=DraftLesson,
        project_id=project_id,
        context_manifest=[
            {"kind": "stage", "stage": "draft"},
            {"kind": "brief", "sha256": brief_hash},
            *(
                {
                    "kind": "lesson_candidate", "id": label,
                    "material_id": str(item.material_id),
                    "page_from": item.page_from, "page_to": item.page_to,
                    "fragment_ids": [str(fragment) for fragment in item.fragment_ids],
                }
                for label, item in labelled(items).items()
            ),
        ],
        request_model_override=model,
        # Стоимость уже показана в диалоге, и её верх — предел задачи.
        confirmed=True,
        parameters={"max_output_tokens": DRAFT_OUTPUT_TOKENS},
        **context,
    )


# --- оценка ----------------------------------------------------------------------------


def _price(model: AiModelCatalogEntry | None, calls: list[tuple[int, int]]) -> Decimal | None:
    if model is None or model.prompt_price_usd is None or model.completion_price_usd is None:
        return None
    return sum(
        (model.prompt_price_usd * tokens_in + model.completion_price_usd * tokens_out
         for tokens_in, tokens_out in calls),
        Decimal(0),
    )


def _fixed_calls(level: str) -> list[tuple[int, int]]:
    """Вызовы сборки по плану сверх шагов: рецензент с правками и задания урока."""
    calls = [ai_practice.BUILD_CALL]
    if level == "detailed":
        calls = [REVIEW_CALL] + [STEP_CALL[level]] * ai_steps.MAX_REWRITES + calls
    return calls


def _level_calls(level: str, steps: int | None = None) -> list[tuple[int, int]]:
    """Вызовы уровня до плана: план, шаги, у «Подробного» рецензент с правками, задания."""
    count = steps if steps is not None else EXPECTED_STEPS[level]
    return [PLAN_CALL] + [STEP_CALL[level]] * count + _fixed_calls(level)


def _level_estimate(model: AiModelCatalogEntry | None, level: str) -> LessonAiLevelRead:
    calls = _level_calls(level)
    return LessonAiLevelRead(
        level=level, calls=len(calls),
        input_tokens=sum(item[0] for item in calls),
        output_tokens=sum(item[1] for item in calls),
        cost_usd=_price(model, calls), available=model is not None,
    )


def _step_costs(model: AiModelCatalogEntry | None, level: str
                ) -> tuple[Decimal | None, Decimal | None, int]:
    """Цена шага и неизменной части сборки по плану — для пересчёта в редакторе плана."""
    fixed = _fixed_calls(level)
    return _price(model, [STEP_CALL[level]]), _price(model, fixed), len(fixed)


async def preflight(
    session: Session, project_id: UUID, order: LessonAiOrder
) -> LessonAiPreflightRead:
    """Материалы, кандидаты, паспорт и оценка уровней — без вызова модели."""
    project = _require_lessons_project(session, project_id, writable=False)
    node = _require_study_node(session, project_id, order.program_node_id)
    prepared = await _prepare(session, project, node, order)
    items = prepared.found.candidates
    reason: str | None = None
    model: AiModelCatalogEntry | None = None
    provider_id: UUID | None = None
    draft = LessonAiLevelRead(
        level="draft", calls=1, input_tokens=0, output_tokens=DRAFT_OUTPUT_TOKENS,
        cost_usd=None, available=False,
    )
    try:
        resolved = resolve_model(session, ROLE, order.model)
        model, provider_id = resolved.model, resolved.provider.id
        estimate = await ModelGateway(session).preflight(
            _draft_request(project_id, prepared.brief, items, order.model)
        )
        draft = draft.model_copy(update={
            "input_tokens": estimate.estimated_input_tokens,
            "output_tokens": estimate.estimated_output_tokens,
            "cost_usd": estimate.estimated_cost_usd,
            "available": True,
        })
    except AiGatewayError as error:
        reason = error.detail
        model = None
        draft = draft.model_copy(update={"unavailable_reason": error.detail})
    levels = [draft]
    for level in ("standard", "detailed"):
        estimate_level = _level_estimate(model, level)
        if reason is not None:
            estimate_level = estimate_level.model_copy(update={"unavailable_reason": reason})
        levels.append(estimate_level)
    return LessonAiPreflightRead(
        program_node_id=node.id,
        topic_title=node.title,
        materials=prepared.materials,
        candidates=len(items),
        candidate_tokens=sum(item.tokens for item in items),
        material_state=prepared.brief["material_state"]["label"],
        notes=prepared.brief["material_state"]["notes"],
        sources_available=bool(items),
        default_minutes=prepared.default_minutes,
        conspect_words=ai_context.conspect_words(session, project_id, node.id),
        use_conspect=prepared.use_conspect,
        models_available=reason is None,
        models_unavailable_reason=reason,
        provider_id=provider_id,
        model_id=model.model_id if model else None,
        model_label=(model.display_name or model.model_id) if model else None,
        price_known=draft.cost_usd is not None,
        prices_from=model.pricing_snapshot_at if model else None,
        levels=levels,
        brief_text=ai_context.render_brief(prepared.brief),
    )


# --- постановка задач ------------------------------------------------------------------


@dataclass
class _Run:
    node: ProgramNode
    prepared: _Prepared
    resolved: ResolvedModel
    selection: AiModelSelection


async def _prepare_run(session: Session, project_id: UUID, command: LessonAiRunWrite) -> _Run:
    project = _require_lessons_project(session, project_id, writable=True)
    node = _require_study_node(session, project_id, command.program_node_id)
    prepared = await _prepare(session, project, node, command)
    if command.basis == LessonBasis.SOURCES and not prepared.found.candidates:
        raise ProjectConflictError(
            "По теме не нашлось материала — выберите основу со знаниями модели",
            code="lesson_ai_no_material",
        )
    resolved = resolve_model(session, ROLE, command.model)
    selection = command.model or AiModelSelection(
        provider_id=resolved.provider.id, model_id=resolved.model_id
    )
    return _Run(node, prepared, resolved, selection)


def _require_price(cost: Decimal | None, command: LessonAiRunWrite, model_id: str) -> None:
    if cost is None and not command.confirm_unknown_price:
        raise ProjectConflictError(
            "Цена модели неизвестна: подтвердите запуск без оценки стоимости",
            code="ai_price_unknown",
            context={"model_id": model_id},
        )


def _add_job(
    session: Session, project_id: UUID, *, subtype: str, total: int,
    checkpoint: dict[str, Any], max_cost: Decimal | None, max_calls: int,
    allow_unknown_price: bool,
) -> BackgroundJobStartRead:
    with project_write_transaction(session, project_id):
        job = BackgroundJob(
            kind=BackgroundJobKind.AI_LESSON,
            project_id=project_id,
            state=BackgroundJobState.QUEUED,
            done=0,
            total=total,
            checkpoint={
                "subtype": subtype,
                **checkpoint,
                BUDGET_KEY: budget_state(
                    max_cost_usd=max_cost, max_calls=max_calls,
                    allow_unknown_price=allow_unknown_price,
                ),
            },
            diagnostics=[],
            pause_requested=False,
        )
        session.add(job)
        session.flush()
        return BackgroundJobStartRead(job_id=job.id)


def _frozen(run: _Run, command: BaseModel) -> dict[str, Any]:
    return {
        "command": command.model_dump(mode="json"),
        "program_node_id": str(run.node.id),
        "topic_title": run.node.title,
        "brief": run.prepared.brief,
        "candidates": [item.to_json() for item in run.prepared.found.candidates],
        "model": run.selection.model_dump(mode="json"),
        "model_label": run.resolved.model.display_name or run.resolved.model_id,
    }


async def start_plan(
    session: Session, project_id: UUID, command: LessonAiRunWrite
) -> BackgroundJobStartRead:
    """План урока «Обычный»/«Подробный» — предложение для редактора плана."""
    if command.level == "draft":
        raise ProjectDomainError(
            "У «Черновика» плана нет — он собирается одним вызовом",
            status=422, code="lesson_ai_plan_level",
        )
    run = await _prepare_run(session, project_id, command)
    estimate = await ModelGateway(session).preflight(ai_steps.plan_request(
        project_id, run.prepared.brief, run.prepared.found.candidates, run.selection,
    ))
    _require_price(estimate.estimated_cost_usd, command, run.resolved.model_id)
    step_cost, fixed_cost, fixed_calls = _step_costs(run.resolved.model, command.level)
    return _add_job(
        session, project_id, subtype=SUBTYPE_PLAN, total=1,
        checkpoint={
            **_frozen(run, command),
            "costs": {
                "step_usd": str(step_cost) if step_cost is not None else None,
                "fixed_usd": str(fixed_cost) if fixed_cost is not None else None,
                "fixed_calls": fixed_calls,
            },
        },
        max_cost=command.max_cost_usd or estimate.estimated_cost_usd,
        max_calls=1 + CALLS_SLACK,
        allow_unknown_price=command.confirm_unknown_price,
    )


def _plan_from_write(command: LessonAiBuildWrite, count: int, basis: str
                     ) -> tuple[LessonPlan, list[str]]:
    assert command.plan is not None
    draft = LessonPlan(
        title=command.plan.title,
        goal=command.plan.goal,
        concepts=command.plan.concepts,
        steps=[
            PlanStep(
                kind=step.kind, title=step.title, intent=step.intent,
                sources=[label for label in step.sources if ai_steps.plan_index(label, count)
                         is not None],
                collapsed=step.collapsed, introduces=step.introduces,
            )
            for step in command.plan.steps
        ],
    )
    return ai_steps.sanitize_plan(draft, count, basis)


def _start_from_plan(
    session: Session, project_id: UUID, command: LessonAiBuildWrite
) -> BackgroundJobStartRead:
    """Сборка по правленому плану: паспорт и куски — те, по которым план составлен."""
    assert command.plan is not None
    _require_lessons_project(session, project_id, writable=True)
    plan_job = session.get(BackgroundJob, command.plan.job_id)
    if (
        plan_job is None
        or plan_job.project_id != project_id
        or plan_job.kind != BackgroundJobKind.AI_LESSON
        or plan_job.checkpoint.get("subtype") != SUBTYPE_PLAN
        or plan_job.state != BackgroundJobState.COMPLETED
    ):
        raise ProjectConflictError(
            "План урока не найден или ещё не готов", code="lesson_ai_plan_missing",
        )
    frozen = plan_job.checkpoint
    order = LessonAiRunWrite.model_validate(frozen["command"])
    merged = LessonAiBuildWrite.model_validate({
        **order.model_dump(mode="json"),
        "max_cost_usd": command.max_cost_usd, "confirm_unknown_price":
            command.confirm_unknown_price or order.confirm_unknown_price,
        "plan": command.plan.model_dump(mode="json"),
    })
    count = len(frozen["candidates"])
    plan, dropped = _plan_from_write(merged, count, order.basis.value)
    calls = ai_steps.planned_calls(order.level, len(plan.steps))
    costs = frozen.get("costs") or {}
    step_cost = Decimal(costs["step_usd"]) if costs.get("step_usd") else None
    fixed_cost = Decimal(costs["fixed_usd"]) if costs.get("fixed_usd") else Decimal(0)
    estimate = step_cost * len(plan.steps) + fixed_cost if step_cost is not None else None
    with project_write_transaction(session, project_id):
        stored = session.get(BackgroundJob, plan_job.id)
        assert stored is not None
        # План разобран: из корзины «ждут проверки» он уходит.
        stored.reviewed_at = utc_now()
    return _add_job(
        session, project_id, subtype=SUBTYPE_BUILD, total=1 + calls,
        checkpoint={
            **{key: frozen[key] for key in (
                "program_node_id", "topic_title", "brief", "candidates", "model", "model_label",
            )},
            "command": merged.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "plan_dropped": dropped,
            "plan_job_id": str(plan_job.id),
        },
        max_cost=merged.max_cost_usd or estimate,
        max_calls=calls + CALLS_SLACK * 2,
        allow_unknown_price=merged.confirm_unknown_price,
    )


async def start(
    session: Session, project_id: UUID, command: LessonAiBuildWrite
) -> BackgroundJobStartRead:
    """Поставить сборку: по плану, «Черновик» или «Обычный»/«Подробный» без показа плана."""
    if command.plan is not None:
        return _start_from_plan(session, project_id, command)
    run = await _prepare_run(session, project_id, command)
    items = run.prepared.found.candidates
    if command.level == "draft":
        estimate = await ModelGateway(session).preflight(
            _draft_request(project_id, run.prepared.brief, items, command.model)
        )
        cost, calls = estimate.estimated_cost_usd, 1
    else:
        level_calls = _level_calls(command.level)
        cost, calls = _price(run.resolved.model, level_calls), len(level_calls)
    _require_price(cost, command, run.resolved.model_id)
    return _add_job(
        session, project_id, subtype=SUBTYPE_BUILD, total=calls,
        checkpoint=_frozen(run, command),
        max_cost=command.max_cost_usd or cost,
        # Без плана число шагов ещё неизвестно: предел вызовов — по самому длинному плану.
        max_calls=(1 if command.level == "draft" else 1 + ai_steps.planned_calls(
            command.level, 16)) + CALLS_SLACK * 2,
        allow_unknown_price=command.confirm_unknown_price,
    )


def resume(
    session: Session, project_id: UUID, job_id: UUID, command: LessonAiResumeWrite
) -> BackgroundJobStartRead:
    """Продолжить упавшую сборку с места сбоя: готовые шаги в `checkpoint` не теряются."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        job = session.get(BackgroundJob, job_id)
        if (
            job is None
            or job.project_id != project_id
            or job.kind != BackgroundJobKind.AI_LESSON
            or job.state not in {BackgroundJobState.FAILED, BackgroundJobState.CANCELLED}
        ):
            raise ProjectConflictError(
                "Эту сборку нельзя продолжить", code="lesson_ai_not_resumable",
            )
        checkpoint = dict(job.checkpoint)
        checkpoint.pop("result", None)
        if command.max_cost_usd is not None:
            checkpoint[BUDGET_KEY] = {
                **checkpoint.get(BUDGET_KEY, {}), "max_cost_usd": str(command.max_cost_usd),
            }
        job.checkpoint = checkpoint
        job.state = BackgroundJobState.QUEUED
        job.error = None
        job.pause_requested = False
        job.completed_at = None
        job.updated_at = utc_now()
        session.flush()
        return BackgroundJobStartRead(job_id=job.id)


# --- выполнение ------------------------------------------------------------------------


async def _run_draft(
    session: Session, gateway: ModelGateway, job: BackgroundJob
) -> LessonAiBuildResult:
    items = [Candidate.from_json(item) for item in job.checkpoint["candidates"]]
    model = AiModelSelection.model_validate(job.checkpoint["model"])
    result = await gateway.complete(_draft_request(
        job.project_id, job.checkpoint["brief"], items, model,
        job_id=job.id, budget_context=JobBudget(session, job.id),
    ))
    session.expire_all()
    job = session.get(BackgroundJob, job.id)
    assert job is not None
    if job.pause_requested:
        # Отменили, пока шёл вызов: оплаченный ответ остаётся в AiRun, урок не создаётся.
        return LessonAiBuildResult(
            lesson_id=None, dropped=[], cost_usd=result.usage.actual_cost_usd
        )
    draft = LessonDraft(goal=result.value.goal, concepts=list(result.value.concepts),
                        run_ids=[result.run_id])
    for step in result.value.steps:
        if step.kind == "source":
            draft.items.append(SourceItem(step.source or "", step.collapsed))
        else:
            draft.items.append(NoteItem(step.variant, step.body_md or "", result.run_id))
    return save_lesson(
        session, job, draft, model_id=result.actual_model_id,
        cost=result.usage.actual_cost_usd,
    )


def _plan_read(job: BackgroundJob, plan: LessonPlan, dropped: list[str]) -> LessonAiPlanRead:
    order = LessonAiRunWrite.model_validate(job.checkpoint["command"])
    items = [Candidate.from_json(item) for item in job.checkpoint["candidates"]]
    costs = job.checkpoint.get("costs") or {}
    return LessonAiPlanRead(
        title=plan.title,
        goal=plan.goal,
        concepts=plan.concepts,
        steps=[LessonAiPlanStep.model_validate(step.model_dump()) for step in plan.steps],
        candidates=[
            LessonAiCandidateRead(
                label=f"C{index}", material_name=item.material_name, title=item.title,
                page_from=item.page_from, page_to=item.page_to, tokens=item.tokens,
                signals=item.signals,
            )
            for index, item in enumerate(items, start=1)
        ],
        template=order.template,
        level=order.level,
        basis=order.basis,
        minutes=job.checkpoint["brief"]["order"].get("minutes"),
        dropped=dropped,
        step_cost_usd=Decimal(costs["step_usd"]) if costs.get("step_usd") else None,
        fixed_cost_usd=Decimal(costs["fixed_usd"]) if costs.get("fixed_usd") else None,
        fixed_calls=int(costs.get("fixed_calls") or 0),
    )


async def _run_plan(
    session: Session, gateway: ModelGateway, job: BackgroundJob
) -> LessonAiPlanRead:
    items = [Candidate.from_json(item) for item in job.checkpoint["candidates"]]
    runner = ai_steps.Runner(session, gateway, job)
    plan, dropped = await ai_steps.make_plan(runner, job.checkpoint["brief"], items)
    session.expire_all()
    job = session.get(BackgroundJob, job.id)
    assert job is not None
    return _plan_read(job, plan, dropped)


async def run(session: Session, gateway: ModelGateway, job_id: UUID) -> BaseModel:
    """Выполнить задачу `ai_lesson` из очереди по её подвиду и уровню."""
    job = session.get(BackgroundJob, job_id)
    assert job is not None and job.project_id is not None
    subtype = job.checkpoint.get("subtype")
    if subtype == SUBTYPE_PLAN:
        return await _run_plan(session, gateway, job)
    if subtype == ai_enrich.SUBTYPE:
        return await ai_enrich.run(session, gateway, job_id)
    if subtype == ai_practice.SUBTYPE:
        return await ai_practice.run(session, gateway, job_id)
    if subtype != SUBTYPE_BUILD:
        raise AssertionError(f"Неизвестный подвид ai_lesson: {subtype}")
    if job.checkpoint["command"]["level"] == "draft":
        return existing_result(session, job) or await _run_draft(session, gateway, job)
    built = existing_result(session, job) or await ai_steps.run_staged(session, gateway, job_id)
    return await ai_practice.attach_to_build(session, gateway, job_id, built)
