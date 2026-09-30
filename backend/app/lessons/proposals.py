"""Применение предложения модели к уроку: частично, одной записью, с одной отменой.

Предложение (`ai_lesson/enrich`) лежит в `checkpoint.result` задачи. Выбранные
операции применяются по порядку предложения к уроку, каким он стал: пропавший
блок или разрез вне куска — «конфликт», а не молчаливое применение. Вся правка —
одна запись `lesson_blocks`: её отмена возвращает структуру, тексты переписанных
пояснений и название с целью урока. Удалять материал модель не может — такой
операции нет.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lessons import tasks
from app.lessons.ai_schemas import (
    LessonProposalApplyWrite,
    LessonProposalOp,
    LessonProposalRead,
)
from app.lessons.ai_writer import (
    citation_labels,
    labels_in_order,
    ref_key,
    rewrite_citations,
)
from app.lessons.editing import (
    _block_data,
    _content_ref,
    _Edit,
    _ordered_blocks,
    _split,
    _topics_data,
)
from app.lessons.schemas import LessonBlockWrite, LessonChangeResult
from app.lessons.service import (
    ACTION_LESSON_BLOCKS,
    _change_result,
    _require_lesson,
    _require_lessons_project,
    _require_revision,
)
from app.lessons.task_store import sync_lesson_tasks
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonSourceRef,
    ProjectActionLog,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError

PROPOSAL_SUBTYPES = {"enrich", "practice"}


class LessonProposalApplyResult(LessonChangeResult):
    # Выбранные операции, которые урок уже не принимает: блок пропал, разрез не лёг.
    conflicts: list[str]


def _proposal_job(session: Session, project_id: UUID, lesson_id: UUID, job_id: UUID
                  ) -> tuple[BackgroundJob, LessonProposalRead]:
    job = session.get(BackgroundJob, job_id)
    if (
        job is None
        or job.project_id != project_id
        or job.kind != BackgroundJobKind.AI_LESSON
        or job.checkpoint.get("subtype") not in PROPOSAL_SUBTYPES
        or job.state != BackgroundJobState.COMPLETED
        or job.checkpoint.get("result") is None
    ):
        raise ProjectConflictError("Предложение не найдено", code="lesson_proposal_missing")
    proposal = LessonProposalRead.model_validate(job.checkpoint["result"])
    if proposal.lesson_id != lesson_id:
        raise ProjectConflictError("Предложение к другому уроку", code="lesson_proposal_missing")
    if job.reviewed_at is not None:
        raise ProjectConflictError("Предложение уже разобрано", code="lesson_proposal_resolved")
    return job, proposal


class _Conflict(Exception):
    """Операция не ложится на урок, каким он стал."""


class _Applier:
    def __init__(self, session: Session, lesson: Lesson, proposal: LessonProposalRead,
                 profile: dict) -> None:
        self.session = session
        self.lesson = lesson
        self.proposal = proposal
        self.edit = _Edit(session, lesson, _ordered_blocks(session, lesson.id), LessonBlockWrite(
            expected_revision=lesson.revision, operation="add_note",
        ))
        self.sources = {item.label: item.block_id for item in proposal.sources}
        self.tasks = tasks.TaskPlacer(session, lesson, proposal.program_node_id, self.sources,
                                      profile, heading=False, edit=self.edit)
        self.labels = citation_labels(session, [block.id for block in self.edit.blocks])
        self.texts: dict[str, dict] = {}
        self.conflicts: list[str] = []

    def _block(self, block_id: UUID | None) -> LessonBlock | None:
        return next((item for item in self.edit.blocks if item.id == block_id), None)

    def _supports(self, body: str) -> tuple[str, list[LessonSourceRef]]:
        """Метки кусков предложения → опоры урока с его сквозными номерами."""
        mapping: dict[str, str] = {}
        refs: list[LessonSourceRef] = []
        for label in labels_in_order(body):
            block = self._block(self.sources.get(label))
            if block is None or block.kind != LessonBlockKind.SOURCE:
                continue
            content = _content_ref(self.session, block)
            key = ref_key(content)
            if key not in self.labels:
                taken = {int(item[1:]) for item in self.labels.values() if item[1:].isdigit()}
                self.labels[key] = f"S{max(taken, default=0) + 1}"
            mapping[label] = self.labels[key]
            refs.append(LessonSourceRef(
                id=uuid4(), role=LessonRefRole.SUPPORT, material_id=content.material_id,
                source_name_snapshot=content.source_name_snapshot,
                material_revision=content.material_revision,
                page_from=content.page_from, page_to=content.page_to,
                from_fragment_id=content.from_fragment_id, to_fragment_id=content.to_fragment_id,
                always_pages=False, boundary_shifted=False, citation_label=mapping[label],
            ))
        return rewrite_citations(body, mapping), refs

    def _attach(self, block: LessonBlock, refs: list[LessonSourceRef]) -> None:
        self.session.flush()
        seen: set[str] = set()
        for ref in refs:
            if ref.citation_label in seen:
                continue
            seen.add(ref.citation_label)
            ref.block_id = block.id
            self.session.add(ref)

    def insert_note(self, op: LessonProposalOp) -> None:
        anchor = self._block(op.block_id)
        if anchor is None:
            raise _Conflict
        if op.after_fragment_id is not None:
            if anchor.kind != LessonBlockKind.SOURCE:
                raise _Conflict
            self.edit.command = LessonBlockWrite(
                expected_revision=self.lesson.revision, operation="split",
                block_id=anchor.id, fragment_id=op.after_fragment_id,
            )
            try:
                _split(self.edit)
            except ProjectDomainError as error:
                raise _Conflict from error
        body, refs = self._supports(op.body_md or "")
        block = self.edit.new_block(
            LessonBlockKind.NOTE, variant=LessonNoteVariant(op.variant or "explanation"),
            body_md=body, origin=LessonBlockOrigin.MODEL, basis=op.basis, ai_run_id=op.run_id,
        )
        self.edit.insert(block, anchor.id)
        self._attach(block, refs)

    def rewrite_note(self, op: LessonProposalOp) -> None:
        block = self._block(op.block_id)
        if block is None or block.kind != LessonBlockKind.NOTE:
            raise _Conflict
        self.texts.setdefault(str(block.id), {
            "body_md": block.body_md, "variant": block.variant.value if block.variant else None,
            "origin": block.origin.value, "basis": block.basis.value if block.basis else None,
            "ai_run_id": str(block.ai_run_id) if block.ai_run_id else None,
        })
        body, refs = self._supports(op.body_md or "")
        self.session.execute(delete(LessonSourceRef).where(
            LessonSourceRef.block_id == block.id, LessonSourceRef.role == LessonRefRole.SUPPORT,
        ))
        block.body_md = body
        if op.variant:
            block.variant = LessonNoteVariant(op.variant)
        # Текст человека, переписанный моделью, — уже смешанный (FR-L5).
        block.origin = (LessonBlockOrigin.MODEL if block.origin == LessonBlockOrigin.MODEL
                        else LessonBlockOrigin.MIXED)
        block.basis = op.basis
        block.ai_run_id = op.run_id
        block.updated_at = utc_now()
        self._attach(block, refs)

    def set_collapsed(self, op: LessonProposalOp) -> None:
        block = self._block(op.block_id)
        if block is None or block.kind != LessonBlockKind.SOURCE or op.collapsed is None:
            raise _Conflict
        block.collapsed = op.collapsed

    def insert_task(self, op: LessonProposalOp) -> None:
        if op.task is None or self.tasks.place(op) is None:
            raise _Conflict

    def rename_lesson(self, op: LessonProposalOp) -> None:
        self.lesson.title = (op.text or self.lesson.title)[:200]

    def set_goal(self, op: LessonProposalOp) -> None:
        self.lesson.goal = op.text


def apply_proposal(
    session: Session, project_id: UUID, lesson_id: UUID, job_id: UUID,
    command: LessonProposalApplyWrite,
) -> LessonProposalApplyResult:
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        _require_revision(lesson, command.expected_revision)
        job, proposal = _proposal_job(session, project_id, lesson_id, job_id)
        chosen = set(command.op_ids)
        unknown = chosen - {op.id for op in proposal.ops}
        if unknown:
            raise ProjectDomainError(
                "В предложении нет таких изменений", status=422, code="lesson_proposal_op",
                context={"op_ids": sorted(unknown)},
            )
        before = [_block_data(session, block) for block in _ordered_blocks(session, lesson.id)]
        topics = _topics_data(session, lesson.id)
        lesson_before = {"title": lesson.title, "goal": lesson.goal}
        applier = _Applier(session, lesson, proposal,
                           tasks.profile_of(job.checkpoint.get("brief") or {}))
        applied: list[str] = []
        for op in proposal.ops:
            if op.id not in chosen:
                continue
            try:
                getattr(applier, op.op)(op)
            except _Conflict:
                applier.conflicts.append(op.id)
                continue
            applied.append(op.id)
            session.flush()
        for index, block in enumerate(applier.edit.blocks):
            block.sort_order = index
        session.flush()
        sync_lesson_tasks(session, lesson.id)
        if applied:
            lesson.revision += 1
            lesson.updated_at = utc_now()
            session.add(ProjectActionLog(
                project_id=project_id, action_type=ACTION_LESSON_BLOCKS,
                phase="active", payload_version=1, target_title=lesson.title,
                inverse_data={
                    "lesson_id": str(lesson.id), "blocks": before, "topics": topics,
                    "binding_ids": [str(item) for item in applier.edit.binding_ids],
                    "texts": applier.texts, "lesson": lesson_before,
                },
            ))
        stored = session.get(BackgroundJob, job.id)
        assert stored is not None
        stored.checkpoint = {**stored.checkpoint, "applied_op_ids": applied,
                             "conflict_op_ids": applier.conflicts}
        stored.reviewed_at = utc_now()
        session.flush()
        result = _change_result(session, lesson)
        return LessonProposalApplyResult(**result.model_dump(), conflicts=applier.conflicts)
