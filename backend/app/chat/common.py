"""Общая запись сессий, черновиков и сообщений чата — независимая от домена
(exam или program). Вынесено из `app.exam.chat`, чтобы чат построения
программы учебника (`app.projects.program_chat`) не копировал разметку
строки чата: только предметная логика (гейты, контекст, промпты) остаётся
своей у каждого домена.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ChatMessage,
    ChatMessageRole,
    ChatPayloadKind,
    ChatSession,
    ChatStreamState,
    utc_now,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


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
    skill: str | None
    ai_run_id: UUID | None
    attempt_id: UUID | None
    grade_attempt_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ManifestEntryRead(BaseModel):
    # Записи манифеста несут kind-специфичные поля (revision, sha256, count) —
    # эта схема отдаёт только то, что нужно чипу, и не падает на лишних ключах.
    model_config = ConfigDict(extra="ignore")

    kind: str
    id: str | None = None
    included: bool
    truncated: bool = False
    bytes: int = 0
    count: int | None = None
    reason: str | None = None
    # Program-чат группирует записи источников по флагу контекста и подписывает
    # их именем источника — exam-контекст эти поля не заполняет (остаются None).
    flag_key: str | None = None
    label: str | None = None


def message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead.model_validate(message)


def append_message_row(
    session: Session,
    chat: ChatSession,
    *,
    role: ChatMessageRole,
    text: str = "",
    stream_state: ChatStreamState = ChatStreamState.COMPLETE,
    payload_kind: ChatPayloadKind = ChatPayloadKind.NONE,
    payload: dict[str, Any] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    skill: str | None = None,
    ai_run_id: UUID | None = None,
    attempt_id: UUID | None = None,
    grade_attempt_id: UUID | None = None,
    message_id: UUID | None = None,
) -> ChatMessage:
    """Raw insert, no transaction of its own — caller must already be inside one.

    SQLAlchemy autobegins a transaction on the session's first read, so a
    second `with session.begin():` inside the same request raises "A
    transaction is already begun". Compound flows (build context, then
    append) call this directly inside their own single `with session.begin():`;
    `append_message` below stays the transactional entry point for callers
    that touch nothing else on the session first.
    """
    next_sequence = session.scalar(
        select(func.coalesce(func.max(ChatMessage.sequence), 0) + 1).where(
            ChatMessage.session_id == chat.id
        )
    )
    message = ChatMessage(
        id=message_id or uuid4(),
        session_id=chat.id,
        sequence=next_sequence,
        role=role,
        text=text,
        stream_state=stream_state,
        payload_kind=payload_kind,
        payload=payload or {},
        context_snapshot=context_snapshot or {},
        skill=skill,
        ai_run_id=ai_run_id,
        attempt_id=attempt_id,
        grade_attempt_id=grade_attempt_id,
    )
    session.add(message)
    chat.updated_at = utc_now()
    session.flush()
    session.refresh(message)
    return message


def append_message(session: Session, chat: ChatSession, **fields: Any) -> ChatMessage:
    with session.begin():
        return append_message_row(session, chat, **fields)


def save_draft_text(session: Session, chat: ChatSession, text: str) -> ChatSession:
    chat.draft_text = text
    chat.updated_at = utc_now()
    session.flush()
    session.refresh(chat)
    return chat


def message_counts(session: Session, session_ids: Sequence[UUID]) -> dict[UUID, int]:
    if not session_ids:
        return {}
    return dict(
        session.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_(session_ids))
            .group_by(ChatMessage.session_id)
        ).all()
    )
