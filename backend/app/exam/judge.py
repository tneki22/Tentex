"""Структурная ИИ-проверка попытки с верификацией цитат на сервере."""

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.schemas import AiMessage, AiModelSelection, AiUsage
from app.exam.checking import RubricPoint, locate_quote
from app.exam.prompts import ANSWER_JUDGE_SYSTEM_PROMPT
from app.models import Attempt, AttemptOutcome, ExaminerPersona, ExaminerStrictness


class JudgePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=400),
    ]
    quote: str = Field(default="", max_length=1000)


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["passed", "partial", "failed"]
    credited: list[JudgePoint] = Field(default_factory=list, max_length=20)
    missed: list[JudgePoint] = Field(default_factory=list, max_length=20)
    wrong: list[JudgePoint] = Field(default_factory=list, max_length=20)
    summary: str = Field(default="", max_length=2000)


@dataclass(frozen=True)
class JudgeResult:
    outcome: AttemptOutcome
    credited: list[RubricPoint]
    missed: list[RubricPoint]
    wrong: list[RubricPoint]
    summary: str
    ai_run_id: UUID
    actual_model_id: str
    usage: AiUsage
    cached: bool


PERSONA_LABELS = {
    ExaminerPersona.CALM_TEACHER: "спокойный преподаватель",
    ExaminerPersona.NEUTRAL_EXAMINER: "нейтральный экзаменатор",
    ExaminerPersona.STRICT_REVIEWER: "строгий рецензент",
}

STRICTNESS_LABELS = {
    ExaminerStrictness.SOFT: "мягкая",
    ExaminerStrictness.NORMAL: "обычная",
    ExaminerStrictness.STRICT: "строгая",
}


def _data_block(name: str, value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"<{name}_data>\n{payload}\n</{name}_data>"


def _messages(attempt: Attempt) -> list[AiMessage]:
    snapshot = attempt.context_snapshot
    system = (
        f"{ANSWER_JUDGE_SYSTEM_PROMPT}\n\n"
        f"Персона: {PERSONA_LABELS[attempt.persona]}. "
        f"Строгость: {STRICTNESS_LABELS[attempt.strictness]}."
    )
    blocks = [_data_block("question", snapshot.get("question", ""))]
    profile = snapshot.get("profile")
    if profile:
        blocks.append(_data_block("profile", profile))
    blocks.append(_data_block("reference", snapshot.get("reference_text")))
    blocks.append(_data_block("fragment", snapshot.get("fragments", [])))
    blocks.append(_data_block("answer", attempt.text))
    user = "\n\n".join(blocks)
    return [AiMessage(role="system", content=system), AiMessage(role="user", content=user)]


def _rubric_points(answer: str, points: list[JudgePoint]) -> list[RubricPoint]:
    verified: list[RubricPoint] = []
    for item in points:
        location = locate_quote(answer, item.quote)
        verified.append(
            RubricPoint(
                point=item.point,
                quote=item.quote or None,
                quote_start=location[0] if location is not None else None,
                quote_end=location[1] if location is not None else None,
            )
        )
    return verified


def _model_override(snapshot: dict) -> AiModelSelection | None:
    raw = snapshot.get("model_override")
    if not raw:
        return None
    return AiModelSelection(provider_id=raw["provider_id"], model_id=raw["model_id"])


async def judge_attempt(gateway: ModelGateway, attempt: Attempt) -> JudgeResult:
    """Судит один неизменяемый снимок попытки и проверяет все цитаты локально."""
    snapshot = attempt.context_snapshot
    manifest = snapshot.get("manifest", [])
    if not isinstance(manifest, list):
        manifest = []
    result = await gateway.complete(
        AiTextRequest(
            role="exam_answer_judge",
            messages=_messages(attempt),
            response_model=JudgeVerdict,
            project_id=attempt.project_id,
            context_manifest=manifest,
            request_model_override=_model_override(snapshot),
            source_fingerprint={
                "program_node_id": str(attempt.program_node_id),
                "answer_sha256": hashlib.sha256(attempt.text.encode()).hexdigest(),
                "reference_revision": snapshot.get("reference_revision"),
            },
        )
    )
    return JudgeResult(
        outcome=AttemptOutcome(result.value.outcome),
        credited=_rubric_points(attempt.text, result.value.credited),
        missed=_rubric_points(attempt.text, result.value.missed),
        wrong=_rubric_points(attempt.text, result.value.wrong),
        summary=result.value.summary,
        ai_run_id=result.run_id,
        actual_model_id=result.actual_model_id,
        usage=result.usage,
        cached=result.cached,
    )
