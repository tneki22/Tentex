from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderStreamEvent, ProviderUsage
from app.bindings import service as binding_service
from app.bindings.schemas import BindingCreateWrite
from app.exam import chat as chat_service
from app.exam import router as chat_router
from app.exam.context import build_context
from app.exam.prompts import PERSONA_PROMPTS, build_chat_reply_prompt
from app.exam.schemas import (
    ChatMessageWrite,
    ChatModelOverrideWrite,
    ChatSettingsWrite,
)
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    BindingMechanism,
    ChatMessageRole,
    ChatMode,
    ExaminerPersona,
    ExaminerStrictness,
    GoalPassport,
    utc_now,
)
from app.projects.errors import ProjectDomainError


def test_partial_patch_does_not_reset_other_settings(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Частичный PATCH")
    chat = chat_service.create_session(session, project.id, topic.id)

    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(strictness=ExaminerStrictness.STRICT)
    )
    updated = chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(persona=ExaminerPersona.CALM_TEACHER)
    )

    assert updated.persona == ExaminerPersona.CALM_TEACHER
    assert updated.strictness == ExaminerStrictness.STRICT  # не сброшено вторым PATCH
    assert updated.context_flags["profile"] is True  # флаги не тронуты вовсе


def test_context_flags_merge_partially(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Частичные флаги")
    chat = chat_service.create_session(session, project.id, topic.id)

    updated = chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(context_flags={"fragments": False})
    )

    assert updated.context_flags["fragments"] is False
    assert updated.context_flags["reference"] is True  # остальные ключи целы
    assert updated.context_flags["profile"] is True


