"""Задания урока (FR-L11): проверка формы, запись, чтение и попытки.

Задание — Активность `study_task` и строка `study_tasks` с формой, условием,
ключом и опорами; в документе урока его держит блок вида `activity`. Модель
предлагает задание черновиком `TaskDraft`, сервер проверяет форму и всё
невалидное отбрасывает с причиной. Шесть форм проверяются по ключу без модели
(`task_check`), открытый ответ — судьёй экзамена с нейтральной персоной; без
моделей такой ответ сохраняется без оценки и проверяется позже.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.settings import AiGatewayError
from app.db import project_write_transaction
from app.exam.judge import judge_attempt
from app.lessons import refs as refs_module
from app.lessons import task_check
from app.lessons.ai_prompts import TaskDraft
from app.lessons.ai_schemas import LessonProposalOp
from app.lessons.ai_writer import labels_in_order, rewrite_citations
from app.lessons.editing import _Edit, _ordered_blocks
from app.lessons.schemas import LessonBlockWrite
from app.lessons.service import _require_lesson, _require_lessons_project, _source_name
from app.lessons.task_schemas import (
    StudyTaskAttemptRead,
    StudyTaskAttemptWrite,
    StudyTaskDraftRead,
)
from app.lessons.task_store import attempt_read
from app.models import (
    Activity,
    ActivityKind,
    ActivityOrigin,
    Attempt,
    ExaminerPersona,
    ExaminerStrictness,
    Grade,
    GradeMethod,
    Lesson,
    LessonBasis,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonSourceRef,
    Material,
    MaterialFragment,
    ProjectMaterial,
    StudyTask,
    StudyTaskDifficulty,
    StudyTaskForm,
)
from app.projects.errors import ProjectDomainError, ProjectNotFoundError

MARKER = re.compile(r"\{\{(\d+)\}\}")
#: Судья открытого ответа видит опоры задания, а не весь урок.
JUDGE_SOURCE_CHARS = 3_000
#: Модели недоступны по настройке или сети — ответ ждёт проверки, а не падает.
AI_PENDING_CODES = {
    "ai_disabled", "ai_role_disabled", "ai_provider_unavailable", "ai_timeout",
    "ai_daily_limit",
}


# --- черновик модели → задание ------------------------------------------------------------


def _clean(values: list[str] | None) -> list[str]:
    return [" ".join(item.split()) for item in values or [] if item and item.strip()]


def _unique(values: list[str]) -> bool:
    return len({task_check.normalize(item) for item in values}) == len(values)


def _shuffle(size: int, seed: str) -> list[int]:
    """Перестановка для показа, стабильная для одного условия и не тождественная."""
    order = list(range(size))
    random.Random(hashlib.sha256(seed.encode()).hexdigest()).shuffle(order)
    if order == sorted(order):
        order = order[1:] + order[:1]
    return order


def _choice(draft: TaskDraft, form: StudyTaskForm) -> tuple[dict, dict] | str:
    options = _clean(draft.options)
    if not 2 <= len(options) <= 8:
        return "у выбора нужно от двух до восьми вариантов"
    if not _unique(options):
        return "варианты повторяются"
    correct = sorted({number - 1 for number in draft.correct or []})
    if not correct or any(not 0 <= index < len(options) for index in correct):
        return "номер верного варианта вне списка"
    if form == StudyTaskForm.SINGLE_CHOICE and len(correct) != 1:
        return "у выбора одного нужен ровно один верный вариант"
    if form == StudyTaskForm.MULTIPLE_CHOICE and len(correct) == len(options):
        return "все варианты верные — выбирать нечего"
    return {"options": options}, {"correct": correct}


def _blanks(draft: TaskDraft, prompt: str) -> tuple[dict, dict] | str:
    numbers = [int(item) for item in MARKER.findall(prompt)]
    answers = [_clean(item) for item in draft.blanks or []]
    if not numbers:
        return "в условии нет пропусков {{1}}"
    if numbers != list(range(1, len(numbers) + 1)):
        return "пропуски пронумерованы не по порядку"
    if len(answers) != len(numbers):
        return f"пропусков {len(numbers)}, а ключей {len(answers)}"
    if any(not item for item in answers):
        return "у пропуска нет допустимого ответа"
    return {"blanks": len(numbers)}, {"answers": answers}


def _numeric(draft: TaskDraft) -> tuple[dict, dict] | str:
    if draft.value is None or not math.isfinite(draft.value):
        return "у числового ответа ключ — не число"
    tolerance = draft.tolerance or 0.0
    if not math.isfinite(tolerance) or tolerance < 0:
        return "допуск отрицательный"
    relative = bool(draft.relative)
    if relative and tolerance >= 1:
        return "относительный допуск не меньше 100%"
    unit = (draft.unit or "").strip() or None
    return {"unit": unit}, {"value": draft.value, "tolerance": tolerance, "relative": relative}


def _ordering(draft: TaskDraft, seed: str) -> tuple[dict, dict] | str:
    steps = _clean(draft.steps)
    if not 3 <= len(steps) <= 8:
        return "в порядке нужно от трёх до восьми шагов"
    if not _unique(steps):
        return "шаги повторяются"
    shown = _shuffle(len(steps), seed)
    # Ключ — номера показанных шагов в верном порядке.
    return ({"items": [steps[index] for index in shown]},
            {"order": [shown.index(step) for step in range(len(steps))]})


def _matching(draft: TaskDraft, seed: str) -> tuple[dict, dict] | str:
    pairs = [(" ".join(item.left.split()), " ".join(item.right.split()))
             for item in draft.pairs or [] if item.left.strip() and item.right.strip()]
    if not 3 <= len(pairs) <= 8:
        return "в сопоставлении нужно от трёх до восьми пар"
    left = [item[0] for item in pairs]
    right = [item[1] for item in pairs]
    if not _unique(left) or not _unique(right):
        return "сопоставление не взаимно однозначно: части пар повторяются"
    shown = _shuffle(len(pairs), seed)
    return ({"left": left, "right": [right[index] for index in shown]},
            {"match": [shown.index(pair) for pair in range(len(pairs))]})


def _open(draft: TaskDraft) -> tuple[dict, dict] | str:
    if not (draft.reference_md or "").strip():
        return "у открытого ответа нет образца"
    return {}, {"points": _clean(draft.points)}


def prepare(draft: TaskDraft, known: set[str], basis: LessonBasis
            ) -> StudyTaskDraftRead | str:
    """Черновик модели → задание с ключом; строка — почему задание отброшено."""
    form = StudyTaskForm(draft.form)
    prompt = draft.prompt_md.strip()
    if form == StudyTaskForm.FILL_BLANKS:
        result = _blanks(draft, prompt)
    elif form in {StudyTaskForm.SINGLE_CHOICE, StudyTaskForm.MULTIPLE_CHOICE}:
        result = _choice(draft, form)
    elif form == StudyTaskForm.NUMERIC:
        result = _numeric(draft)
    elif form == StudyTaskForm.ORDERING:
        result = _ordering(draft, prompt)
    elif form == StudyTaskForm.MATCHING:
        result = _matching(draft, prompt)
    else:
        result = _open(draft)
    if isinstance(result, str):
        return result
    payload, key = result
    explanation = draft.explanation_md.strip()
    supports = [] if basis == LessonBasis.MODEL_ONLY else [
        label for label in dict.fromkeys(labels_in_order(explanation)) if label in known
    ]
    task_basis = basis if supports or basis == LessonBasis.MODEL_ONLY else LessonBasis.MODEL_ONLY
    return StudyTaskDraftRead(
        form=form, prompt_md=prompt, payload=payload, answer_key=key,
        reference_md=(draft.reference_md or "").strip() or None
        if form == StudyTaskForm.OPEN_ANSWER else None,
        # Опора показывается строкой «Опора: …», метки в тексте читателю не нужны.
        explanation_md=rewrite_citations(explanation, {}),
        hint_md=(draft.hint_md or "").strip() or None,
        difficulty=StudyTaskDifficulty(draft.difficulty), basis=task_basis, supports=supports,
    )


# --- запись -----------------------------------------------------------------------------------


def _source_snapshot(session: Session, project_id: UUID, block_ids: list[UUID]
                     ) -> tuple[list[str], list[dict[str, Any]]]:
    """Фрагменты и текст опор задания: судья открытого ответа читает их, а не урок."""
    fragment_ids: list[str] = []
    sources: list[dict[str, Any]] = []
    for block_id in block_ids:
        ref = session.scalar(select(LessonSourceRef).where(
            LessonSourceRef.block_id == block_id, LessonSourceRef.role == LessonRefRole.CONTENT,
        ))
        if ref is None:
            continue
        material = session.get(Material, ref.material_id) if ref.material_id else None
        link = session.get(ProjectMaterial, (project_id, ref.material_id)) if material else None
        text = ""
        if material is not None and link is not None and ref.region_bbox is None:
            order = refs_module.load_order(session, material, ref.page_from, ref.page_to)
            ids = refs_module.content_fragment_ids(order, refs_module.bounds_of(ref))
            fragment_ids += [str(item) for item in ids]
            texts = dict(session.execute(
                select(MaterialFragment.id, MaterialFragment.text)
                .where(MaterialFragment.id.in_(ids))
            ).tuples().all()) if ids else {}
            text = " ".join(" ".join((texts.get(item) or "").split()) for item in ids)
        sources.append({
            "material_id": str(ref.material_id) if ref.material_id else None,
            "material_name": _source_name(material, link, ref.source_name_snapshot),
            "page_from": ref.page_from, "page_to": ref.page_to,
            "text": text[:JUDGE_SOURCE_CHARS],
        })
    return fragment_ids, sources


def profile_of(brief: dict[str, Any]) -> dict[str, Any]:
    """Что судья открытого ответа знает о читателе: уровень и тема, не весь паспорт."""
    reader = brief.get("reader") or {}
    return {"starting_level": reader.get("starting_level"),
            "topic": (brief.get("topic") or {}).get("title")}


def create_task(
    session: Session, lesson: Lesson, node_id: UUID | None, task: StudyTaskDraftRead,
    source_blocks: dict[str, UUID], *, profile: dict[str, Any], run_id: UUID | None,
) -> StudyTask:
    """Активность и задание урока; блок `activity` ставит вызывающий."""
    activity = Activity(
        project_id=lesson.project_id, program_node_id=node_id, kind=ActivityKind.STUDY_TASK,
        evidence_strength=1.0, origin=ActivityOrigin.LESSON,
    )
    session.add(activity)
    session.flush()
    fragment_ids, sources = _source_snapshot(session, lesson.project_id, [
        source_blocks[label] for label in task.supports if label in source_blocks
    ])
    study = StudyTask(
        activity_id=activity.id, project_id=lesson.project_id, lesson_id=lesson.id,
        form=task.form, prompt_md=task.prompt_md, payload=task.payload,
        answer_key=task.answer_key, reference_md=task.reference_md,
        explanation_md=task.explanation_md, hint_md=task.hint_md,
        difficulty=task.difficulty, basis=task.basis,
        supporting_fragment_ids=fragment_ids,
        source_snapshot={"sources": sources, "profile": profile},
        ai_run_id=run_id,
    )
    session.add(study)
    session.flush()
    return study


class TaskPlacer:
    """Задания встают блоками `activity`: после своего блока или в конец урока.

    Несколько заданий после одного блока идут в своём порядке. С `heading` перед
    первым заданием в конце встаёт заголовок «Практика» — так делает сборка урока.
    """

    def __init__(
        self, session: Session, lesson: Lesson, node_id: UUID | None,
        source_blocks: dict[str, UUID], profile: dict[str, Any], *, heading: bool,
        edit: _Edit | None = None,
    ) -> None:
        self.session = session
        self.lesson = lesson
        self.node_id = node_id
        self.source_blocks = source_blocks
        self.profile = profile
        self.heading = heading
        self.edit = edit or _Edit(session, lesson, _ordered_blocks(session, lesson.id),
                                  LessonBlockWrite(expected_revision=lesson.revision,
                                                   operation="add_note"))
        self.last_after: dict[UUID | None, UUID] = {}

    def _end(self) -> UUID | None:
        if None in self.last_after:
            return self.last_after[None]
        if self.heading:
            title = self.edit.new_block(
                LessonBlockKind.NOTE, variant=LessonNoteVariant.HEADING,
                body_md="## Практика", origin=LessonBlockOrigin.MODEL, basis=None,
            )
            self.edit.insert(title, self.edit.blocks[-1].id if self.edit.blocks else None)
            return title.id
        return self.edit.blocks[-1].id if self.edit.blocks else None

    def _past_collapsed(self, anchor: LessonBlock) -> LessonBlock:
        """Свёрнутые под пояснением куски — его часть: задание встаёт после них."""
        position = self.edit.blocks.index(anchor)
        while (position + 1 < len(self.edit.blocks)
               and self.edit.blocks[position + 1].kind == LessonBlockKind.SOURCE
               and self.edit.blocks[position + 1].collapsed
               and anchor.kind != LessonBlockKind.SOURCE):
            position += 1
        return self.edit.blocks[position]

    def place(self, op: LessonProposalOp) -> LessonBlock | None:
        """Задание на место; `None` — блока, после которого оно стоит, больше нет."""
        assert op.task is not None
        anchor = None
        if op.block_id is not None:
            anchor = next((item for item in self.edit.blocks if item.id == op.block_id), None)
            if anchor is None:
                return None
        key = anchor.id if anchor else None
        if key is not None and key not in self.last_after:
            anchor = self._past_collapsed(anchor)
        after = self.last_after.get(key) or (anchor.id if anchor else self._end())
        study = create_task(self.session, self.lesson, self.node_id, op.task,
                            self.source_blocks, profile=self.profile, run_id=op.run_id)
        block = self.edit.new_block(
            LessonBlockKind.ACTIVITY, activity_id=study.activity_id,
            origin=LessonBlockOrigin.MODEL, basis=op.task.basis, ai_run_id=op.run_id,
        )
        self.edit.insert(block, after)
        self.last_after[key] = block.id
        return block

    def finish(self) -> None:
        self.session.flush()
        for index, block in enumerate(self.edit.blocks):
            block.sort_order = index


# --- попытки ----------------------------------------------------------------------------------


def _require_task(session: Session, project_id: UUID, lesson_id: UUID, activity_id: UUID
                  ) -> StudyTask:
    task = session.get(StudyTask, activity_id)
    if (task is None or task.project_id != project_id or task.lesson_id != lesson_id
            or task.deleted_at is not None):
        raise ProjectNotFoundError("Задание не найдено")
    return task


def _readable(task: StudyTask, answer: dict[str, Any]) -> str:
    """Ответ словами — для истории и журнала попыток."""
    payload = task.payload
    if task.form == StudyTaskForm.SINGLE_CHOICE:
        return payload["options"][answer["choice"]]
    if task.form == StudyTaskForm.MULTIPLE_CHOICE:
        return "; ".join(payload["options"][index] for index in answer["choices"]) or "—"
    if task.form == StudyTaskForm.FILL_BLANKS:
        return "; ".join(str(item or "—") for item in answer["blanks"])
    if task.form == StudyTaskForm.NUMERIC:
        return f"{answer['value']} {payload.get('unit') or ''}".strip()
    if task.form == StudyTaskForm.ORDERING:
        return " → ".join(payload["items"][index] for index in answer["order"])
    return "; ".join(
        f"{left} → {payload['right'][index] if index is not None else '—'}"
        for left, index in zip(payload["left"], answer["pairs"], strict=True)
    )


def _judge_snapshot(task: StudyTask, text: str) -> dict[str, Any]:
    points = task.answer_key.get("points") or []
    reference = task.reference_md or ""
    if points:
        reference += "\n\nПункты, которые должны быть в ответе:\n" + "\n".join(
            f"- {item}" for item in points)
    snapshot = task.source_snapshot or {}
    return {
        "question": task.prompt_md,
        "reference_text": reference,
        "profile": snapshot.get("profile") or {},
        "fragments": [
            {"material_name": item["material_name"], "page_from": item["page_from"],
             "page_to": item["page_to"], "text": item["text"]}
            for item in snapshot.get("sources", []) if item.get("text")
        ],
        "manifest": [{"kind": "study_task", "id": str(task.activity_id)}],
        "answer": {"text": text},
    }


def _points(values: list[Any]) -> list[dict[str, Any]]:
    return [{"point": item.point, "quote": item.quote} for item in values]


async def _judge(session: Session, gateway: ModelGateway, task: StudyTask, attempt: Attempt
                 ) -> Grade | None:
    """Открытый ответ — судье экзамена; без моделей оценки нет, ответ ждёт проверки."""
    try:
        judged = await judge_attempt(gateway, attempt)
    except AiGatewayError as error:
        # Как у экзамена: отказ шлюза оставляет только транзакцию чтения — закрыть её.
        session.commit()
        if error.code in AI_PENDING_CODES:
            return None
        raise
    with project_write_transaction(session, task.project_id):
        grade = Grade(
            attempt_id=attempt.id, outcome=judged.outcome, method=GradeMethod.AI_JUDGE,
            credited_points=_points(judged.credited), missed_points=_points(judged.missed),
            wrong_points=_points(judged.wrong), summary=judged.summary,
            ai_run_id=judged.ai_run_id,
        )
        session.add(grade)
        session.flush()
        return grade


async def submit_attempt(
    session: Session, gateway: ModelGateway, project_id: UUID, lesson_id: UUID,
    activity_id: UUID, command: StudyTaskAttemptWrite,
) -> StudyTaskAttemptRead:
    """Попытка задания: ключ проверяет сразу, открытый ответ — модель или позже."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        _require_lesson(session, project_id, lesson_id)
        task = _require_task(session, project_id, lesson_id, activity_id)
        is_open = task.form == StudyTaskForm.OPEN_ANSWER
        if is_open:
            text = (command.text or "").strip()
            if not text:
                raise ProjectDomainError("Напишите ответ", status=422, code="study_task_answer")
            answer: dict[str, Any] = {"text": text}
            result = None
            snapshot = _judge_snapshot(task, text)
        else:
            answer = command.answer or {}
            try:
                result = task_check.check(task.form, task.payload, task.answer_key, answer)
            except task_check.AnswerShapeError as error:
                raise ProjectDomainError(
                    f"Ответ не той формы: {error}", status=422, code="study_task_answer",
                ) from error
            text = _readable(task, answer)
            snapshot = {"question": task.prompt_md, "answer": answer,
                        "manifest": [{"kind": "study_task", "id": str(task.activity_id)}]}
        ordinal = (session.scalar(
            select(func.max(Attempt.ordinal)).where(Attempt.activity_id == activity_id)
        ) or 0) + 1
        attempt = Attempt(
            project_id=project_id, activity_id=activity_id, ordinal=ordinal,
            answer_mode="study_task", active_seconds=command.active_seconds, text=text,
            persona=ExaminerPersona.NEUTRAL_EXAMINER, strictness=ExaminerStrictness.NORMAL,
            context_snapshot={**snapshot, "lesson_id": str(lesson_id), "form": task.form.value},
        )
        session.add(attempt)
        session.flush()
        grade = None
        if result is not None:
            grade = Grade(
                attempt_id=attempt.id, outcome=result.outcome, method=GradeMethod.EXACT_MATCH,
                credited_points=[], missed_points=[], wrong_points=[], summary=result.summary,
            )
            session.add(grade)
            session.flush()
    if is_open:
        grade = await _judge(session, gateway, task, attempt)
    return attempt_read(task, attempt, grade)


