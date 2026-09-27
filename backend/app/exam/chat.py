from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.roles import validate_role_parameters
from app.ai.schemas import AiModelSelection
from app.ai.settings import seed_from_preset, validate_model_selection
from app.chat import common as chat_common
from app.db import project_write_transaction
from app.exam.context import (
    CONTEXT_FLAG_KEYS,
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
from app.projects.errors import ProjectDomainError, ProjectNotFoundError

# Требуются одновременно и streaming, и structured output: одна выбранная
# модель обслуживает и обычный ответ, и судью той же сессии (AI-CHATS.md §21.3).
REQUIRED_MODEL_CAPABILITIES = frozenset({"streaming", "structured_output"})
# Параметры чата проверяются по роли ответа: судья той же сессии работает на
# параметрах своей роли из Параметров, его снимок фиксирует только модель.
CHAT_PARAMETERS_ROLE = "exam_chat_reply"

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}
TITLE_MAX_LEN = 60


def _require_exam_project(session: Session, project_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.status != ProjectStatus.ACTIVE:
        raise ProjectNotFoundError()
    return project


def _require_chat_node(session: Session, project_id: UUID, node_id: UUID) -> ProgramNode:
    node = session.get(ProgramNode, node_id)
    if (
        node is None
        or node.project_id != project_id
        or node.is_archived
        or node.node_type not in STUDY_NODE_TYPES
    ):
        raise ProjectDomainError("Вопрос не найден", status=404, code="chat_node_not_found")
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


def list_sessions(session: Session, project_id: UUID, node_id: UUID | None) -> list[ChatSession]:
    _require_exam_project(session, project_id)
    if node_id is not None:
        _require_chat_node(session, project_id, node_id)
    return list(
        session.scalars(
            select(ChatSession)
            .where(
                ChatSession.project_id == project_id,
                ChatSession.program_node_id == node_id,
                # Чаты построения программы и поиска в интернете тоже живут без
                # темы, но это другие режимы со своими списками — в ленту чата
                # проекта они не попадают.
                ChatSession.mode.in_((ChatMode.EXAM, ChatMode.STUDY)),
            )
            .order_by(ChatSession.updated_at.desc())
        )
    )


def list_session_summaries(
    session: Session, project_id: UUID, node_id: UUID | None
) -> list[ChatSessionSummary]:
    chats = list_sessions(session, project_id, node_id)
    if not chats:
        return []
    counts = chat_common.message_counts(session, [chat.id for chat in chats])
    return [_summary(chat, counts.get(chat.id, 0)) for chat in chats]


def create_session(session: Session, project_id: UUID, node_id: UUID | None) -> ChatSession:
    with project_write_transaction(session, project_id):
        project = _require_exam_project(session, project_id)
        node = _require_chat_node(session, project_id, node_id) if node_id else None
        if node is None and project.template_key != "free":
            raise ProjectDomainError(
                "Чат без темы доступен только в свободном проекте",
                status=422,
                code="chat_node_required",
            )
        existing = session.scalar(
            select(func.count(ChatSession.id)).where(
                ChatSession.project_id == project_id, ChatSession.program_node_id == node_id
            )
        )
        ordinal = existing + 1
        base_title = _title(node) if node else "Свободное изучение"
        title = base_title if ordinal == 1 else f"{base_title} · {ordinal}"
        selection, parameters = seed_from_preset(
            session, role=CHAT_PARAMETERS_ROLE, required=REQUIRED_MODEL_CAPABILITIES
        )
        chat = ChatSession(
            project_id=project_id,
            program_node_id=node_id,
            section_scope_node_id=section_scope(session, node) if node else None,
            title=title,
            persona=ExaminerPersona.NEUTRAL_EXAMINER,
            strictness=ExaminerStrictness.NORMAL,
            mode=(
                ChatMode.EXAM
                if project.workspace_variant == WorkspaceVariant.EXAM
                else ChatMode.STUDY
            ),
            model_override=selection,
            model_parameters=parameters,
            draft_text="",
        )
        session.add(chat)
        session.flush()
        session.refresh(chat)
    return chat


def _message_read(message: ChatMessage) -> ChatMessageRead:
    return chat_common.message_read(message)


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
        select(ChatMessage).where(ChatMessage.session_id == chat.id).order_by(ChatMessage.sequence)
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
        model_parameters=chat.model_parameters or {},
        context_flags=chat.context_flags,
        draft_text=chat.draft_text,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[_message_read(message) for message in messages],
    )


def save_draft(session: Session, project_id: UUID, chat_id: UUID, text: str) -> ChatSession:
    # Открытие чата отправляет только что загруженный черновик обратно. Тот же
    # текст не пишем: любая запись сбрасывает кэш страниц у всех соединений API,
    # а новый updated_at поднимал бы сессию в списке без действий пользователя.
    _require_exam_project(session, project_id)
    current = _require_session(session, project_id, chat_id)
    if current.draft_text == text:
        return current
    with project_write_transaction(session, project_id):
        _require_exam_project(session, project_id)
        chat = _require_session(session, project_id, chat_id)
        return chat_common.save_draft_text(session, chat, text)


