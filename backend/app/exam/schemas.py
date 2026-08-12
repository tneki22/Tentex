from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import (
    AttemptOutcome,
    ChatMessageRole,
    ChatPayloadKind,
    ChatStreamState,
    ExaminerPersona,
    ExaminerStrictness,
    GradeMethod,
)

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ChatSessionCreateWrite(ApiModel):
    program_node_id: UUID


class ChatSessionSummary(ApiModel):
    id: UUID
    project_id: UUID
    program_node_id: UUID
    title: str
    updated_at: datetime
    message_count: int
    # В итерации 1 разбор ответа виден только внутри чата: последний итог по
    # сессии на уровне списка чатов приезжает вместе с историей попыток (1b+).
    last_outcome: str | None = None


class ChatMessageRead(ApiModel):
    id: UUID
    session_id: UUID
    sequence: int
    role: ChatMessageRole
    text: str
    stream_state: ChatStreamState
    payload_kind: ChatPayloadKind
    payload: dict[str, Any]
    context_snapshot: dict[str, Any]
    ai_run_id: UUID | None
    attempt_id: UUID | None
    grade_attempt_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ChatSessionDetail(ApiModel):
    id: UUID
    project_id: UUID
    program_node_id: UUID
    section_scope_node_id: UUID | None
    title: str
    persona: ExaminerPersona
    strictness: ExaminerStrictness
    draft_text: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageRead]


class ChatDraftWrite(ApiModel):
    text: str = Field(max_length=200_000)


class ChatContextRead(ApiModel):
    node_id: UUID
    question: str
    reference_included: bool
    material_count: int
    tail_limit: int


class ChatDraftRead(ApiModel):
    text: str
    updated_at: datetime


class ChatMessageWrite(ApiModel):
    text: NonBlank = Field(max_length=20_000)


class ChatAnswerWrite(ApiModel):
    text: NonBlank = Field(max_length=50_000)


class RubricPointRead(ApiModel):
    point: str
    quote: str | None = None
    quote_start: int | None = None
    quote_end: int | None = None


class AttemptRead(ApiModel):
    id: UUID
    project_id: UUID
    program_node_id: UUID
    parent_attempt_id: UUID | None
    ordinal: int
    text: str
    persona: ExaminerPersona
    strictness: ExaminerStrictness
    context_snapshot: dict[str, Any]
    created_at: datetime


class GradeUsageRead(ApiModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    provider_cached_tokens: int = 0
    actual_cost_usd: Decimal | None = Decimal("0")
    actual_cost_rub: Decimal | None = Decimal("0")


class GradeRead(ApiModel):
    attempt_id: UUID
    outcome: AttemptOutcome
    method: GradeMethod | None
    credited_points: list[RubricPointRead]
    missed_points: list[RubricPointRead]
    wrong_points: list[RubricPointRead]
    summary: str
    self_assessment: AttemptOutcome | None
    ai_run_id: UUID | None
    actual_model_id: str | None
    usage: GradeUsageRead
    cached: bool
    created_at: datetime
    updated_at: datetime


class AttemptSummaryRead(ApiModel):
    id: UUID
    ordinal: int
    created_at: datetime
    outcome: AttemptOutcome | None
    method: GradeMethod | None
    self_assessment: AttemptOutcome | None
    text_preview: str


class AttemptDetailRead(ApiModel):
    attempt: AttemptRead
    grade: GradeRead | None


class SelfAssessmentWrite(ApiModel):
    outcome: AttemptOutcome


class ChatAnswerResult(ApiModel):
    messages: list[ChatMessageRead]
    attempt: AttemptRead
    grade: GradeRead
