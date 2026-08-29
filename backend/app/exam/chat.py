from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.schemas import AiModelSelection
from app.ai.settings import validate_model_selection
from app.exam.context import (
    CONTEXT_FLAG_KEYS,
    ChatContext,
    build_context,
    section_scope,
)
from app.exam.schemas import (
    CapabilityRead,
    ChatCapabilitiesRead,
    ChatContextPreviewRead,
    ChatMessageRead,
    ChatModelOverrideRead,
    ChatSessionDetail,
    ChatSessionSummary,
    ChatSettingsWrite,
    ManifestEntryRead,
)
from app.models import (
    ChatMessage,
    ChatMessageRole,
    ChatMode,
    ChatPayloadKind,
    ChatSession,
    ChatStreamState,
    ExaminerPersona,
    ExaminerStrictness,
    NodeType,
    ProgramNode,
    Project,
    ProjectStatus,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError

# Требуются одновременно и streaming, и structured output: одна выбранная
# модель обслуживает и обычный ответ, и судью той же сессии (AI-CHATS.md §21.3).
REQUIRED_MODEL_CAPABILITIES = frozenset({"streaming", "structured_output"})

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}
TITLE_MAX_LEN = 60


def _require_exam_project(session: Session, project_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.status != ProjectStatus.ACTIVE:
        raise ProjectNotFoundError()
    if project.workspace_variant != WorkspaceVariant.EXAM:
        raise ProjectConflictError(
            "Чат доступен только экзаменационным проектам",
            code="chat_exam_only",
        )
    return project


def _require_chat_node(session: Session, project_id: UUID, node_id: UUID) -> ProgramNode:
    node = session.get(ProgramNode, node_id)
    if (
        node is None
        or node.project_id != project_id
        or node.is_archived
        or node.node_type not in STUDY_NODE_TYPES
    ):
        raise ProjectDomainError(
            "Вопрос не найден", status=404, code="chat_node_not_found"
        )
    return node


def _require_session(session: Session, project_id: UUID, chat_id: UUID) -> ChatSession:
    chat = session.get(ChatSession, chat_id)
    if chat is None or chat.project_id != project_id:
        raise ProjectDomainError("Чат не найден", status=404, code="chat_session_not_found")
    return chat


def _title(node: ProgramNode) -> str:
    title = node.title.strip()
    return title if len(title) <= TITLE_MAX_LEN else f"{title[: TITLE_MAX_LEN - 1]}…"


def _summary(chat: ChatSession, message_count: int) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=chat.id,
        project_id=chat.project_id,
        program_node_id=chat.program_node_id,
        title=chat.title,
        updated_at=chat.updated_at,
        message_count=message_count,
    )


def list_sessions(session: Session, project_id: UUID, node_id: UUID) -> list[ChatSession]:
    _require_exam_project(session, project_id)
    _require_chat_node(session, project_id, node_id)
    return list(
        session.scalars(
            select(ChatSession)
            .where(ChatSession.project_id == project_id, ChatSession.program_node_id == node_id)
            .order_by(ChatSession.updated_at.desc())
        )
    )


def list_session_summaries(
    session: Session, project_id: UUID, node_id: UUID
) -> list[ChatSessionSummary]:
    chats = list_sessions(session, project_id, node_id)
    if not chats:
        return []
    counts = dict(
        session.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_([chat.id for chat in chats]))
            .group_by(ChatMessage.session_id)
        ).all()
    )
    return [_summary(chat, counts.get(chat.id, 0)) for chat in chats]