def update_settings(
    session: Session, project_id: UUID, chat_id: UUID, command: ChatSettingsWrite
) -> ChatSession:
    """Частичный PATCH: поле трогается, только если явно прислано (`model_fields_set`)."""
    fields = command.model_fields_set
    with project_write_transaction(session, project_id):
        _require_exam_project(session, project_id)
        chat = _require_session(session, project_id, chat_id)
        if "mode" in fields and command.mode is not None:
            chat.mode = command.mode
        if "persona" in fields and command.persona is not None:
            chat.persona = command.persona
        if "strictness" in fields and command.strictness is not None:
            chat.strictness = command.strictness
        if "model_override" in fields:
            snapshot = None
            parameters = None
            if command.model_override is not None:
                selection = AiModelSelection(
                    provider_id=command.model_override.provider_id,
                    model_id=command.model_override.model_id,
                )
                validate_model_selection(session, selection, required=REQUIRED_MODEL_CAPABILITIES)
                snapshot = {
                    "provider_id": str(selection.provider_id),
                    "model_id": selection.model_id,
                }
                parameters = validate_role_parameters(
                    CHAT_PARAMETERS_ROLE, command.model_parameters or {}
                )
            chat_common.apply_model_choice(
                session, chat, selection=snapshot, parameters=parameters
            )
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


def context_preview(session: Session, project_id: UUID, chat_id: UUID) -> ChatContextPreviewRead:
    _require_exam_project(session, project_id)
    chat = _require_session(session, project_id, chat_id)
    ctx = build_context(session, chat, for_judge=False)
    manifest = [ManifestEntryRead.model_validate(entry) for entry in ctx.manifest]
    override = _model_override_read(chat)
    return ChatContextPreviewRead(
        session_id=chat.id,
        node_id=chat.program_node_id,
        question=ctx.question,
        persona=chat.persona,
        strictness=chat.strictness,
        model_source="override" if override else "auto",
        model_id=override.model_id if override else None,
        manifest=manifest,
        fingerprint=ctx.fingerprint,
        total_bytes=sum(entry.bytes for entry in manifest),
    )


def _append_message_row(session: Session, chat: ChatSession, **fields: Any) -> ChatMessage:
    """Raw insert, no transaction of its own — caller must already be inside one.

    Delegates to `app.chat.common` (вынесено оттуда — логика domain-agnostic,
    её же использует `app.projects.program_chat`). Тонкая обёртка остаётся
    здесь ради существующих вызывающих (`exam/attempts.py`, `chat_tools/executor.py`
    зовут `chat_service._append_message_row` по имени).
    """
    return chat_common.append_message_row(session, chat, **fields)


def append_message(session: Session, chat: ChatSession, **fields: Any) -> ChatMessage:
    with session.begin():
        return _append_message_row(session, chat, **fields)


def require_turn_session(session: Session, project_id: UUID, chat_id: UUID) -> ChatSession:
    """Чат для нового хода: проект экзаменационный или свободный, сессия его."""
    _require_exam_project(session, project_id)
    return _require_session(session, project_id, chat_id)


def find_turn(
    session: Session, chat_id: UUID, client_turn_id: str
) -> tuple[ChatMessage, ChatMessage | None] | None:
    """Прежний ход с этим ID: реплика пользователя и завершённый ответ на неё, если есть."""
    user = session.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == chat_id,
            ChatMessage.client_turn_id == client_turn_id,
        )
    )
    if user is None:
        return None
    # Ответ хода — завершённый ответ до следующего вопроса: после упавшей
    # попытки повтор дописывает новый ответ ниже неудачного.
    for message in session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == chat_id, ChatMessage.sequence > user.sequence)
        .order_by(ChatMessage.sequence)
    ):
        if message.role == ChatMessageRole.USER:
            break
        if (
            message.role == ChatMessageRole.EXAMINER
            and message.stream_state == ChatStreamState.COMPLETE
        ):
            return user, message
    return user, None


def record_turn(
    session: Session,
    project_id: UUID,
    chat_id: UUID,
    text: str,
    *,
    skill: str | None,
    client_turn_id: str | None,
    snapshot: dict[str, Any],
    remember_budget: int | None = None,
) -> UUID:
    """Записать реплику пользователя — только после подготовки и подтверждения хода."""
    with project_write_transaction(session, project_id):
        chat = require_turn_session(session, project_id, chat_id)
        if remember_budget is not None:
            chat.context_budget_tokens = remember_budget
        user_message = _append_message_row(
            session,
            chat,
            role=ChatMessageRole.USER,
            text=text,
            skill=skill,
            client_turn_id=client_turn_id,
            context_snapshot=snapshot,
        )
    return user_message.id


def finish_turn(
    session: Session,
    project_id: UUID,
    chat_id: UUID,
    *,
    message_id: UUID,
    text: str,
    stream_state: ChatStreamState,
    ai_run_id: UUID | None,
    skill: str | None = None,
    context_snapshot: dict[str, Any] | None = None,
) -> ChatMessage:
    with project_write_transaction(session, project_id):
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
            skill=skill,
            context_snapshot=context_snapshot or {},
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


def get_capabilities(
    session: Session, project_id: UUID, node_id: UUID | None
) -> ChatCapabilitiesRead:
    from app.chat_tools.registry import list_tool_specs

    project = _require_exam_project(session, project_id)
    if node_id is not None:
        _require_chat_node(session, project_id, node_id)
    modes = [
        CapabilityRead(
            key="exam",
            title="Экзамен",
            available=project.workspace_variant == WorkspaceVariant.EXAM,
            unavailable_reason=(
                None
                if project.workspace_variant == WorkspaceVariant.EXAM
                else "exam_mode_not_applicable"
            ),
        ),
        CapabilityRead(
            key="study",
            title="Разобраться",
            available=True,
        ),
    ]
    skills = [
        CapabilityRead(
            key=key,
            title=title,
            available=(
                key in _AVAILABLE_SKILLS and project.workspace_variant == WorkspaceVariant.EXAM
            ),
            unavailable_reason=(
                None
                if key in _AVAILABLE_SKILLS and project.workspace_variant == WorkspaceVariant.EXAM
                else "skill_not_implemented"
            ),
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
