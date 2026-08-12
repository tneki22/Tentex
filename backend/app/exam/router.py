from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.schemas import AiMessage
from app.db import SessionLocal, get_session
from app.exam import attempts as attempt_service
from app.exam import chat as chat_service
from app.exam.context import ChatContext
from app.exam.prompts import CHAT_REPLY_SYSTEM_PROMPT
from app.exam.schemas import (
    AttemptDetailRead,
    AttemptRead,
    AttemptSummaryRead,
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
    GradeRead,
    GradeUsageRead,
    SelfAssessmentWrite,
)
from app.models import AiRun, ChatMessage, ChatMessageRole, ChatSession, ChatStreamState, Grade
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
async def post_chat_answer(
    project_id: UUID,
    session_id: UUID,
    command: ChatAnswerWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> ChatAnswerResult:
    result = await attempt_service.submit_answer(
        session, gateway, project_id, session_id, command.text
    )
    return ChatAnswerResult(
        messages=[ChatMessageRead.model_validate(item) for item in result.messages],
        attempt=AttemptRead.model_validate(result.attempt),
        grade=_grade_read(session, result.grade),
    )


def _grade_read(session: Session, grade: Grade) -> GradeRead:
    run = session.get(AiRun, grade.ai_run_id) if grade.ai_run_id is not None else None
    usage = GradeUsageRead(
        input_tokens=run.input_tokens or 0 if run is not None else 0,
        output_tokens=run.output_tokens or 0 if run is not None else 0,
        reasoning_tokens=run.reasoning_tokens or 0 if run is not None else 0,
        provider_cached_tokens=run.provider_cached_tokens or 0 if run is not None else 0,
        actual_cost_usd=(
            run.actual_cost_usd if run is not None else Decimal("0")
        ),
        actual_cost_rub=(
            run.actual_cost_rub if run is not None else Decimal("0")
        ),
    )
    return GradeRead(
        attempt_id=grade.attempt_id,
        outcome=grade.outcome,
        method=grade.method,
        credited_points=grade.credited_points,
        missed_points=grade.missed_points,
        wrong_points=grade.wrong_points,
        summary=grade.summary,
        self_assessment=grade.self_assessment,
        ai_run_id=grade.ai_run_id,
        actual_model_id=run.actual_model_id if run is not None else None,
        usage=usage,
        cached=run.status == "cached" if run is not None else False,
        created_at=grade.created_at,
        updated_at=grade.updated_at,
    )


def _attempt_detail(session: Session, item: attempt_service.AttemptWithGrade) -> AttemptDetailRead:
    return AttemptDetailRead(
        attempt=AttemptRead.model_validate(item.attempt),
        grade=_grade_read(session, item.grade) if item.grade is not None else None,
    )


@router.post(
    "/projects/{project_id}/attempts/{attempt_id}/check", response_model=GradeRead
)
async def post_attempt_check(
    project_id: UUID,
    attempt_id: UUID,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> GradeRead:
    grade = await attempt_service.check_attempt(session, gateway, project_id, attempt_id)
    return _grade_read(session, grade)


@router.put(
    "/projects/{project_id}/attempts/{attempt_id}/self-assessment",
    response_model=GradeRead,
)
def put_attempt_self_assessment(
    project_id: UUID,
    attempt_id: UUID,
    command: SelfAssessmentWrite,
    session: SessionDependency,
) -> GradeRead:
    grade = attempt_service.set_self_assessment(
        session, project_id, attempt_id, command.outcome
    )
    return _grade_read(session, grade)


@router.get("/projects/{project_id}/attempts", response_model=list[AttemptSummaryRead])
def get_attempts(
    project_id: UUID, node_id: UUID, session: SessionDependency
) -> list[AttemptSummaryRead]:
    return [
        AttemptSummaryRead(
            id=item.attempt.id,
            ordinal=item.attempt.ordinal,
            created_at=item.attempt.created_at,
            outcome=item.grade.outcome if item.grade is not None else None,
            method=item.grade.method if item.grade is not None else None,
            self_assessment=(
                item.grade.self_assessment if item.grade is not None else None
            ),
            text_preview=item.attempt.text[:180],
        )
        for item in attempt_service.list_attempts(session, project_id, node_id)
    ]


@router.get(
    "/projects/{project_id}/attempts/{attempt_id}", response_model=AttemptDetailRead
)
def get_attempt_detail(
    project_id: UUID, attempt_id: UUID, session: SessionDependency
) -> AttemptDetailRead:
    return _attempt_detail(
        session, attempt_service.get_attempt(session, project_id, attempt_id)
    )
