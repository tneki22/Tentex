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

from app.ai.schemas import AiChatPreset
from app.ai.settings import model_display_name, store_chat_preset
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
    preview: list[str] = []


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
    client_turn_id: str | None = None,
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
        client_turn_id=client_turn_id,
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


def apply_model_choice(
    session: Session,
    chat: ChatSession,
    *,
    selection: dict[str, Any] | None,
    parameters: dict[str, Any] | None,
) -> None:
    """Смена модели чата: запись выбора, отметка в ленте и обновление пресета.

    Общая для обоих чатов — расходится у них только проверка возможностей
    модели, которая делается до вызова. Внутри чужой транзакции, своей не
    открывает.
    """
    before = chat.model_override
    chat.model_override = selection
    chat.model_parameters = parameters
    if selection != before:
        _note_model_switch(session, chat, before=before, after=selection)
        store_chat_preset(
            session,
            None
            if selection is None
            else AiChatPreset(
                provider_id=UUID(str(selection["provider_id"])),
                model_id=str(selection["model_id"]),
                parameters=parameters or {},
            ),
        )


def _note_model_switch(
    session: Session,
    chat: ChatSession,
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Строка «было → стало» в ленте.

    Только в непустом чате: в пустом отмечать нечего, а начинать переписку
    служебной строкой незачем. Имена резолвятся сейчас, а не при чтении, по
    той же причине, по которой сам выбор хранится снимком: подключение
    провайдера могут удалить позже, а запись должна остаться читаемой.
    """
    has_messages = session.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == chat.id)
    )
    if not has_messages:
        return
    append_message_row(
        session,
        chat,
        role=ChatMessageRole.SYSTEM,
        text=(
            f"Модель: {model_display_name(session, before)}"
            f" → {model_display_name(session, after)}"
        ),
    )


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
