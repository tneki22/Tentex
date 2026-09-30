from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.dictation import _audio_format
from app.ai.gateway import MAX_AUDIO_BYTES, AiTextRequest, ModelGateway
from app.ai.schemas import AiMessage
from app.chat_tools.executor import run_tool
from app.db import SessionLocal, get_session
from app.exam import attempts as attempt_service
from app.exam import chat as chat_service
from app.exam import oral as oral_service
from app.exam.reply import ChatConfirmationRequired, TurnOptions, prepare_reply
from app.exam.schemas import (
    AttemptDetailRead,
    AttemptRead,
    AttemptSummaryRead,
    ChatAnswerResult,
    ChatAnswerWrite,
    ChatCapabilitiesRead,
    ChatContextPreviewRead,
    ChatDraftRead,
    ChatDraftWrite,
    ChatMessageRead,
    ChatMessageWrite,
    ChatSessionCreateWrite,
    ChatSessionDetail,
    ChatSessionSummary,
    ChatSettingsWrite,
    ChatToolRunRead,
    GradeRead,
    GradeUsageRead,
    OralRecordingRead,
    OralSubmitWrite,
    SelfAssessmentWrite,
    ToolRunCreateWrite,
)
from app.exam.sources import STABLE_IDS, ensure_scope_has_places
from app.models import (
    AiRun,
    ChatMessage,
    ChatMode,
    ChatStreamState,
    Grade,
    OralRecording,
    utc_now,
)
from app.projects.errors import ProjectDomainError
from app.retrieval.citations import citation_error

SessionDependency = Annotated[Session, Depends(get_session)]
GatewayDependency = Annotated[ModelGateway, Depends(get_model_gateway)]
router = APIRouter(prefix="/api", tags=["exam-chat"])


@router.get("/projects/{project_id}/chat/sessions", response_model=list[ChatSessionSummary])
def list_chat_sessions(
    project_id: UUID, session: SessionDependency, node_id: UUID | None = None
) -> list[ChatSessionSummary]:
    return chat_service.list_session_summaries(session, project_id, node_id)


@router.post("/projects/{project_id}/chat/sessions", response_model=ChatSessionDetail)
def create_chat_session(
    project_id: UUID, command: ChatSessionCreateWrite, session: SessionDependency
) -> ChatSessionDetail:
    chat = chat_service.create_session(session, project_id, command.program_node_id)
    return chat_service.get_session_detail(session, project_id, chat.id)


@router.get("/projects/{project_id}/chat/sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session(
    project_id: UUID, session_id: UUID, session: SessionDependency
) -> ChatSessionDetail:
    return chat_service.get_session_detail(session, project_id, session_id)


@router.put("/projects/{project_id}/chat/sessions/{session_id}/draft", response_model=ChatDraftRead)
def put_chat_draft(
    project_id: UUID, session_id: UUID, command: ChatDraftWrite, session: SessionDependency
) -> ChatDraftRead:
    chat = chat_service.save_draft(session, project_id, session_id, command.text)
    return ChatDraftRead(text=chat.draft_text, updated_at=chat.updated_at)


@router.put(
    "/projects/{project_id}/chat/sessions/{session_id}/settings",
    response_model=ChatSessionDetail,
)
def patch_chat_settings(
    project_id: UUID,
    session_id: UUID,
    command: ChatSettingsWrite,
    session: SessionDependency,
) -> ChatSessionDetail:
    chat_service.update_settings(session, project_id, session_id, command)
    return chat_service.get_session_detail(session, project_id, session_id)


@router.get(
    "/projects/{project_id}/chat/sessions/{session_id}/context",
    response_model=ChatContextPreviewRead,
)
def get_chat_context(
    project_id: UUID, session_id: UUID, session: SessionDependency
) -> ChatContextPreviewRead:
    return chat_service.context_preview(session, project_id, session_id)


@router.get("/projects/{project_id}/chat/capabilities", response_model=ChatCapabilitiesRead)
def get_chat_capabilities(
    project_id: UUID, session: SessionDependency, node_id: UUID | None = None
) -> ChatCapabilitiesRead:
    return chat_service.get_capabilities(session, project_id, node_id)