def test_unknown_context_flag_rejected(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Неизвестный флаг")
    chat = chat_service.create_session(session, project.id, topic.id)

    with pytest.raises(ProjectDomainError) as excinfo:
        chat_service.update_settings(
            session, project.id, chat.id, ChatSettingsWrite(context_flags={"bogus": True})
        )
    assert excinfo.value.code == "chat_context_flag_unknown"


def test_new_session_defaults_to_exam_mode(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Режим по умолчанию")
    chat = chat_service.create_session(session, project.id, topic.id)
    assert chat.mode == ChatMode.EXAM


def test_study_mode_rejected_with_stable_reason(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Режим Разобраться")
    chat = chat_service.create_session(session, project.id, topic.id)

    with pytest.raises(ProjectDomainError) as excinfo:
        chat_service.update_settings(
            session, project.id, chat.id, ChatSettingsWrite(mode=ChatMode.STUDY)
        )
    assert excinfo.value.code == "chat_mode_unavailable"
    assert chat.mode == ChatMode.EXAM  # настройка не применилась


def test_unknown_model_override_rejected(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Неизвестная модель")
    chat = chat_service.create_session(session, project.id, topic.id)

    with pytest.raises(ProjectDomainError) as excinfo:
        chat_service.update_settings(
            session,
            project.id,
            chat.id,
            ChatSettingsWrite(
                model_override=ChatModelOverrideWrite(provider_id=uuid4(), model_id="ghost")
            ),
        )
    assert excinfo.value.code == "ai_model_not_in_catalog"


def test_model_without_structured_output_rejected(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Модель без structured output")
    chat = chat_service.create_session(session, project.id, topic.id)

    provider_id = uuid4()
    now = utc_now()
    session.add(
        AiProviderConnection(
            id=provider_id, label="Only streaming", catalog_profile="openai_compatible",
            base_url="https://example.test/v1",
        )
    )
    session.flush()
    session.add(
        AiModelCatalogEntry(
            provider_id=provider_id,
            model_id="stream-only",
            display_name="Stream only",
            supported_parameters=["temperature"],  # непустой список без response_format
            input_modalities=["text"],
            output_modalities=["text"],
            prompt_price_usd=Decimal("0.000001"),
            completion_price_usd=Decimal("0.000002"),
            pricing_snapshot_at=now,
            catalog_snapshot_at=now,
            is_manually_added=True,
            is_available=True,
        )
    )
    session.commit()

    with pytest.raises(ProjectDomainError) as excinfo:
        chat_service.update_settings(
            session,
            project.id,
            chat.id,
            ChatSettingsWrite(
                model_override=ChatModelOverrideWrite(
                    provider_id=provider_id, model_id="stream-only"
                )
            ),
        )
    assert excinfo.value.code == "ai_capability_unsupported"


def test_compatible_model_override_is_saved(session: Session, ai_config: str) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Совместимая модель")
    chat = chat_service.create_session(session, project.id, topic.id)
    provider = session.scalars(select(AiProviderConnection)).one()
    session.commit()  # закрыть автоначатую транзакцию чтения перед следующим with session.begin()

    updated = chat_service.update_settings(
        session,
        project.id,
        chat.id,
        ChatSettingsWrite(
            model_override=ChatModelOverrideWrite(provider_id=provider.id, model_id=ai_config)
        ),
    )
    assert updated.model_override == {"provider_id": str(provider.id), "model_id": ai_config}

    cleared = chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(model_override=None)
    )
    assert cleared.model_override is None


def test_profile_included_in_context_and_persona_changes_prompt_not_reference(
    session: Session,
) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Профиль в контексте")
    session.add(
        GoalPassport(
            project_id=project.id,
            subject="Теория вероятностей",
            instructor_requirements="Сначала определение, затем пример",
            updated_at=utc_now(),
        )
    )
    session.commit()
    chat = chat_service.create_session(session, project.id, topic.id)

    ctx = build_context(session, chat, for_judge=False)
    assert ctx.profile["subject"] == "Теория вероятностей"
    assert ctx.profile["instructor_requirements"] == "Сначала определение, затем пример"
    entries = {entry["kind"]: entry for entry in ctx.manifest}
    assert entries["profile"]["included"] is True

    calm = build_chat_reply_prompt(ExaminerPersona.CALM_TEACHER, ExaminerStrictness.NORMAL)
    strict = build_chat_reply_prompt(ExaminerPersona.STRICT_REVIEWER, ExaminerStrictness.NORMAL)
    assert PERSONA_PROMPTS[ExaminerPersona.CALM_TEACHER] in calm
    assert PERSONA_PROMPTS[ExaminerPersona.STRICT_REVIEWER] in strict
    assert calm != strict
    # Смена персоны не должна задевать эталон/данные — только слой tone.
    assert "Теория вероятностей" not in calm and "Теория вероятностей" not in strict


def test_context_flag_off_excludes_profile(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Профиль выключен")
    session.add(
        GoalPassport(project_id=project.id, subject="БД", updated_at=utc_now())
    )
    session.commit()
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(context_flags={"profile": False})
    )
    session.refresh(chat)

    ctx = build_context(session, chat, for_judge=False)
    assert ctx.profile == {}
    entries = {entry["kind"]: entry for entry in ctx.manifest}
    assert entries["profile"]["included"] is False
    assert entries["profile"]["reason"] == "excluded_by_user"


def test_judge_never_receives_chat_tail(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Судья без хвоста")
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.append_message(session, chat, role=ChatMessageRole.USER, text="привет")
    chat_service.append_message(session, chat, role=ChatMessageRole.EXAMINER, text="привет и тебе")

    ctx = build_context(session, chat, for_judge=True)
    assert ctx.tail == []
    entries = {entry["kind"]: entry for entry in ctx.manifest}
    assert entries["chat_tail"]["included"] is False


def test_preview_and_actual_request_share_fingerprint(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Fingerprint")
    chat = chat_service.create_session(session, project.id, topic.id)

    preview = chat_service.context_preview(session, project.id, chat.id)
    ctx = build_context(session, chat, for_judge=False)
    assert preview.fingerprint == ctx.fingerprint


def test_answers_file_binding_is_not_duplicated_in_chat_context(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Реляционная модель")
    material = make_material(session, "a9")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Реляционная модель хранит данные в таблицах."],
    )
    binding_service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(
            program_node_id=topic.id,
            fragment_ids=page.fragment_ids,
            mechanism=BindingMechanism.ANSWERS_FILE,
        ),
    )
    chat = chat_service.create_session(session, project.id, topic.id)

    context = build_context(session, chat, for_judge=False)

    assert context.fragments == []
    assert not any(item["kind"] == "fragment" for item in context.manifest)


@pytest.mark.asyncio
async def test_sse_completed_carries_final_message(
    session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Completed несёт сообщение")
    chat = chat_service.create_session(session, project.id, topic.id)

    fake = FakeTransport(
        streams=[
            [
                ProviderStreamEvent(delta="Гото"),
                ProviderStreamEvent(
                    delta="во",
                    usage=ProviderUsage(input_tokens=1, output_tokens=1),
                    actual_model_id=ai_config,
                    request_id="req-completed",
                ),
            ]
        ]
    )
    monkeypatch.setattr("app.ai.gateway.production_transport", lambda db, modality: fake)
    test_session_local = sessionmaker(bind=session.bind, expire_on_commit=False)
    monkeypatch.setattr(chat_router, "SessionLocal", test_session_local)

    response = await chat_router.post_chat_message(
        project_id=project.id,
        session_id=chat.id,
        command=ChatMessageWrite(text="Объясни ещё раз"),
        session=session,
        gateway=ModelGateway(session),
    )
    frames = [chunk async for chunk in response.body_iterator]
    completed_frame = next(frame for frame in frames if "event: completed" in frame)
    data_line = next(line for line in completed_frame.split("\n") if line.startswith("data: "))
    payload = json.loads(data_line[len("data: ") :])
    assert payload["message"]["text"] == "Готово"
    assert payload["message"]["stream_state"] == "complete"
    assert payload["message"]["id"] == payload["message_id"]