def create_session(session: Session, project_id: UUID, node_id: UUID) -> ChatSession:
    with session.begin():
        _require_exam_project(session, project_id)
        node = _require_chat_node(session, project_id, node_id)
        existing = session.scalar(
            select(func.count(ChatSession.id)).where(
                ChatSession.project_id == project_id, ChatSession.program_node_id == node_id
            )
        )
        ordinal = existing + 1
        base_title = _title(node)
        title = base_title if ordinal == 1 else f"{base_title} · {ordinal}"
        chat = ChatSession(
            project_id=project_id,
            program_node_id=node_id,
            section_scope_node_id=section_scope(session, node),
            title=title,
            persona=ExaminerPersona.NEUTRAL_EXAMINER,
            strictness=ExaminerStrictness.NORMAL,
            draft_text="",
        )
        session.add(chat)
        session.flush()
        session.refresh(chat)
    return chat


def _message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead.model_validate(message)


def get_session(session: Session, project_id: UUID, chat_id: UUID) -> ChatSession:
    _require_exam_project(session, project_id)
    return _require_session(session, project_id, chat_id)


def get_node(session: Session, project_id: UUID, node_id: UUID) -> ProgramNode:
    return _require_chat_node(session, project_id, node_id)


def _model_override_read(chat: ChatSession) -> ChatModelOverrideRead | None:
    if not chat.model_override:
        return None
    return ChatModelOverrideRead.model_validate(chat.model_override)


def get_session_detail(session: Session, project_id: UUID, chat_id: UUID) -> ChatSessionDetail:
    _require_exam_project(session, project_id)
    chat = _require_session(session, project_id, chat_id)
    messages = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == chat.id)
        .order_by(ChatMessage.sequence)
    )
    return ChatSessionDetail(
        id=chat.id,
        project_id=chat.project_id,
        program_node_id=chat.program_node_id,
        section_scope_node_id=chat.section_scope_node_id,
        title=chat.title,
        mode=chat.mode,
        persona=chat.persona,
        strictness=chat.strictness,
        model_override=_model_override_read(chat),
        context_flags=chat.context_flags,
        draft_text=chat.draft_text,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[_message_read(message) for message in messages],
    )


def save_draft(session: Session, project_id: UUID, chat_id: UUID, text: str) -> ChatSession:
    with session.begin():
        _require_exam_project(session, project_id)
        chat = _require_session(session, project_id, chat_id)
        chat.draft_text = text
        chat.updated_at = utc_now()
        session.flush()
        session.refresh(chat)
    return chat


def update_settings(
    session: Session, project_id: UUID, chat_id: UUID, command: ChatSettingsWrite
) -> ChatSession:
    """Частичный PATCH: поле трогается, только если явно прислано (`model_fields_set`)."""
    fields = command.model_fields_set
    with session.begin():
        _require_exam_project(session, project_id)
        chat = _require_session(session, project_id, chat_id)
        if "mode" in fields and command.mode is not None:
            if command.mode is ChatMode.STUDY:
                raise ProjectDomainError(
                    "Режим «Разобраться» пока недоступен",
                    status=422,
                    code="chat_mode_unavailable",
                )
            chat.mode = command.mode
        if "persona" in fields and command.persona is not None:
            chat.persona = command.persona
        if "strictness" in fields and command.strictness is not None:
            chat.strictness = command.strictness
        if "model_override" in fields:
            if command.model_override is None:
                chat.model_override = None
            else:
                selection = AiModelSelection(
                    provider_id=command.model_override.provider_id,
                    model_id=command.model_override.model_id,
                )
                validate_model_selection(session, selection, required=REQUIRED_MODEL_CAPABILITIES)
                chat.model_override = {
                    "provider_id": str(selection.provider_id),
                    "model_id": selection.model_id,
                }
        if "context_flags" in fields and command.context_flags is not None:
            unknown = set(command.context_flags) - CONTEXT_FLAG_KEYS
            if unknown:
                raise ProjectDomainError(
                    "Неизвестная часть контекста",
                    status=422,
                    code="chat_context_flag_unknown",
                    context={"keys": sorted(unknown)},
                )
            chat.context_flags = {**chat.context_flags, **command.context_flags}
        chat.updated_at = utc_now()
        session.flush()
        session.refresh(chat)
    return chat