@router.post(
    "/projects/{project_id}/chat/sessions/{session_id}/tools/{tool_key}/runs",
    response_model=ChatToolRunRead,
)
def post_tool_run(
    project_id: UUID,
    session_id: UUID,
    tool_key: str,
    command: ToolRunCreateWrite,
    session: SessionDependency,
) -> ChatToolRunRead:
    run = run_tool(session, project_id, session_id, tool_key, command.input)
    return ChatToolRunRead.model_validate(run)


@router.post("/projects/{project_id}/chat/sessions/{session_id}/messages")
async def post_chat_message(
    project_id: UUID,
    session_id: UUID,
    command: ChatMessageWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> StreamingResponse:
    """Ход чата: подготовка → при нужде подтверждение → запись реплики → поток.

    Реплика пользователя пишется только после подготовки и подтверждения:
    отказ или отмена не оставляют в ленте вопроса без ответа. Тот же
    `client_turn_id` повторяет ход, не создавая вторую реплику.
    """
    chat = chat_service.require_turn_session(session, project_id, session_id)
    options = TurnOptions(
        text=command.text,
        operation=command.operation,
        scope=command.retrieval_scope,
        material_ids=command.retrieval_material_ids,
        knowledge_policy=command.knowledge_policy,
    )
    previous = (
        chat_service.find_turn(session, chat.id, command.client_turn_id)
        if command.client_turn_id
        else None
    )
    if previous is not None:
        user, answer = previous
        if answer is not None:
            return _stream(_replay(user, answer))
        options = TurnOptions.from_message(user, options)
    if chat.mode == ChatMode.STUDY:
        ensure_scope_has_places(session, project_id, chat.program_node_id, options.scope)

    before = previous[0].sequence if previous is not None else None
    prepared = await prepare_reply(
        session, gateway, chat, options,
        budget_tokens=command.context_budget_tokens, before_sequence=before,
    )
    budget = prepared.budget
    if command.context_budget_tokens and budget.maximum and budget.limit > budget.maximum:
        raise ProjectDomainError(
            "Такой объём не помещается в окно выбранной модели",
            status=422,
            code="chat_context_budget_too_large",
            context={"maximum": budget.maximum},
        )
    if prepared.reasons and command.confirmed_request_hash != prepared.preflight.request_hash:
        expanded = None
        if budget.over and (budget.maximum is None or budget.needed <= budget.maximum):
            expanded = await prepare_reply(
                session, gateway, chat, options,
                budget_tokens=budget.needed, before_sequence=before,
            )
        raise ChatConfirmationRequired(prepared, expanded)

    if previous is not None:
        user_message_id = previous[0].id
    else:
        user_message_id = chat_service.record_turn(
            session,
            project_id,
            chat.id,
            options.text,
            skill=options.operation,
            client_turn_id=command.client_turn_id,
            snapshot=prepared.user_snapshot,
            remember_budget=command.context_budget_tokens if command.remember_budget else None,
        )
    request = replace(prepared.request, confirmed=True)
    return _stream(
        _events(project_id, session_id, request, user_message_id, prepared.sources, options)
    )


def _stream(frames: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _replay(user: ChatMessage, answer: ChatMessage) -> AsyncIterator[str]:
    """Ход уже отвечен — повтор отдаёт сохранённый ответ, не вызывая модель."""
    sources = (answer.context_snapshot or {}).get("retrieval_sources", [])
    yield _frame(
        "started",
        {
            "message_id": str(answer.id),
            "user_message_id": str(user.id),
            "run_id": str(answer.ai_run_id) if answer.ai_run_id else None,
            "sources": sources,
        },
    )
    yield _frame(
        "completed",
        {
            "message_id": str(answer.id),
            "message": ChatMessageRead.model_validate(answer).model_dump(mode="json"),
            "usage": {},
            "cached": True,
        },
    )


def _frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _events(
    project_id: UUID,
    chat_id: UUID,
    request: AiTextRequest,
    user_message_id: UUID,
    sources: list[dict[str, Any]],
    options: TurnOptions,
) -> AsyncIterator[str]:
    # Зависимость get_session закрывается до отправки тела StreamingResponse
    # (FastAPI ≥ 0.106), поэтому поток открывает свою сессию — тот же случай,
    # что воркер разбора, а не обход правила из tentex-api.
    message_id = uuid4()
    allowed = {str(source["id"]) for source in sources}
    with SessionLocal() as db:
        chunks: list[str] = []
        run_id: UUID | None = None
        saved = False

        def _save(stream_state: ChatStreamState) -> ChatMessage:
            nonlocal saved
            message = chat_service.finish_turn(
                db,
                project_id,
                chat_id,
                message_id=message_id,
                text="".join(chunks),
                stream_state=stream_state,
                ai_run_id=run_id,
                skill=options.operation,
                context_snapshot={
                    "retrieval_sources": sources,
                    "source_ids": STABLE_IDS,
                    "turn": options.snapshot(),
                },
            )
            saved = True
            return message

        try:
            current_request = request
            for citation_attempt in range(2):
                completed_usage: dict[str, object] = {}
                async for event in ModelGateway(db).stream(current_request):
                    if event.kind == "started":
                        run_id = event.run_id
                        # Источники едут в первом кадре: ссылки [S3] работают уже
                        # во время потока, а не только после `completed`.
                        yield _frame(
                            "started",
                            {
                                "message_id": str(message_id),
                                "user_message_id": str(user_message_id),
                                "run_id": str(run_id),
                                "sources": sources,
                            },
                        )
                    elif event.kind == "delta":
                        chunks.append(event.delta)
                        yield _frame("delta", {"text": event.delta})
                    elif event.kind == "completed":
                        completed_usage = event.usage.model_dump(mode="json") if event.usage else {}
                problem = citation_error("".join(chunks), allowed)
                if problem and citation_attempt == 0:
                    chunks.clear()
                    yield _frame("reset", {"reason": problem})
                    current_request = replace(
                        request,
                        messages=[
                            *request.messages,
                            AiMessage(
                                role="user",
                                content=(
                                    "Исправь ответ: используй только разрешённые ID "
                                    "источников"
                                    + (" и хотя бы одну цитату" if allowed else "")
                                    + ". Не комментируй исправление."
                                ),
                            ),
                        ],
                    )
                    continue
                if problem:
                    yield _frame(
                        "error",
                        {"code": "chat_invalid_citations", "detail": problem, "context": {}},
                    )
                    _save(ChatStreamState.FAILED)
                    break
                # Сообщение сохраняется до кадра completed, чтобы фронтенд мог
                # заменить оптимистичную запись готовым ChatMessageRead без
                # повторного чтения всей сессии (AI-CHATS.md §21.4).
                message = _save(ChatStreamState.COMPLETE)
                yield _frame(
                    "completed",
                    {
                        "message_id": str(message_id),
                        "message": ChatMessageRead.model_validate(message).model_dump(mode="json"),
                        "usage": completed_usage,
                        "cached": False,
                    },
                )
                break
        except asyncio.CancelledError:
            if not saved:
                _save(ChatStreamState.STOPPED)
            raise
        except ProjectDomainError as error:
            yield _frame(
                "error", {"code": error.code, "detail": error.detail, "context": error.context}
            )
            if not saved:
                _save(ChatStreamState.FAILED)
        finally:
            if not saved:
                _save(ChatStreamState.FAILED)


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
        session,
        gateway,
        project_id,
        session_id,
        command.text,
        answer_mode=command.answer_mode,
        active_seconds=command.active_seconds,
    )
    return ChatAnswerResult(
        messages=[ChatMessageRead.model_validate(item) for item in result.messages],
        attempt=AttemptRead.model_validate(result.attempt),
        grade=_grade_read(session, result.grade) if result.grade is not None else None,
    )


def _grade_read(session: Session, grade: Grade) -> GradeRead:
    run = session.get(AiRun, grade.ai_run_id) if grade.ai_run_id is not None else None
    usage = GradeUsageRead(
        input_tokens=run.input_tokens or 0 if run is not None else 0,
        output_tokens=run.output_tokens or 0 if run is not None else 0,
        reasoning_tokens=run.reasoning_tokens or 0 if run is not None else 0,
        provider_cached_tokens=run.provider_cached_tokens or 0 if run is not None else 0,
        actual_cost_usd=(run.actual_cost_usd if run is not None else Decimal("0")),
        actual_cost_rub=(run.actual_cost_rub if run is not None else Decimal("0")),
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


def _oral_read(row: OralRecording) -> OralRecordingRead:
    return OralRecordingRead(
        id=row.id,
        transcript=row.transcript,
        metrics=row.metrics,
        audio_available=bool(row.audio_path and row.audio_expires_at > utc_now()),
        audio_expires_at=row.audio_expires_at,
    )


@router.post(
    "/projects/{project_id}/chat/sessions/{session_id}/oral-drafts",
    response_model=OralRecordingRead,
)
async def post_oral_draft(
    project_id: UUID,
    session_id: UUID,
    file: UploadFile,
    duration_ms: Annotated[int, Form(ge=1, le=300_000)],
    session: SessionDependency,
    gateway: GatewayDependency,
) -> OralRecordingRead:
    """Сохранить запись и вернуть транскрипт на исправление перед оценкой."""
    oral_service.cleanup_expired(session)
    audio_format = _audio_format(file.content_type)
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    row = await oral_service.create_draft(
        session, gateway, project_id, session_id, audio, audio_format, duration_ms,
    )
    return _oral_read(row)


@router.get(
    "/projects/{project_id}/chat/sessions/{session_id}/oral-drafts/{recording_id}",
    response_model=OralRecordingRead,
)
def get_oral_draft(
    project_id: UUID, session_id: UUID, recording_id: UUID, session: SessionDependency,
) -> OralRecordingRead:
    """Восстановить несданный или сданный черновик."""
    with session.begin():
        row = oral_service._recording(session, project_id, session_id, recording_id)
        return _oral_read(row)


@router.post(
    "/projects/{project_id}/chat/sessions/{session_id}/oral-drafts/{recording_id}/submit",
    response_model=ChatAnswerResult,
)
async def post_oral_answer(
    project_id: UUID, session_id: UUID, recording_id: UUID,
    command: OralSubmitWrite, session: SessionDependency, gateway: GatewayDependency,
) -> ChatAnswerResult:
    """Сдать исправленный транскрипт и проверить его ИИ-судьёй."""
    result = await oral_service.submit_draft(
        session, gateway, project_id, session_id, recording_id,
        command.text, command.answer_mode,
    )
    return ChatAnswerResult(
        messages=[ChatMessageRead.model_validate(item) for item in result.messages],
        attempt=AttemptRead.model_validate(result.attempt),
        grade=_grade_read(session, result.grade) if result.grade is not None else None,
    )


@router.get("/projects/{project_id}/oral-recordings/{recording_id}/audio")
def get_oral_audio(
    project_id: UUID, recording_id: UUID, session: SessionDependency,
) -> FileResponse:
    """Выдать ещё доступную локальную запись только своему проекту."""
    path = oral_service.audio_path(session, project_id, recording_id)
    return FileResponse(path)


def _attempt_detail(session: Session, item: attempt_service.AttemptWithGrade) -> AttemptDetailRead:
    oral = session.scalar(select(OralRecording).where(
        OralRecording.attempt_id == item.attempt.id
    ))
    return AttemptDetailRead(
        attempt=AttemptRead.model_validate(item.attempt),
        grade=_grade_read(session, item.grade) if item.grade is not None else None,
        oral=_oral_read(oral) if oral is not None else None,
    )


@router.post("/projects/{project_id}/attempts/{attempt_id}/check", response_model=GradeRead)
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
    grade = attempt_service.set_self_assessment(session, project_id, attempt_id, command.outcome)
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
            self_assessment=(item.grade.self_assessment if item.grade is not None else None),
            text_preview=item.attempt.text[:180],
        )
        for item in attempt_service.list_attempts(session, project_id, node_id)
    ]


@router.get("/projects/{project_id}/attempts/{attempt_id}", response_model=AttemptDetailRead)
def get_attempt_detail(
    project_id: UUID, attempt_id: UUID, session: SessionDependency
) -> AttemptDetailRead:
    return _attempt_detail(session, attempt_service.get_attempt(session, project_id, attempt_id))
