"""«Собрать урок с ИИ»: оценка перед запуском, фоновая задача и сборка черновика.

Этапы A–B (область и кандидаты) идут без модели при постановке задачи и
замораживаются в `checkpoint` вместе с паспортом урока: все вызовы одной сборки
видят одно и то же. Модель выбирает куски только метками `S*` из этого списка,
поэтому ссылка урока всегда лежит внутри переданного ей контекста (FR-L10).
Сервер проверяет каждую ссылку сам: неизвестная отбрасывается, а пояснение без
подтверждённой опоры получает основание «знания модели» — метка видна в уроке.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.job_budget import JobBudget, budget_state
from app.ai.schemas import AiMessage, AiModelSelection
from app.ai.settings import AiGatewayError, resolve_model
from app.background.schemas import BackgroundJobStartRead
from app.db import project_write_transaction
from app.lessons import ai_context, boundaries
from app.lessons import candidates as candidates_module
from app.lessons import refs as refs_module
from app.lessons.ai_prompts import TEMPLATES, DraftLesson, draft_instructions
from app.lessons.ai_schemas import (
    LessonAiBuildResult,
    LessonAiBuildWrite,
    LessonAiLevelRead,
    LessonAiMaterialRead,
    LessonAiOrder,
    LessonAiPreflightRead,
)
from app.lessons.candidates import Candidate, CandidateSet
from app.lessons.editing import _bind_fragments, _create_source, _Edit
from app.lessons.schemas import LessonBlockWrite
from app.lessons.service import (
    ACTION_LESSON_CREATE,
    ROLE_ORDER,
    _load_program,
    _require_lessons_project,
    _require_study_node,
    _source_name,
    new_lesson,
)
from app.models import (
    AiModelCatalogEntry,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    GoalPassport,
    Lesson,
    LessonBasis,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonSourceRef,
    Material,
    ProgramNode,
    Project,
    ProjectActionLog,
    ProjectMaterial,
    SourceRole,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError
from app.retrieval.citations import CITATION_GROUP, cited_ids

ROLE = "lesson_builder"
SUBTYPE_BUILD = "build"
#: Полный текст лучших кусков в черновике; остальные идут началом.
DRAFT_FULL_TOKENS = 7_000
HEAD_WORDS = 80
#: Черновик — один ответ целиком, ему нужен запас на все шаги урока.
DRAFT_OUTPUT_TOKENS = 8_000
#: Число вызовов и бюджеты входа/выхода по уровням (план, §1а) — для оценки до запуска.
#: Черновик считается точно по настоящему запросу, остальные — по этим бюджетам.
LEVEL_CALLS: dict[str, list[tuple[int, int]]] = {
    "standard": [(8_000, 3_000)] + [(6_000, 2_000)] * 6 + [(10_000, 4_000)],
    "detailed": [(8_000, 3_000)] + [(6_000, 2_500)] * 9 + [(12_000, 4_000)]
    + [(6_000, 2_500)] * 3 + [(10_000, 5_000)],
}
LEVEL_PENDING = "Уровень появится в следующем срезе — пока доступен «Черновик»"
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


def _labels(items: list[Candidate]) -> dict[str, Candidate]:
    return {f"S{index}": item for index, item in enumerate(items, start=1)}


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
    for index, (label, item) in enumerate(_labels(items).items()):
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


def _manifest(stage: str, brief: dict[str, Any], items: list[Candidate]) -> list[dict[str, Any]]:
    brief_hash = hashlib.sha256(ai_context.render_brief(brief).encode()).hexdigest()
    return [
        {"kind": "stage", "stage": stage},
        {"kind": "brief", "sha256": brief_hash},
        *(
            {
                "kind": "lesson_candidate", "id": label, "material_id": str(item.material_id),
                "page_from": item.page_from, "page_to": item.page_to,
                "fragment_ids": [str(fragment) for fragment in item.fragment_ids],
            }
            for label, item in _labels(items).items()
        ),
    ]


def _draft_request(
    project_id: UUID, brief: dict[str, Any], items: list[Candidate],
    model: AiModelSelection | None, *, job_id: UUID | None = None,
    budget: JobBudget | None = None,
) -> AiTextRequest[DraftLesson]:
    return AiTextRequest(
        role=ROLE,
        messages=draft_messages(brief, items),
        response_model=DraftLesson,
        project_id=project_id,
        context_manifest=_manifest("draft", brief, items),
        request_model_override=model,
        # Стоимость уже показана в диалоге, и её верх — предел задачи.
        confirmed=True,
        parameters={"max_output_tokens": DRAFT_OUTPUT_TOKENS},
        job_id=job_id,
        budget_context=budget,
    )


# --- оценка ----------------------------------------------------------------------------


def _level_estimate(model: AiModelCatalogEntry | None, level: str) -> LessonAiLevelRead:
    calls = LEVEL_CALLS[level]
    input_tokens = sum(item[0] for item in calls)
    output_tokens = sum(item[1] for item in calls)
    cost = (
        model.prompt_price_usd * input_tokens + model.completion_price_usd * output_tokens
        if model and model.prompt_price_usd is not None and model.completion_price_usd is not None
        else None
    )
    return LessonAiLevelRead(
        level=level, calls=len(calls), input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=cost, available=False, unavailable_reason=LEVEL_PENDING,
    )


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
        draft = draft.model_copy(update={"unavailable_reason": error.detail})
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
        levels=[draft, _level_estimate(model, "standard"), _level_estimate(model, "detailed")],
        brief_text=ai_context.render_brief(prepared.brief),
    )


# --- постановка задачи -----------------------------------------------------------------


async def start(
    session: Session, project_id: UUID, command: LessonAiBuildWrite
) -> BackgroundJobStartRead:
    """Поставить сборку. Кандидаты и паспорт считаются здесь и замораживаются в задаче."""
    if command.level != "draft":
        raise ProjectDomainError(LEVEL_PENDING, status=422, code="lesson_ai_level_unavailable")
    project = _require_lessons_project(session, project_id, writable=True)
    node = _require_study_node(session, project_id, command.program_node_id)
    prepared = await _prepare(session, project, node, command)
    items = prepared.found.candidates
    if command.basis == LessonBasis.SOURCES and not items:
        raise ProjectConflictError(
            "По теме не нашлось материала — выберите основу со знаниями модели",
            code="lesson_ai_no_material",
        )
    resolved = resolve_model(session, ROLE, command.model)
    estimate = await ModelGateway(session).preflight(
        _draft_request(project_id, prepared.brief, items, command.model)
    )
    if estimate.estimated_cost_usd is None and not command.confirm_unknown_price:
        raise ProjectConflictError(
            "Цена модели неизвестна: подтвердите запуск без оценки стоимости",
            code="ai_price_unknown",
            context={"model_id": resolved.model_id},
        )
    max_cost = command.max_cost_usd or estimate.estimated_cost_usd
    selection = command.model or AiModelSelection(
        provider_id=resolved.provider.id, model_id=resolved.model_id
    )
    with project_write_transaction(session, project_id):
        job = BackgroundJob(
            kind=BackgroundJobKind.AI_LESSON,
            project_id=project_id,
            state=BackgroundJobState.QUEUED,
            done=0,
            total=1,
            checkpoint={
                "subtype": SUBTYPE_BUILD,
                "command": command.model_dump(mode="json"),
                "program_node_id": str(node.id),
                "topic_title": node.title,
                "brief": prepared.brief,
                "candidates": [item.to_json() for item in items],
                "model": selection.model_dump(mode="json"),
                "model_label": resolved.model.display_name or resolved.model_id,
                "budget": budget_state(
                    max_cost_usd=max_cost,
                    max_calls=1 + CALLS_SLACK,
                    allow_unknown_price=command.confirm_unknown_price,
                ),
            },
            diagnostics=[],
            pause_requested=False,
        )
        session.add(job)
        session.flush()
        return BackgroundJobStartRead(job_id=job.id)


# --- сборка черновика ------------------------------------------------------------------


#: Группа ссылок вместе с пробелом перед ней: убранная ссылка не оставляет «текст .».
_CITATION_WITH_SPACE = re.compile(r"([ \t]*)" + CITATION_GROUP.pattern)


def _labels_in_order(text: str) -> list[str]:
    """Метки `S*` текста в порядке первого появления."""
    found = [
        item.strip()
        for group in CITATION_GROUP.findall(text)
        for item in re.split(r"[,;]", group)
    ]
    return list(dict.fromkeys(found))


def _rewrite_citations(text: str, mapping: dict[str, str]) -> str:
    """Оставить в тексте только известные метки и перевести их в номера урока."""

    def replace(match: re.Match[str]) -> str:
        kept = [
            mapping[item.strip()]
            for item in re.split(r"[,;]", match.group(2))
            if item.strip() in mapping
        ]
        return f"{match.group(1)}[{', '.join(dict.fromkeys(kept))}]" if kept else ""

    return _CITATION_WITH_SPACE.sub(replace, text).strip()


def _heading(text: str) -> str:
    return f"## {text.strip().lstrip('#').strip()}"


class _DraftWriter:
    """Черновик в блоки урока: куски — ссылками, пояснения — с опорами `support`."""

    def __init__(
        self, session: Session, lesson: Lesson, node: ProgramNode,
        items: dict[str, Candidate], basis: LessonBasis, template: str, run_id: UUID,
    ) -> None:
        self.session = session
        self.lesson = lesson
        self.node = node
        self.items = items
        self.basis = basis
        self.collapsed_default = TEMPLATES[template].collapsed
        self.run_id = run_id
        self.edit = _Edit(session, lesson, [], LessonBlockWrite(
            expected_revision=lesson.revision, operation="add_fragments",
        ))
        self.dropped: list[str] = []
        self.used_sources: set[str] = set()
        # Сквозные номера опор урока в порядке первой ссылки: S7 модели → S1 урока.
        self.lesson_labels: dict[str, str] = {}
        self.characters = 0

    def _material(self, item: Candidate) -> tuple[Material, ProjectMaterial] | None:
        material = self.session.get(Material, item.material_id)
        link = self.session.get(ProjectMaterial, (self.lesson.project_id, item.material_id))
        return (material, link) if material is not None and link is not None else None

    def _bounds(self, item: Candidate, material: Material) -> refs_module.Bounds | None:
        order = refs_module.load_order(self.session, material, item.page_from, item.page_to)
        known = {fragment.id for fragment in order.fragments}
        if item.fragment_ids[0] not in known or item.fragment_ids[-1] not in known:
            return None
        return refs_module.fragment_range(order, item.fragment_ids[0], item.fragment_ids[-1])

    def add_source(self, label: str, collapsed: bool | None) -> None:
        item = self.items.get(label)
        if item is None:
            self.dropped.append(f"Кусок {label}: такого источника не было в контексте")
            return
        if label in self.used_sources:
            self.dropped.append(f"Кусок {label}: уже стоит в уроке")
            return
        pair = self._material(item)
        bounds = self._bounds(item, pair[0]) if pair else None
        if pair is None or bounds is None:
            self.dropped.append(f"Кусок {label}: материал изменился после оценки")
            return
        material, link = pair
        # Без `after_block_id` правка ставит блок в конец — черновик пишется по порядку.
        block = _create_source(
            self.edit, material, link, bounds, self.node.id, LessonBlockOrigin.MODEL
        )
        block.collapsed = self.collapsed_default if collapsed is None else collapsed
        order = refs_module.load_order(self.session, material, bounds.page_from, bounds.page_to)
        self.edit.binding_ids += _bind_fragments(
            self.session, self.lesson.project_id, self.node.id, material.id,
            refs_module.content_fragment_ids(order, bounds), LessonBlockOrigin.MODEL,
        )
        self.used_sources.add(label)
        self.characters += len(item.text)

    def _supports(self, body: str) -> tuple[str, list[str]]:
        """Ссылки пояснения: известные метки получают номер урока, прочие исчезают."""
        cited = cited_ids(body)
        if self.basis == LessonBasis.MODEL_ONLY:
            return _rewrite_citations(body, {}), []
        unknown = sorted(cited - set(self.items))
        if unknown:
            self.dropped.append("Ссылки на неизвестные источники убраны: " + ", ".join(unknown))
        for label in _labels_in_order(body):
            if label in self.items:
                self.lesson_labels.setdefault(label, f"S{len(self.lesson_labels) + 1}")
        text = _rewrite_citations(body, self.lesson_labels)
        return text, [label for label in self.lesson_labels if label in cited]

    def add_note(self, variant: str | None, body: str | None) -> None:
        body = (body or "").strip()
        if not body:
            self.dropped.append("Пустое пояснение пропущено")
            return
        note_variant = LessonNoteVariant(variant or LessonNoteVariant.EXPLANATION.value)
        if note_variant == LessonNoteVariant.HEADING:
            text, supports = _heading(_rewrite_citations(body, {})), []
        else:
            text, supports = self._supports(body)
        basis = self.basis if supports or self.basis == LessonBasis.MODEL_ONLY else (
            LessonBasis.MODEL_ONLY
        )
        block = self.edit.new_block(
            LessonBlockKind.NOTE, variant=note_variant, body_md=text,
            origin=LessonBlockOrigin.MODEL, ai_run_id=self.run_id,
            basis=None if note_variant == LessonNoteVariant.HEADING else basis,
        )
        self.edit.insert(block, None)
        self.session.flush()
        for label in supports:
            self._support_ref(block, label)
        self.characters += len(text)

    def _support_ref(self, block: LessonBlock, label: str) -> None:
        item = self.items[label]
        pair = self._material(item)
        bounds = self._bounds(item, pair[0]) if pair else None
        if pair is None or bounds is None:
            return
        material, link = pair
        self.session.add(LessonSourceRef(
            id=uuid4(), block_id=block.id, role=LessonRefRole.SUPPORT, material_id=material.id,
            source_name_snapshot=_source_name(material, link, material.original_name),
            material_revision=material.active_parse_revision or None,
            page_from=bounds.page_from, page_to=bounds.page_to,
            from_fragment_id=bounds.from_fragment_id, to_fragment_id=bounds.to_fragment_id,
            always_pages=False, boundary_shifted=False,
            citation_label=self.lesson_labels[label],
        ))

    def finish(self) -> None:
        for index, block in enumerate(self.edit.blocks):
            block.sort_order = index


def _save_draft(
    session: Session, job: BackgroundJob, draft: DraftLesson, run_id: UUID,
    actual_model_id: str, cost: Decimal | None,
) -> LessonAiBuildResult:
    checkpoint = job.checkpoint
    command = LessonAiBuildWrite.model_validate(checkpoint["command"])
    items = _labels([Candidate.from_json(item) for item in checkpoint["candidates"]])
    project_id = job.project_id
    assert project_id is not None
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, command.program_node_id)
        now = utc_now()
        lesson = new_lesson(session, project_id, node, now)
        lesson.goal = draft.goal.strip() or None
        writer = _DraftWriter(
            session, lesson, node, items, command.basis, command.template, run_id
        )
        for step in draft.steps:
            if step.kind == "source" and command.basis != LessonBasis.MODEL_ONLY:
                writer.add_source(step.source or "", step.collapsed)
            elif step.kind == "note":
                writer.add_note(step.variant, step.body_md)
            else:
                writer.dropped.append("Кусок материала при основе «только знания модели» убран")
        writer.finish()
        lesson.duration_minutes = command.minutes or boundaries.estimate_minutes(
            writer.characters
        )
        lesson.build_meta = {
            "template": command.template,
            "level": command.level,
            "basis": command.basis.value,
            "model_id": actual_model_id,
            "cost_usd": str(cost) if cost is not None else None,
            "concepts": [item.strip() for item in draft.concepts if item.strip()],
            "job_id": str(job.id),
            "ai_run_ids": [str(run_id)],
            "dropped": writer.dropped,
        }
        session.add(ProjectActionLog(
            project_id=project_id, action_type=ACTION_LESSON_CREATE,
            phase="active", payload_version=1, target_title=lesson.title,
            inverse_data={
                "lesson_id": str(lesson.id),
                "binding_ids": [str(item) for item in writer.edit.binding_ids],
            },
        ))
        stored = session.get(BackgroundJob, job.id)
        assert stored is not None
        stored.checkpoint = {**stored.checkpoint, "lesson_id": str(lesson.id)}
        session.flush()
        return LessonAiBuildResult(lesson_id=lesson.id, dropped=writer.dropped, cost_usd=cost)


async def run(session: Session, gateway: ModelGateway, job_id: UUID) -> LessonAiBuildResult:
    """Выполнить сборку из очереди. Готовый урок не создаётся второй раз при повторе задачи."""
    job = session.get(BackgroundJob, job_id)
    assert job is not None and job.project_id is not None
    checkpoint = job.checkpoint
    if checkpoint.get("subtype") != SUBTYPE_BUILD:
        raise AssertionError(f"Неизвестный подвид ai_lesson: {checkpoint.get('subtype')}")
    if checkpoint.get("lesson_id"):
        lesson = session.get(Lesson, UUID(checkpoint["lesson_id"]))
        meta = (lesson.build_meta or {}) if lesson else {}
        return LessonAiBuildResult(
            lesson_id=UUID(checkpoint["lesson_id"]), dropped=list(meta.get("dropped") or []),
            cost_usd=Decimal(meta["cost_usd"]) if meta.get("cost_usd") else None,
        )
    items = [Candidate.from_json(item) for item in checkpoint["candidates"]]
    model = AiModelSelection.model_validate(checkpoint["model"])
    result = await gateway.complete(_draft_request(
        job.project_id, checkpoint["brief"], items, model,
        job_id=job_id, budget=JobBudget(session, job_id),
    ))
    session.expire_all()
    job = session.get(BackgroundJob, job_id)
    assert job is not None
    if job.pause_requested:
        # Отменили, пока шёл вызов: оплаченный ответ остаётся в AiRun, урок не создаётся.
        return LessonAiBuildResult(
            lesson_id=None, dropped=[], cost_usd=result.usage.actual_cost_usd
        )
    return _save_draft(
        session, job, result.value, result.run_id, result.actual_model_id,
        result.usage.actual_cost_usd,
    )

