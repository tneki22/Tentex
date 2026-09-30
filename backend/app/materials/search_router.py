"""Проектно-независимые сессии поиска для Библиотеки."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import ModelGateway
from app.chat import common as chat_common
from app.chat import project_sessions
from app.db import get_session
from app.projects import source_search_chat

router = APIRouter(prefix="/api/library/source-search-chat/sessions", tags=["materials"])
Db = Annotated[Session, Depends(get_session)]
Gateway = Annotated[ModelGateway, Depends(get_model_gateway)]
CHANNEL = source_search_chat.CHANNEL


@router.get("", response_model=list[project_sessions.ProjectChatSessionSummary])
def list_sessions(session: Db) -> list[project_sessions.ProjectChatSessionSummary]:
    """История Библиотеки не пересекается с проектными поисками."""
    return project_sessions.list_session_summaries(session, None, CHANNEL)


@router.post("", response_model=project_sessions.ProjectChatSessionDetail)
def create_session(session: Db) -> project_sessions.ProjectChatSessionDetail:
    """Новая сессия использует общий пресет модели поиска."""
    chat = project_sessions.create_session(session, None, CHANNEL)
    return project_sessions.session_detail(session, chat, CHANNEL)


@router.get("/{session_id}", response_model=project_sessions.ProjectChatSessionDetail)
def get_session(session_id: UUID, session: Db) -> project_sessions.ProjectChatSessionDetail:
    """Прочитать переписку Библиотеки."""
    return project_sessions.get_session_detail(session, None, session_id, CHANNEL)


@router.put("/{session_id}/draft", response_model=project_sessions.ProjectChatSessionDetail)
def save_draft(session_id: UUID, command: project_sessions.ProjectChatDraftWrite,
               session: Db) -> project_sessions.ProjectChatSessionDetail:
    """Сохранить черновик библиотечного поиска."""
    project_sessions.save_draft(session, None, session_id, command.text, CHANNEL)
    return project_sessions.get_session_detail(session, None, session_id, CHANNEL)


@router.get("/{session_id}/context", response_model=project_sessions.ProjectChatContextPreviewRead)
def context(session_id: UUID, session: Db) -> project_sessions.ProjectChatContextPreviewRead:
    """У библиотечного поиска нет проектных чипов контекста."""
    return source_search_chat.context_preview(session, None, session_id)


@router.put("/{session_id}/context", response_model=project_sessions.ProjectChatSessionDetail)
def update_context(session_id: UUID, command: project_sessions.ProjectChatContextWrite,
                   session: Db) -> project_sessions.ProjectChatSessionDetail:
    """Сохранить общие настройки поиска без области проекта."""
    project_sessions.update_context(session, None, session_id, command, CHANNEL)
    return project_sessions.get_session_detail(session, None, session_id, CHANNEL)


@router.put("/{session_id}/settings", response_model=project_sessions.ProjectChatSessionDetail)
def update_settings(session_id: UUID, command: project_sessions.ProjectChatSettingsWrite,
                    session: Db) -> project_sessions.ProjectChatSessionDetail:
    """Выбрать модель библиотечного чата."""
    project_sessions.update_settings(session, None, session_id, command, CHANNEL)
    return project_sessions.get_session_detail(session, None, session_id, CHANNEL)


@router.post("/{session_id}/messages", response_model=chat_common.ChatMessageRead)
async def send_message(session_id: UUID, command: project_sessions.ProjectChatMessageWrite,
                       session: Db, gateway: Gateway) -> chat_common.ChatMessageRead:
    """Выполнить ход без SSE."""
    message = await source_search_chat.send_message(session, gateway, None, session_id,
                                                    command.text)
    return chat_common.message_read(message)


@router.post("/{session_id}/messages/stream")
def stream_message(session_id: UUID, command: project_sessions.ProjectChatMessageWrite,
                   session: Db) -> StreamingResponse:
    """Поток этапов общего конвейера SearXNG."""
    project_sessions.require_session(session, None, session_id, CHANNEL)
    return StreamingResponse(
        source_search_chat.stream_turn(None, session_id, command.text),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
