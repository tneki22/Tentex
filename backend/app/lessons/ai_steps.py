"""Уровни «Обычный» и «Подробный»: план, шаги по одному вызову, рецензент.

План — один вызов по компактной карте кусков `C1…Cn`. Шаг — вызов с полным
текстом своих кусков (метки `S1…Sk` внутри вызова), планом и итогами уже
написанных шагов; ответ шага сразу переводится в метки общего списка кусков.
Каждый готовый шаг пишется в `checkpoint`: упавшая задача продолжается с того
же шага, оплаченные ответы не теряются. У «Подробного» рецензент читает
черновик целиком и называет до восьми проблем четырёх видов; переписываются
не больше трёх шагов.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.gateway import AiResult, AiTextRequest, ModelGateway
from app.ai.job_budget import JobBudget, spent
from app.ai.schemas import AiMessage, AiModelSelection
from app.db import job_write_transaction
from app.lessons import ai_context
from app.lessons import candidates as candidates_module
from app.lessons.ai_prompts import (
    REVIEW_PROBLEMS,
    STEP_KINDS,
    LessonPlan,
    LessonReview,
    StepText,
    plan_instructions,
    review_instructions,
    step_instructions,
)
from app.lessons.ai_schemas import LessonAiBuildResult, LessonAiBuildWrite
from app.lessons.ai_writer import (
    LessonDraft,
    NoteItem,
    SourceItem,
    existing_result,
    labels_in_order,
    rewrite_citations,
    save_lesson,
)
from app.lessons.candidates import Candidate
from app.models import BackgroundJob

ROLE = "lesson_builder"
MAP_HEAD_WORDS = 120
REVIEW_HEAD_WORDS = 200
#: Полный текст кусков шага и их соседей в одном вызове.
STEP_SOURCE_TOKENS = 4_500
PLAN_OUTPUT_TOKENS = 3_000
STEP_OUTPUT_TOKENS = {"standard": 2_000, "detailed": 3_000}
REVIEW_OUTPUT_TOKENS = 3_000
MAX_REWRITES = 3


# --- метки ------------------------------------------------------------------------------


def global_label(index: int) -> str:
    """Метка куска в общем списке задачи: ими пишутся шаги и опоры урока."""
    return f"S{index + 1}"


def plan_index(label: str, count: int) -> int | None:
    """`C4` карты плана → индекс куска; чужая метка — `None`."""
    if not label.startswith("C") or not label[1:].isdigit():
        return None
    index = int(label[1:]) - 1
    return index if 0 <= index < count else None


def sanitize_plan(plan: LessonPlan, count: int, basis: str) -> tuple[LessonPlan, list[str]]:
    """Опоры шагов — только куски карты; при основе без материалов их нет вовсе."""
    dropped: list[str] = []
    steps = []
    for number, step in enumerate(plan.steps, start=1):
        kept = []
        for label in step.sources:
            if basis == "model_only":
                continue
            if plan_index(label, count) is None:
                dropped.append(f"Шаг {number}: опоры {label} не было в карте")
            elif label not in kept:
                kept.append(label)
        steps.append(step.model_copy(update={"sources": kept}))
    return plan.model_copy(update={"steps": steps}), dropped


# --- промпты ----------------------------------------------------------------------------


def _map_text(items: list[Candidate]) -> str:
    """Карта кусков для плана: шапка и начало каждого, в порядке учебника."""
    if not items:
        return "(материалов нет)"
    return "\n\n---\n\n".join(
        f"{candidates_module.header(item, f'C{index}')}\n"
        f"{candidates_module.head_text(item.text, MAP_HEAD_WORDS)}"
        for index, item in enumerate(items, start=1)
    )


def _plan_text(plan: LessonPlan, current: int | None = None) -> str:
    lines = [
        f"Урок «{plan.title}». Цель: {plan.goal}",
        "Понятия по порядку: " + (" → ".join(plan.concepts) or "не указаны"),
    ]
    for number, step in enumerate(plan.steps, start=1):
        label = STEP_KINDS[step.kind][0]
        marker = "  ← сейчас" if current == number - 1 else ""
        lines.append(f"{number}. [{label}] {step.title} — {step.intent}{marker}")
    return "\n".join(lines)


def _manifest(stage: str, brief: dict[str, Any], labels: dict[str, Candidate]) -> list[dict]:
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
            for label, item in labels.items()
        ),
    ]


def plan_request(
    project_id: UUID, brief: dict[str, Any], items: list[Candidate], model: AiModelSelection,
    **context: Any,
) -> AiTextRequest[LessonPlan]:
    order = brief["order"]
    user = (
        f"<brief>\n{ai_context.render_brief(brief)}\n</brief>\n\n"
        f"<sources>\n{_map_text(items)}\n</sources>\n\n"
        "Составь план урока по теме из паспорта."
    )
    return AiTextRequest(
        role=ROLE,
        messages=[
            AiMessage(role="system", content=plan_instructions(
                order["template"], order["level"], order["basis"])),
            AiMessage(role="user", content=user),
        ],
        response_model=LessonPlan,
        project_id=project_id,
        context_manifest=_manifest(
            "plan", brief, {f"C{i}": item for i, item in enumerate(items, start=1)}
        ),
        request_model_override=model,
        confirmed=True,
        parameters={"max_output_tokens": PLAN_OUTPUT_TOKENS},
        **context,
    )


def _step_sources(
    plan: LessonPlan, index: int, items: list[Candidate]
) -> dict[str, int]:
    """Куски шага и их соседи по учебнику: локальная метка → индекс в общем списке."""
    chosen: list[int] = []
    for label in plan.steps[index].sources:
        position = plan_index(label, len(items))
        if position is not None and position not in chosen:
            chosen.append(position)
    used = sum(items[position].tokens for position in chosen)
    for position in list(chosen):
        neighbour = position + 1
        if (
            neighbour < len(items)
            and neighbour not in chosen
            and items[neighbour].material_id == items[position].material_id
            and used + items[neighbour].tokens <= STEP_SOURCE_TOKENS
        ):
            chosen.append(neighbour)
            used += items[neighbour].tokens
    return {f"S{number}": position for number, position in enumerate(chosen, start=1)}


def _concepts_text(brief: dict[str, Any], plan: LessonPlan, index: int) -> str:
    known = brief["known"]["concepts"] + [
        concept for step in plan.steps[:index] for concept in step.introduces
    ]
    later = [concept for step in plan.steps[index + 1 :] for concept in step.introduces]
    return "\n".join([
        "Уже известно: " + ("; ".join(known) or "ничего"),
        "Вводит этот шаг: " + ("; ".join(plan.steps[index].introduces) or "новых понятий нет"),
        "Введут позже — не опережай: " + ("; ".join(later) or "ничего"),
    ])


def _written_text(plan: LessonPlan, index: int, done: dict[str, dict]) -> str:
    previous = done.get(str(index - 1))
    lines = []
    if previous:
        lines.append(f"Предыдущий шаг целиком:\n{previous['body_md']}")
    summaries = [
        f"{number + 1}. {plan.steps[number].title}: {done[str(number)]['summary']}"
        for number in range(len(plan.steps))
        if str(number) in done and number not in {index, index - 1}
    ]
    if summaries:
        lines.append("Итоги остальных готовых шагов:\n" + "\n".join(summaries))
    return "\n\n".join(lines) or "Это первый шаг."


def step_request(
    project_id: UUID, brief: dict[str, Any], plan: LessonPlan, index: int,
    done: dict[str, dict], items: list[Candidate], model: AiModelSelection,
    *, note: str | None = None, **context: Any,
) -> tuple[AiTextRequest[StepText], dict[str, int]]:
    order = brief["order"]
    local = _step_sources(plan, index, items)
    sources = "\n\n---\n\n".join(
        f"{candidates_module.header(items[position], label)}\n{items[position].text}"
        for label, position in local.items()
    ) or "(у шага нет опор — пиши из знаний и не ставь ссылок)"
    step = plan.steps[index]
    user = "\n\n".join([
        f"<brief>\n{ai_context.render_brief(brief, compact=True)}\n</brief>",
        f"<plan>\n{_plan_text(plan, index)}\n</plan>",
        f"<concepts>\n{_concepts_text(brief, plan, index)}\n</concepts>",
        f"<written>\n{_written_text(plan, index, done)}\n</written>",
        f"<sources>\n{sources}\n</sources>",
        *([f"<review>\nЗамечание рецензента к этому шагу: {note}\n"
           "Перепиши шаг так, чтобы замечание было исправлено.\n</review>"] if note else []),
        f"Напиши шаг {index + 1} «{step.title}»: {step.intent}",
    ])
    request = AiTextRequest(
        role=ROLE,
        messages=[
            AiMessage(role="system", content=step_instructions(
                order["template"], order["level"], order["basis"])),
            AiMessage(role="user", content=user),
        ],
        response_model=StepText,
        project_id=project_id,
        context_manifest=_manifest(
            "rewrite" if note else "step", brief,
            {label: items[position] for label, position in local.items()},
        ) + [{"kind": "step", "index": index}],
        request_model_override=model,
        confirmed=True,
        parameters={"max_output_tokens": STEP_OUTPUT_TOKENS[order["level"]]},
        **context,
    )
    return request, local


def review_request(
    project_id: UUID, brief: dict[str, Any], plan: LessonPlan, done: dict[str, dict],
    items: list[Candidate], model: AiModelSelection, **context: Any,
) -> AiTextRequest[LessonReview]:
    draft = "\n\n".join(
        f"### Шаг {number + 1} · {plan.steps[number].title}\n{done[str(number)]['body_md']}"
        for number in range(len(plan.steps))
        if str(number) in done
    )
    cited = sorted({
        int(label[1:]) - 1
        for step in done.values()
        for label in step.get("labels", [])
    })
    heads = "\n\n---\n\n".join(
        f"{candidates_module.header(items[position], global_label(position))}\n"
        f"{candidates_module.head_text(items[position].text, REVIEW_HEAD_WORDS)}"
        for position in cited
        if position < len(items)
    ) or "(опор нет)"
    user = "\n\n".join([
        f"<brief>\n{ai_context.render_brief(brief, compact=True)}\n</brief>",
        f"<plan>\n{_plan_text(plan)}\n</plan>",
        f"<draft>\n{draft}\n</draft>",
        f"<sources>\n{heads}\n</sources>",
        "Найди проблемы черновика.",
    ])
    return AiTextRequest(
        role=ROLE,
        messages=[
            AiMessage(role="system", content=review_instructions()),
            AiMessage(role="user", content=user),
        ],
        response_model=LessonReview,
        project_id=project_id,
        context_manifest=_manifest(
            "review", brief, {global_label(position): items[position] for position in cited
                              if position < len(items)},
        ),
        request_model_override=model,
        confirmed=True,
        parameters={"max_output_tokens": REVIEW_OUTPUT_TOKENS},
        **context,
    )


# --- выполнение -------------------------------------------------------------------------


def update_checkpoint(session: Session, job_id: UUID, **values: Any) -> BackgroundJob:
    with job_write_transaction(session, job_id):
        job = session.get(BackgroundJob, job_id)
        assert job is not None
        checkpoint = dict(job.checkpoint)
        checkpoint.update(values)
        job.checkpoint = checkpoint
        if "done" in values:
            job.done = values["done"]
        if "total" in values:
            job.total = values["total"]
        session.flush()
        return job


def _cancelled(session: Session, job_id: UUID) -> bool:
    session.expire_all()
    job = session.get(BackgroundJob, job_id)
    return job is None or job.pause_requested


class Runner:
    """Один вызов модели задачи: общий предел, запись run_id."""

    def __init__(self, session: Session, gateway: ModelGateway, job: BackgroundJob) -> None:
        self.session = session
        self.gateway = gateway
        self.job_id = job.id
        self.project_id = job.project_id
        self.model = AiModelSelection.model_validate(job.checkpoint["model"])
        self.budget = JobBudget(session, job.id)

    @property
    def context(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "budget_context": self.budget}

    async def call[T: BaseModel](self, request: AiTextRequest[T]) -> AiResult[T]:
        result = await self.gateway.complete(request)
        self.session.expire_all()
        job = self.session.get(BackgroundJob, self.job_id)
        assert job is not None
        run_ids = [*job.checkpoint.get("run_ids", []), str(result.run_id)]
        update_checkpoint(
            self.session, self.job_id, run_ids=run_ids, actual_model_id=result.actual_model_id,
        )
        return result


async def make_plan(
    runner: Runner, brief: dict[str, Any], items: list[Candidate]
) -> tuple[LessonPlan, list[str]]:
    result = await runner.call(plan_request(
        runner.project_id, brief, items, runner.model, **runner.context,
    ))
    return sanitize_plan(result.value, len(items), brief["order"]["basis"])


def _to_global(body: str, local: dict[str, int]) -> tuple[str, list[str], list[str]]:
    """Локальные метки шага → метки общего списка; меток вне вызова не бывает — они убираются."""
    mapping = {label: global_label(position) for label, position in local.items()}
    found = labels_in_order(body)
    unknown = [label for label in found if label not in mapping]
    labels = list(dict.fromkeys(mapping[label] for label in found if label in mapping))
    return rewrite_citations(body, mapping), labels, unknown


async def write_step(
    runner: Runner, brief: dict[str, Any], plan: LessonPlan, index: int,
    done: dict[str, dict], items: list[Candidate], note: str | None = None,
) -> dict[str, Any]:
    request, local = step_request(
        runner.project_id, brief, plan, index, done, items, runner.model,
        note=note, **runner.context,
    )
    result = await runner.call(request)
    body, labels, unknown = _to_global(result.value.body_md, local)
    return {
        "variant": result.value.variant,
        "body_md": body,
        "summary": result.value.summary,
        "labels": labels,
        "unknown": unknown,
        "run_id": str(result.run_id),
    }


def _assemble(plan: LessonPlan, done: dict[str, dict], template: str, count: int,
              dropped: list[str]) -> LessonDraft:
    """Шаги в порядке плана: заголовок шага, пояснение и его куски учебника."""
    material_first = template == "guide"
    draft = LessonDraft(goal=plan.goal, concepts=list(plan.concepts), dropped=list(dropped))
    for index, step in enumerate(plan.steps):
        text = done.get(str(index))
        if text is None:
            continue
        if text.get("unknown"):
            draft.dropped.append(
                f"Шаг {index + 1}: ссылки вне его опор убраны: " + ", ".join(text["unknown"])
            )
        run_id = UUID(text["run_id"]) if text.get("run_id") else None
        sources = [
            SourceItem(global_label(position), step.collapsed)
            for label in step.sources
            if (position := plan_index(label, count)) is not None
        ]
        draft.items.append(NoteItem("heading", step.title, run_id))
        if material_first:
            draft.items.extend(sources)
        draft.items.append(NoteItem(text["variant"], text["body_md"], run_id))
        if not material_first:
            draft.items.extend(sources)
    return draft


def planned_calls(level: str, steps: int) -> int:
    """Вызовов по плану: шаги, у «Подробного» ещё рецензент и до трёх правок."""
    return steps + (1 + MAX_REWRITES if level == "detailed" else 0)


async def run_staged(
    session: Session, gateway: ModelGateway, job_id: UUID
) -> LessonAiBuildResult:
    """Сборка по плану с чекпоинтом на шаг; повтор задачи продолжает с места сбоя."""
    job = session.get(BackgroundJob, job_id)
    assert job is not None and job.project_id is not None
    if (ready := existing_result(session, job)) is not None:
        return ready
    command = LessonAiBuildWrite.model_validate(job.checkpoint["command"])
    brief = job.checkpoint["brief"]
    items = [Candidate.from_json(item) for item in job.checkpoint["candidates"]]
    runner = Runner(session, gateway, job)

    dropped = list(job.checkpoint.get("plan_dropped") or [])
    if job.checkpoint.get("plan") is None:
        plan, plan_dropped = await make_plan(runner, brief, items)
        dropped += plan_dropped
        job = update_checkpoint(session, job_id, plan=plan.model_dump(mode="json"),
                                plan_dropped=dropped)
    plan = LessonPlan.model_validate(job.checkpoint["plan"])
    total = 1 + planned_calls(command.level, len(plan.steps))
    done: dict[str, dict] = dict(job.checkpoint.get("steps") or {})
    update_checkpoint(session, job_id, total=total, done=1 + len(done))

    for index in range(len(plan.steps)):
        if str(index) in done:
            continue
        if _cancelled(session, job_id):
            return LessonAiBuildResult(lesson_id=None, dropped=[], cost_usd=None)
        done[str(index)] = await write_step(runner, brief, plan, index, done, items)
        update_checkpoint(session, job_id, steps=done, done=1 + len(done))

    if command.level == "detailed":
        job = session.get(BackgroundJob, job_id)
        review = job.checkpoint.get("review")
        if review is None:
            result = await runner.call(review_request(
                job.project_id, brief, plan, done, items, runner.model, **runner.context,
            ))
            review = result.value.model_dump(mode="json")
            job = update_checkpoint(session, job_id, review=review, done=2 + len(done))
        rewritten = list(job.checkpoint.get("rewritten") or [])
        issues = LessonReview.model_validate(review).issues
        for number in sorted({issue.step for issue in issues})[:MAX_REWRITES]:
            index = number - 1
            if index >= len(plan.steps) or index in rewritten or str(index) not in done:
                continue
            if _cancelled(session, job_id):
                return LessonAiBuildResult(lesson_id=None, dropped=[], cost_usd=None)
            comments = "; ".join(
                f"{REVIEW_PROBLEMS[issue.problem]}: {issue.comment}"
                for issue in issues if issue.step == number
            )
            others = {key: value for key, value in done.items() if key != str(index)}
            done[str(index)] = await write_step(
                runner, brief, plan, index, others, items, note=comments,
            )
            rewritten.append(index)
            update_checkpoint(session, job_id, steps=done, rewritten=rewritten,
                              done=2 + len(done) + len(rewritten))

    if _cancelled(session, job_id):
        return LessonAiBuildResult(lesson_id=None, dropped=[], cost_usd=None)
    job = session.get(BackgroundJob, job_id)
    draft = _assemble(plan, done, command.template, len(items), dropped)
    draft.run_ids = [UUID(item) for item in job.checkpoint.get("run_ids", [])]
    cost = spent(job.checkpoint.get("budget") or {})
    model_id = str(job.checkpoint.get("actual_model_id") or runner.model.model_id)
    return save_lesson(session, job, draft, model_id=model_id, cost=Decimal(cost))
