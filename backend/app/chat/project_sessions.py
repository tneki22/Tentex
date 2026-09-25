"""Сессии проектных чатов без привязки к теме — построения программы и поиска в интернете.

Оба чата живут в `ChatSession` и различаются режимом. История, черновик, выбор
модели, флаги контекста и область («вся программа / раздел / тема») у них устроены
одинаково, поэтому описаны здесь один раз и параметризованы каналом
`ProjectChatChannel`. Предметное — контекст, промпты, ответ модели — остаётся в
модуле каждого чата (`app.projects.program_chat`, `app.projects.source_search_chat`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.roles import validate_role_parameters
from app.ai.schemas import AiModelSelection
from app.ai.settings import seed_from_preset, validate_model_selection
from app.chat import common as chat_common
from app.chat.common import ChatMessageRead, ManifestEntryRead
from app.db import chat_write_transaction
from app.models import (
    ChatMessage,
    ChatMode,
    ChatSession,
    ProgramNode,
    Project,
    ProjectStatus,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError


@dataclass(frozen=True)
class ProjectChatChannel:
    mode: ChatMode
    role: str
    required_capabilities: frozenset[str]
    # «Программа», «Поиск»: вторая сессия получает «Поиск · 2».
    title: str
    # Для текста отказа: «Чат построения программы доступен только …».
    feature: str
    default_flags: Mapping[str, bool]
    # Префикс машинных кодов ошибок — контракт с фронтендом, у программы исторический.
    code_prefix: str

    def fresh_flags(self) -> dict[str, bool]:
        return dict(self.default_flags)

    def flags(self, chat: ChatSession) -> dict[str, bool]:
        """Флаги сессии поверх умолчаний: новый флаг канала включается и у старых сессий."""
        return {**self.default_flags, **(chat.context_flags or {})}


class ChatApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProjectChatSessionSummary(ChatApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    project_id: UUID | None
    title: str
    updated_at: Any
    message_count: int


class ProjectChatModelOverrideRead(ChatApiModel):
    provider_id: UUID
    model_id: str


class ProjectChatSettingsWrite(ChatApiModel):
    """Смена модели чата: выбор и его параметры приходят одним запросом."""

    model_override: ProjectChatModelOverrideRead | None = None
    model_parameters: dict[str, object] | None = None


class ProjectChatSessionDetail(ChatApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    project_id: UUID | None
    section_scope_node_id: UUID | None
    title: str
    model_override: ProjectChatModelOverrideRead | None
    model_parameters: dict[str, object]
    context_flags: dict[str, bool]
    draft_text: str
    created_at: Any
    updated_at: Any
    messages: list[ChatMessageRead]


class ProjectChatDraftWrite(ChatApiModel):
    text: str = Field(max_length=200_000)


class ProjectChatContextWrite(ChatApiModel):
    section_scope_node_id: UUID | None = None
    context_flags: dict[str, bool] | None = None


class ProjectChatContextPreviewRead(ChatApiModel):
    session_id: UUID
    manifest: list[ManifestEntryRead]
    fingerprint: str
    total_bytes: int


class ProjectChatMessageWrite(ChatApiModel):
    text: NonBlank = Field(max_length=20_000)


def require_project(
    session: Session, project_id: UUID | None, channel: ProjectChatChannel
) -> Project | None:
    if project_id is None and channel.mode == ChatMode.SOURCE_SEARCH:
        return None
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError()
    if (channel.mode != ChatMode.SOURCE_SEARCH
            and project.workspace_variant != WorkspaceVariant.TEXTBOOK):
        raise ProjectConflictError(
            f"{channel.feature} доступен только учебниковому проекту",
            code=f"{channel.code_prefix}_textbook_only",
        )
    if project.status not in {ProjectStatus.DRAFT, ProjectStatus.ACTIVE}:
        raise ProjectConflictError(
            "Архивный или завершённый проект нельзя изменять",
            code="project_read_only",
            context={"current_status": project.status.value},
        )
    return project


def require_session(
    session: Session, project_id: UUID | None, session_id: UUID, channel: ProjectChatChannel
) -> ChatSession:
    chat = session.get(ChatSession, session_id)
    if chat is None or chat.project_id != project_id or chat.mode != channel.mode:
        raise ProjectDomainError(
            "Чат не найден", status=404, code=f"{channel.code_prefix}_session_not_found"
        )
    return chat


def list_session_summaries(
    session: Session, project_id: UUID | None, channel: ProjectChatChannel
) -> list[ProjectChatSessionSummary]:
    require_project(session, project_id, channel)
    chats = list(
        session.scalars(
            select(ChatSession)
            .where(ChatSession.project_id == project_id, ChatSession.mode == channel.mode)
            .order_by(ChatSession.updated_at.desc())
        )
    )
    counts = chat_common.message_counts(session, [chat.id for chat in chats])
    return [
        ProjectChatSessionSummary(
            id=chat.id,
            project_id=chat.project_id,
            title=chat.title,
            updated_at=chat.updated_at,
            message_count=counts.get(chat.id, 0),
        )
        for chat in chats
    ]


def create_session(
    session: Session, project_id: UUID | None, channel: ProjectChatChannel
) -> ChatSession:
    with chat_write_transaction(session, project_id):
        require_project(session, project_id, channel)
        existing = session.scalar(
            select(func.count(ChatSession.id)).where(
                ChatSession.project_id == project_id, ChatSession.mode == channel.mode
            )
        )
        ordinal = existing + 1
        selection, parameters = seed_from_preset(
            session, role=channel.role, required=channel.required_capabilities
        )
        chat = ChatSession(
            project_id=project_id,
            program_node_id=None,
            section_scope_node_id=None,
            title=channel.title if ordinal == 1 else f"{channel.title} · {ordinal}",
            mode=channel.mode,
            model_override=selection,
            model_parameters=parameters,
            context_flags=channel.fresh_flags(),
            draft_text="",
        )
        session.add(chat)
        session.flush()
        session.refresh(chat)
    return chat


def _model_override_read(chat: ChatSession) -> ProjectChatModelOverrideRead | None:
    if not chat.model_override:
        return None
    return ProjectChatModelOverrideRead.model_validate(chat.model_override)


def request_model_override(chat: ChatSession | None) -> AiModelSelection | None:
    if chat is None or not chat.model_override:
        return None
    return AiModelSelection(
        provider_id=chat.model_override["provider_id"],
        model_id=chat.model_override["model_id"],
    )


def session_detail(
    session: Session, chat: ChatSession, channel: ProjectChatChannel
) -> ProjectChatSessionDetail:
    messages = session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == chat.id).order_by(ChatMessage.sequence)
    )
    return ProjectChatSessionDetail(
        id=chat.id,
        project_id=chat.project_id,
        section_scope_node_id=chat.section_scope_node_id,
        title=chat.title,
        model_override=_model_override_read(chat),
        model_parameters=chat.model_parameters or {},
        context_flags=channel.flags(chat),
        draft_text=chat.draft_text,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[chat_common.message_read(message) for message in messages],
    )


def get_session_detail(
    session: Session, project_id: UUID | None, session_id: UUID, channel: ProjectChatChannel
) -> ProjectChatSessionDetail:
    require_project(session, project_id, channel)
    chat = require_session(session, project_id, session_id, channel)
    return session_detail(session, chat, channel)


def save_draft(
    session: Session, project_id: UUID | None, session_id: UUID,
    text: str, channel: ProjectChatChannel,
) -> ChatSession:
    with chat_write_transaction(session, project_id):
        require_project(session, project_id, channel)
        chat = require_session(session, project_id, session_id, channel)
        return chat_common.save_draft_text(session, chat, text)


def update_settings(
    session: Session,
    project_id: UUID | None,
    session_id: UUID,
    command: ProjectChatSettingsWrite,
    channel: ProjectChatChannel,
) -> ChatSession:
    with chat_write_transaction(session, project_id):
        require_project(session, project_id, channel)
        chat = require_session(session, project_id, session_id, channel)
        snapshot = None
        parameters = None
        if command.model_override is not None:
            selection = AiModelSelection(
                provider_id=command.model_override.provider_id,
                model_id=command.model_override.model_id,
            )
            validate_model_selection(session, selection, required=channel.required_capabilities)
            snapshot = {
                "provider_id": str(selection.provider_id),
                "model_id": selection.model_id,
            }
            parameters = validate_role_parameters(channel.role, command.model_parameters or {})
        chat_common.apply_model_choice(session, chat, selection=snapshot, parameters=parameters)
        session.flush()
        session.refresh(chat)
    return chat


def update_context(
    session: Session,
    project_id: UUID | None,
    session_id: UUID,
    command: ProjectChatContextWrite,
    channel: ProjectChatChannel,
) -> ChatSession:
    fields = command.model_fields_set
    with chat_write_transaction(session, project_id):
        require_project(session, project_id, channel)
        chat = require_session(session, project_id, session_id, channel)
        if "section_scope_node_id" in fields:
            if command.section_scope_node_id is not None:
                node = session.get(ProgramNode, command.section_scope_node_id)
                if project_id is None or node is None or node.project_id != project_id:
                    raise ProjectDomainError(
                        "Узел области контекста не найден",
                        status=404,
                        code=f"{channel.code_prefix}_scope_node_not_found",
                    )
            chat.section_scope_node_id = command.section_scope_node_id
        if "context_flags" in fields and command.context_flags is not None:
            unknown = set(command.context_flags) - set(channel.default_flags)
            if unknown:
                raise ProjectDomainError(
                    "Неизвестная часть контекста",
                    status=422,
                    code=f"{channel.code_prefix}_context_flag_unknown",
                    context={"keys": sorted(unknown)},
                )
            chat.context_flags = {**channel.flags(chat), **command.context_flags}
        chat.updated_at = utc_now()
        session.flush()
        session.refresh(chat)
    return chat
