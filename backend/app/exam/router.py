from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.schemas import AiMessage
from app.db import SessionLocal, get_session
from app.exam import chat as chat_service
from app.exam.context import ChatContext
from app.exam.prompts import CHAT_REPLY_SYSTEM_PROMPT
from app.exam.schemas import (
    ChatAnswerResult,
    ChatAnswerWrite,
    ChatContextRead,
    ChatDraftRead,
    ChatDraftWrite,
    ChatMessageRead,
    ChatMessageWrite,
    ChatSessionCreateWrite,
    ChatSessionDetail,
    ChatSessionSummary,
)
from app.models import ChatMessage, ChatMessageRole, ChatSession, ChatStreamState
from app.projects.errors import ProjectDomainError

SessionDependency = Annotated[Session, Depends(get_session)]
GatewayDependency = Annotated[ModelGateway, Depends(get_model_gateway)]
router = APIRouter(prefix="/api", tags=["exam-chat"])


@router.get("/projects/{project_id}/chat/sessions", response_model=list[ChatSessionSummary])
def list_chat_sessions(
    project_id: UUID, node_id: UUID, session: SessionDependency
) -> list[ChatSessionSummary]:
    return chat_service.list_session_summaries(session, project_id, node_id)


@router.post("/projects/{project_id}/chat/sessions", response_model=ChatSessionDetail)
def create_chat_session(
    project_id: UUID, command: ChatSessionCreateWrite, session: SessionDependency
) -> ChatSessionDetail:
    chat = chat_service.create_session(session, project_id, command.program_node_id)
    return chat_service.get_session_detail(session, project_id, chat.id)


@router.get(
    "/projects/{project_id}/chat/sessions/{session_id}", response_model=ChatSessionDetail
)
def get_chat_session(
    project_id: UUID, session_id: UUID, session: SessionDependency
) -> ChatSessionDetail:
    return chat_service.get_session_detail(session, project_id, session_id)


@router.put(
    "/projects/{project_id}/chat/sessions/{session_id}/draft", response_model=ChatDraftRead
)
def put_chat_draft(
    project_id: UUID, session_id: UUID, command: ChatDraftWrite, session: SessionDependency
) -> ChatDraftRead:
    chat = chat_service.save_draft(session, project_id, session_id, command.text)
    return ChatDraftRead(text=chat.draft_text, updated_at=chat.updated_at)


@router.get("/projects/{project_id}/chat/context", response_model=ChatContextRead)
def get_chat_context(
    project_id: UUID, node_id: UUID, session: SessionDependency
) -> ChatContextRead:
    return chat_service.context_preview(session, project_id, node_id)


def _history_messages(tail: list[ChatMessage]) -> list[AiMessage]:
    messages: list[AiMessage] = []
    for item in tail:
        if not item.text.strip():
            continue
        if item.role == ChatMessageRole.USER:
            messages.append(AiMessage(role="user", content=item.text))
        elif item.role == ChatMessageRole.EXAMINER:
            messages.append(AiMessage(role="assistant", content=item.text))
    return messages


def _reply_request(chat: ChatSession, ctx: ChatContext, user_text: str) -> AiTextRequest:
    grounding = [f"Вопрос: {ctx.node.title}"]
    if ctx.reference_text is not None:
        grounding.append(f"<reference_data>\n{ctx.reference_text}\n</reference_data>")
    for fragment in ctx.fragments:
        heading = f'material="{fragment.material_name}" page="{fragment.page_number}"'
        grounding.append(f"<fragment_data {heading}>\n{fragment.text}\n</fragment_data>")
    messages = [
        AiMessage(role="system", content=CHAT_REPLY_SYSTEM_PROMPT),
        AiMessage(role="user", content="\n\n".join(grounding)),
        *_history_messages(ctx.tail),
        AiMessage(role="user", content=user_text),
    ]
    return AiTextRequest(
        role="exam_chat_reply",
        messages=messages,
        project_id=chat.project_id,
        context_manifest=ctx.manifest,
        source_fingerprint={"chat_id": str(chat.id)},
    )


@router.post("/projects/{project_id}/chat/sessions/{session_id}/messages")
async def post_chat_message(
    project_id: UUID,
    session_id: UUID,
    command: ChatMessageWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> StreamingResponse:
    chat, ctx = chat_service.start_turn(session, project_id, session_id, command.text)
    request = _reply_request(chat, ctx, command.text)
    # Локальная проверка (роль/модель/ключ настроены) без сети — падает здесь
    # обычным ProjectDomainError, до того как клиент увидит поток.
    await gateway.preflight(request)
    return StreamingResponse(
        _events(project_id, session_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _events(project_id: UUID, chat_id: UUID, request: AiTextRequest) -> AsyncIterator[str]:
    # Зависимость get_session закрывается до отправки тела StreamingResponse
    # (FastAPI ≥ 0.106), поэтому поток открывает свою сессию — тот же случай,
    # что воркер разбора, а не обход правила из tentex-api.
    message_id = uuid4()
    with SessionLocal() as db:
        chunks: list[str] = []
        state = ChatStreamState.COMPLETE
        run_id: UUID | None = None
        try:
            async for event in ModelGateway(db).stream(request):
                if event.kind == "started":
                    run_id = event.run_id
                    yield _frame(
                        "started", {"message_id": str(message_id), "run_id": str(run_id)}
                    )
                elif event.kind == "delta":
                    chunks.append(event.delta)
                    yield _frame("delta", {"text": event.delta})
                elif event.kind == "completed":
                    usage = event.usage.model_dump(mode="json") if event.usage else {}
                    yield _frame(
                        "completed",
                        {"message_id": str(message_id), "usage": usage, "cached": False},
                    )
        except asyncio.CancelledError:
            state = ChatStreamState.STOPPED
            raise
        except ProjectDomainError as error:
            state = ChatStreamState.FAILED
            yield _frame("error", {"code": error.code, "detail": error.detail})
        finally:
            chat_service.finish_turn(
                db,
                project_id,
                chat_id,
                message_id=message_id,
                text="".join(chunks),
                stream_state=state,
                ai_run_id=run_id,
            )


@router.post(
    "/projects/{project_id}/chat/sessions/{session_id}/answer", response_model=ChatAnswerResult
)
def post_chat_answer(
    project_id: UUID,
    session_id: UUID,
    command: ChatAnswerWrite,
    session: SessionDependency,
) -> ChatAnswerResult:
    messages = chat_service.submit_answer_stub(session, project_id, session_id, command.text)
    return ChatAnswerResult(messages=[ChatMessageRead.model_validate(item) for item in messages])