def context_preview(
    session: Session, project_id: UUID, chat_id: UUID
) -> ChatContextPreviewRead:
    _require_exam_project(session, project_id)
    chat = _require_session(session, project_id, chat_id)
    ctx = build_context(session, chat, for_judge=False)
    manifest = [ManifestEntryRead.model_validate(entry) for entry in ctx.manifest]
    override = _model_override_read(chat)
    return ChatContextPreviewRead(
        session_id=chat.id,
        node_id=chat.program_node_id,
        question=ctx.node.title,
        persona=chat.persona,
        strictness=chat.strictness,
        model_source="override" if override else "auto",
        model_id=override.model_id if override else None,
        manifest=manifest,
        fingerprint=ctx.fingerprint,
        total_bytes=sum(entry.bytes for entry in manifest),
    )


def _append_message_row(
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
    second `with session.begin():` inside the same request raises
    "A transaction is already begun". Compound flows (build context, then
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
        return _append_message_row(session, chat, **fields)


def start_turn(
    session: Session, project_id: UUID, chat_id: UUID, text: str
) -> tuple[ChatSession, ChatContext]:
    """Validate, build the reply context and record the user's turn — one transaction."""
    with session.begin():
        _require_exam_project(session, project_id)
        chat = _require_session(session, project_id, chat_id)
        ctx = build_context(session, chat, for_judge=False)
        _append_message_row(
            session, chat, role=ChatMessageRole.USER, text=text, context_snapshot=ctx.snapshot
        )
    return chat, ctx


def finish_turn(
    session: Session,
    project_id: UUID,
    chat_id: UUID,
    *,
    message_id: UUID,
    text: str,
    stream_state: ChatStreamState,
    ai_run_id: UUID | None,
) -> ChatMessage:
    with session.begin():
        _require_exam_project(session, project_id)
        chat = _require_session(session, project_id, chat_id)
        return _append_message_row(
            session,
            chat,
            message_id=message_id,
            role=ChatMessageRole.EXAMINER,
            text=text,
            stream_state=stream_state,
            ai_run_id=ai_run_id,
        )


# Шесть экзаменационных навыков из AI-CHATS.md §8/§21.2. Только «Сдать ответ»
# реально работает в первой итерации: он открывает локальную форму и вообще
# не требует модели. Остальные честно помечены — команда объясняет причину,
# не вызывает API и не создаёт сообщение.
_SKILL_TITLES: dict[str, str] = {
    "answer": "Сдать ответ",
    "ask_question": "Попросить вопрос",
    "hint": "Получить подсказку",
    "task": "Получить задание",
    "accuracy": "Проверить точность",
    "ticket": "Вытянуть билет",
}
_AVAILABLE_SKILLS = frozenset({"answer"})


def get_capabilities(session: Session, project_id: UUID, node_id: UUID) -> ChatCapabilitiesRead:
    from app.chat_tools.registry import list_tool_specs

    _require_exam_project(session, project_id)
    _require_chat_node(session, project_id, node_id)
    modes = [
        CapabilityRead(key="exam", title="Экзамен", available=True),
        CapabilityRead(
            key="study",
            title="Разобраться",
            available=False,
            unavailable_reason="chat_mode_unavailable",
        ),
    ]
    skills = [
        CapabilityRead(
            key=key,
            title=title,
            available=key in _AVAILABLE_SKILLS,
            unavailable_reason=None if key in _AVAILABLE_SKILLS else "skill_not_implemented",
        )
        for key, title in _SKILL_TITLES.items()
    ]
    tools = [
        CapabilityRead(
            key=spec.key,
            title=spec.title,
            available=spec.available,
            unavailable_reason=spec.unavailable_reason,
        )
        for spec in list_tool_specs()
    ]
    return ChatCapabilitiesRead(modes=modes, skills=skills, tools=tools)
