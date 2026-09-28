"""Запись модельного урока: шаги → блоки, куски → ссылки, ссылки `[S*]` → опоры.

Общая для «Черновика» и сборки по плану. Кандидаты здесь адресуются метками
`S1…Sn` своего списка; модель не может указать то, чего в нём нет (FR-L10).
Неизвестная ссылка убирается и попадает в `dropped`, пояснение без подтверждённой
опоры получает основание «знания модели», известные метки становятся сквозными
номерами урока в порядке первой ссылки.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lessons import boundaries
from app.lessons import refs as refs_module
from app.lessons.ai_prompts import TEMPLATES
from app.lessons.ai_schemas import LessonAiBuildResult, LessonAiBuildWrite
from app.lessons.candidates import Candidate
from app.lessons.editing import _bind_fragments, _create_source, _Edit
from app.lessons.schemas import LessonBlockWrite
from app.lessons.service import (
    ACTION_LESSON_CREATE,
    _require_lessons_project,
    _require_study_node,
    _source_name,
    new_lesson,
)
from app.models import (
    BackgroundJob,
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
    ProjectActionLog,
    ProjectMaterial,
    utc_now,
)
from app.retrieval.citations import CITATION_GROUP, cited_ids

#: Группа ссылок вместе с пробелом перед ней: убранная ссылка не оставляет «текст .».
_CITATION_WITH_SPACE = re.compile(r"([ \t]*)" + CITATION_GROUP.pattern)


def labels_in_order(text: str) -> list[str]:
    """Метки `S*` текста в порядке первого появления."""
    found = [
        item.strip()
        for group in CITATION_GROUP.findall(text)
        for item in re.split(r"[,;]", group)
    ]
    return list(dict.fromkeys(found))


def rewrite_citations(text: str, mapping: dict[str, str]) -> str:
    """Оставить в тексте только метки из `mapping` и переименовать их по нему."""

    def replace(match: re.Match[str]) -> str:
        kept = [
            mapping[item.strip()]
            for item in re.split(r"[,;]", match.group(2))
            if item.strip() in mapping
        ]
        return f"{match.group(1)}[{', '.join(dict.fromkeys(kept))}]" if kept else ""

    return _CITATION_WITH_SPACE.sub(replace, text).strip()


def labelled(items: list[Candidate]) -> dict[str, Candidate]:
    return {f"S{index}": item for index, item in enumerate(items, start=1)}


def heading_markdown(text: str) -> str:
    return f"## {text.strip().lstrip('#').strip()}"


@dataclass(frozen=True)
class NoteItem:
    variant: str | None
    body: str
    run_id: UUID | None


@dataclass(frozen=True)
class SourceItem:
    label: str
    collapsed: bool | None


@dataclass
class LessonDraft:
    """Урок модели до записи: цель, понятия и шаги по порядку."""

    goal: str
    concepts: list[str]
    items: list[NoteItem | SourceItem] = field(default_factory=list)
    run_ids: list[UUID] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


class LessonWriter:
    """Шаги в блоки урока: куски — ссылками, пояснения — с опорами `support`."""

    def __init__(
        self, session: Session, lesson: Lesson, node: ProgramNode,
        items: dict[str, Candidate], basis: LessonBasis, template: str,
    ) -> None:
        self.session = session
        self.lesson = lesson
        self.node = node
        self.items = items
        self.basis = basis
        self.collapsed_default = TEMPLATES[template].collapsed
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
        if self.basis == LessonBasis.MODEL_ONLY:
            self.dropped.append("Кусок материала при основе «только знания модели» убран")
            return
        item = self.items.get(label)
        if item is None:
            self.dropped.append(f"Кусок {label}: такого источника не было в контексте")
            return
        if label in self.used_sources:
            return
        pair = self._material(item)
        bounds = self._bounds(item, pair[0]) if pair else None
        if pair is None or bounds is None:
            self.dropped.append(f"Кусок {label}: материал изменился после оценки")
            return
        material, link = pair
        # Без `after_block_id` правка ставит блок в конец — урок пишется по порядку.
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
            return rewrite_citations(body, {}), []
        unknown = sorted(cited - set(self.items))
        if unknown:
            self.dropped.append("Ссылки на неизвестные источники убраны: " + ", ".join(unknown))
        for label in labels_in_order(body):
            if label in self.items:
                self.lesson_labels.setdefault(label, f"S{len(self.lesson_labels) + 1}")
        text = rewrite_citations(body, self.lesson_labels)
        return text, [label for label in self.lesson_labels if label in cited]

    def add_note(self, variant: str | None, body: str | None, run_id: UUID | None) -> None:
        body = (body or "").strip()
        if not body:
            self.dropped.append("Пустое пояснение пропущено")
            return
        note_variant = LessonNoteVariant(variant or LessonNoteVariant.EXPLANATION.value)
        if note_variant == LessonNoteVariant.HEADING:
            # Заголовок с абзацем под ним — два блока: у текста свои опоры и метка основы.
            title, _, rest = body.partition("\n")
            self._add_block(
                LessonNoteVariant.HEADING, heading_markdown(rewrite_citations(title, {})), [],
                run_id,
            )
            if rest.strip():
                self.add_note(LessonNoteVariant.EXPLANATION.value, rest, run_id)
            return
        self._add_block(note_variant, *self._supports(body), run_id)

    def _add_block(
        self, note_variant: LessonNoteVariant, text: str, supports: list[str],
        run_id: UUID | None,
    ) -> None:
        basis = self.basis if supports or self.basis == LessonBasis.MODEL_ONLY else (
            LessonBasis.MODEL_ONLY
        )
        block = self.edit.new_block(
            LessonBlockKind.NOTE, variant=note_variant, body_md=text,
            origin=LessonBlockOrigin.MODEL, ai_run_id=run_id,
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


def existing_result(session: Session, job: BackgroundJob) -> LessonAiBuildResult | None:
    """Урок уже записан этой задачей — повтор после сбоя не создаёт второй."""
    raw = job.checkpoint.get("lesson_id")
    if not raw:
        return None
    lesson = session.get(Lesson, UUID(raw))
    meta = (lesson.build_meta or {}) if lesson else {}
    return LessonAiBuildResult(
        lesson_id=UUID(raw), dropped=list(meta.get("dropped") or []),
        cost_usd=Decimal(meta["cost_usd"]) if meta.get("cost_usd") else None,
    )


def save_lesson(
    session: Session, job: BackgroundJob, draft: LessonDraft, *,
    model_id: str, cost: Decimal | None,
) -> LessonAiBuildResult:
    """Новый черновик одной записью `lesson_create`: отмена уносит урок и привязки."""
    checkpoint = job.checkpoint
    command = LessonAiBuildWrite.model_validate(checkpoint["command"])
    items = labelled([Candidate.from_json(item) for item in checkpoint["candidates"]])
    project_id = job.project_id
    assert project_id is not None
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, command.program_node_id)
        lesson = new_lesson(session, project_id, node, utc_now())
        lesson.goal = draft.goal.strip() or None
        writer = LessonWriter(session, lesson, node, items, command.basis, command.template)
        writer.dropped.extend(draft.dropped)
        for item in draft.items:
            if isinstance(item, SourceItem):
                writer.add_source(item.label, item.collapsed)
            else:
                writer.add_note(item.variant, item.body, item.run_id)
        writer.finish()
        lesson.duration_minutes = command.minutes or boundaries.estimate_minutes(
            writer.characters
        )
        lesson.build_meta = {
            "template": command.template,
            "level": command.level,
            "basis": command.basis.value,
            "model_id": model_id,
            "cost_usd": str(cost) if cost is not None else None,
            "concepts": [item.strip() for item in draft.concepts if item.strip()],
            "job_id": str(job.id),
            "ai_run_ids": [str(item) for item in draft.run_ids],
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