async def check_pending(
    session: Session, gateway: ModelGateway, project_id: UUID, lesson_id: UUID,
    activity_id: UUID, attempt_id: UUID,
) -> StudyTaskAttemptRead:
    """Открытый ответ, сохранённый без моделей, — проверить сейчас."""
    with session.begin():
        _require_lessons_project(session, project_id, writable=True)
        task = _require_task(session, project_id, lesson_id, activity_id)
        attempt = session.get(Attempt, attempt_id)
        if attempt is None or attempt.activity_id != activity_id:
            raise ProjectNotFoundError("Попытка не найдена")
        grade = session.get(Grade, attempt.id)
    if grade is None:
        grade = await _judge(session, gateway, task, attempt)
    return attempt_read(task, attempt, grade)


def list_attempts(session: Session, project_id: UUID, lesson_id: UUID, activity_id: UUID
                  ) -> list[StudyTaskAttemptRead]:
    _require_lessons_project(session, project_id, writable=False)
    task = _require_task(session, project_id, lesson_id, activity_id)
    rows = session.execute(
        select(Attempt, Grade).outerjoin(Grade, Grade.attempt_id == Attempt.id)
        .where(Attempt.activity_id == activity_id).order_by(Attempt.ordinal.desc())
    ).tuples()
    return [attempt_read(task, attempt, grade) for attempt, grade in rows]
