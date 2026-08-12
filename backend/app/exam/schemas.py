from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import (
    ChatMessageRole,
    ChatPayloadKind,
    ChatStreamState,
    ExaminerPersona,
    ExaminerStrictness,
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
    tail_count: int


class ChatMessageWrite(ApiModel):
    text: NonBlank = Field(max_length=20_000)


class ChatAnswerWrite(ApiModel):
    text: NonBlank = Field(max_length=50_000)


class ChatAnswerResult(ApiModel):
    messages: list[ChatMessageRead]
