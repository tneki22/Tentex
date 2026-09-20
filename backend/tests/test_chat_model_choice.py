"""Выбор модели в композере чата: пресет, отметка в ленте, уровень рассуждения."""

from __future__ import annotations

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy.orm import Session

from app.ai.provider import OpenAITransport
from app.ai.roles import validate_role_parameters
from app.ai.schemas import AiChatPreset
from app.ai.settings import read_chat_preset, seed_from_preset, store_chat_preset
from app.exam import chat as chat_service
from app.exam.schemas import ChatModelOverrideWrite, ChatSettingsWrite
from app.models import AiModelCatalogEntry, ChatMessageRole
from app.projects.errors import ProjectDomainError


def _provider_id(session: Session) -> str:
    row = session.query(AiModelCatalogEntry).one()
    return str(row.provider_id)


def _override(session: Session, model_id: str) -> ChatModelOverrideWrite:
    return ChatModelOverrideWrite(provider_id=_provider_id(session), model_id=model_id)


# ---------------------------------------------------------------------------
# Уровень рассуждения
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("effort", ["off", "low", "medium", "high"])
def test_reasoning_effort_passes_role_validation(effort: str) -> None:
    parameters = validate_role_parameters("exam_chat_reply", {"reasoning_effort": effort})
    assert parameters["reasoning_effort"] == effort


def test_unknown_reasoning_effort_is_rejected() -> None:
    with pytest.raises(ProjectDomainError) as caught:
        validate_role_parameters("exam_chat_reply", {"reasoning_effort": "максимальный"})
    assert caught.value.code == "ai_role_parameters_invalid"


def test_openrouter_gets_reasoning_object_and_openai_gets_flat_field() -> None:
    """Один параметр — два разных поля запроса, каждое по своему профилю."""
    openrouter = OpenAITransport("https://example.test/v1", "key", "openrouter")
    kwargs: dict = {}
    openrouter._apply_parameters(kwargs, {"reasoning_effort": "high", "temperature": 0.4})
    assert kwargs["extra_body"]["reasoning"] == {"effort": "high"}
    assert kwargs["temperature"] == 0.4
    assert "reasoning_effort" not in kwargs

    flat = OpenAITransport("https://example.test/v1", "key", "openai_compatible")
    kwargs = {}
    flat._apply_parameters(kwargs, {"reasoning_effort": "low"})
    assert kwargs["reasoning_effort"] == "low"
    assert "extra_body" not in kwargs


def test_off_disables_reasoning_on_openrouter_and_sends_nothing_elsewhere() -> None:
    """Выключить рассуждение умеет только OpenRouter — у плоского поля такого значения нет."""
    openrouter = OpenAITransport("https://example.test/v1", "key", "openrouter")
    kwargs: dict = {}
    openrouter._apply_parameters(kwargs, {"reasoning_effort": "off"})
    assert kwargs["extra_body"]["reasoning"] == {"enabled": False}

    flat = OpenAITransport("https://example.test/v1", "key", "openai_compatible")
    kwargs = {}
    flat._apply_parameters(kwargs, {"reasoning_effort": "off"})
    assert kwargs == {}


# ---------------------------------------------------------------------------
# Липкий пресет
# ---------------------------------------------------------------------------


def test_chosen_model_is_reused_by_the_next_chat(session: Session, ai_config: str) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Первый вопрос")
    chat = chat_service.create_session(session, project.id, topic.id)

    chat_service.update_settings(
        session,
        project.id,
        chat.id,
        ChatSettingsWrite(
            model_override=_override(session, ai_config),
            model_parameters={"reasoning_effort": "high"},
        ),
    )

    preset = read_chat_preset(session)
    assert preset is not None
    assert preset.model_id == ai_config
    assert preset.parameters["reasoning_effort"] == "high"

    fresh = chat_service.create_session(session, project.id, topic.id)
    assert fresh.model_override == {"provider_id": _provider_id(session), "model_id": ai_config}
    assert fresh.model_parameters["reasoning_effort"] == "high"


def test_preset_needing_an_unsupported_capability_falls_back_to_auto(
    session: Session, ai_config: str
) -> None:
    """Непригодный пресет молча даёт «Auto»: новый чат не место для ошибки."""
    store_chat_preset(
        session,
        AiChatPreset(provider_id=_provider_id(session), model_id=ai_config, parameters={}),
    )
    model = session.query(AiModelCatalogEntry).one()
    model.supported_parameters = ["temperature"]  # response_format пропал из каталога
    session.commit()

    selection, parameters = seed_from_preset(
        session, role="exam_chat_reply", required=frozenset({"structured_output"})
    )
    assert (selection, parameters) == (None, None)


# ---------------------------------------------------------------------------
# Отметка в ленте
# ---------------------------------------------------------------------------


def test_switch_in_a_started_chat_is_noted_in_the_timeline(
    session: Session, ai_config: str
) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос со сменой модели")
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.append_message(session, chat, role=ChatMessageRole.USER, text="привет")

    chat_service.update_settings(
        session,
        project.id,
        chat.id,
        ChatSettingsWrite(model_override=_override(session, ai_config)),
    )

    detail = chat_service.get_session_detail(session, project.id, chat.id)
    note = detail.messages[-1]
    assert note.role == ChatMessageRole.SYSTEM
    assert note.text == "Модель: по умолчанию → Test structured model"


def test_empty_chat_switches_without_a_note(session: Session, ai_config: str) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Пустой чат")
    chat = chat_service.create_session(session, project.id, topic.id)

    chat_service.update_settings(
        session,
        project.id,
        chat.id,
        ChatSettingsWrite(model_override=_override(session, ai_config)),
    )

    detail = chat_service.get_session_detail(session, project.id, chat.id)
    assert detail.messages == []


def test_repeated_save_of_the_same_model_adds_nothing(session: Session, ai_config: str) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Тот же выбор дважды")
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.append_message(session, chat, role=ChatMessageRole.USER, text="привет")
    command = ChatSettingsWrite(model_override=_override(session, ai_config))

    chat_service.update_settings(session, project.id, chat.id, command)
    chat_service.update_settings(session, project.id, chat.id, command)

    detail = chat_service.get_session_detail(session, project.id, chat.id)
    notes = [item for item in detail.messages if item.role == ChatMessageRole.SYSTEM]
    assert len(notes) == 1


def test_system_note_stays_out_of_the_program_chat_prompt(session: Session) -> None:
    """Отметка — часть ленты, но не часть разговора с моделью."""
    from app.projects.program_chat import ProgramChatContext, _reply_messages

    ctx = ProgramChatContext(
        profile={}, sources=[], tree_text="", manifest=[], snapshot={}, fingerprint="f"
    )

    class Row:
        def __init__(self, role: ChatMessageRole, text: str) -> None:
            self.role = role
            self.text = text
            self.payload: dict = {}

    tail = [
        Row(ChatMessageRole.USER, "составь программу"),
        Row(ChatMessageRole.SYSTEM, "Модель: A → B"),
        Row(ChatMessageRole.ASSISTANT, "готово"),
    ]
    messages = _reply_messages(ctx, tail, None)
    assert all("Модель: A → B" not in str(item.content) for item in messages)
