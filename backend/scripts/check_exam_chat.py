"""Сквозная серверная проверка первой итерации экзаменационного чата."""

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ai import gateway as gateway_module  # noqa: E402
from app.ai.credentials import encrypt_secret  # noqa: E402
from app.ai.gateway import ModelGateway  # noqa: E402
from app.ai.provider import (  # noqa: E402
    FakeTransport,
    ProviderCompletion,
    ProviderStreamEvent,
    ProviderUsage,
)
from app.bindings.search import (  # noqa: E402
    create_fragment_search,
    reindex_material,
)
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.exam import attempts as attempt_service  # noqa: E402
from app.exam import chat as chat_service  # noqa: E402
from app.exam import router as chat_router  # noqa: E402
from app.exam.schemas import (  # noqa: E402
    ChatAnswerWrite,
    ChatMessageWrite,
    ChatModelOverrideWrite,
    ChatSettingsWrite,
    SelfAssessmentWrite,
    ToolRunCreateWrite,
)
from app.models import (  # noqa: E402
    AiModelCatalogEntry,
    AiProviderConnection,
    AiSettings,
    AttemptOutcome,
    BlockClass,
    ExaminerPersona,
    ExaminerStrictness,
    ExamKind,
    GradeMethod,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialSourceKind,
    MaterialState,
    NodeType,
    PageQuality,
    ProgramNode,
    Project,
    ProjectMaterial,
    ProjectStatus,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    SourceRole,
    TemplateKey,
    WorkspaceVariant,
    utc_now,
)

MODEL_ID = "fake/exam-structured"
REFERENCE = (
    "Индекс ускоряет поиск строк в таблице, но занимает место и замедляет запись."
)


def _configure_ai(session: Session) -> None:
    now = utc_now()
    provider = AiProviderConnection(
        label="Fake provider",
        catalog_profile="openai_compatible",
        base_url="https://fake.test/v1",
        api_key_ciphertext=encrypt_secret("not-a-real-key"),
    )
    session.add(provider)
    session.flush()
    session.add_all(
        [
            AiSettings(
                id=1,
                external_models_enabled=True,
                confirm_input_tokens=100_000,
                usd_rub_rate=Decimal("90"),
                usd_rub_rate_date=now.date(),
                default_text_provider_id=provider.id,
                default_text_model_id=MODEL_ID,
            ),
            AiModelCatalogEntry(
                provider_id=provider.id,
                model_id=MODEL_ID,
                display_name="Fake exam structured",
                context_length=100_000,
                supported_parameters=["response_format"],
                input_modalities=["text"],
                output_modalities=["text"],
                prompt_price_usd=Decimal("0.000001"),
                completion_price_usd=Decimal("0.000002"),
                pricing_snapshot_at=now,
                catalog_snapshot_at=now,
                is_available=True,
            ),
        ]
    )
    session.commit()


def _seed_exam(session: Session) -> tuple[Project, ProgramNode]:
    project = Project(
        template_key=TemplateKey.EXAM,
        workspace_variant=WorkspaceVariant.EXAM,
        status=ProjectStatus.ACTIVE,
        name="Проверка экзаменационного чата",
    )
    session.add(project)
    session.flush()
    node = ProgramNode(
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.QUESTION,
        sort_order=0,
        title="Что даёт индекс базе данных?",
        is_in_current_program=True,
        is_archived=False,
    )
    session.add(node)
    session.flush()
    session.add(
        ReferenceAnswer(
            project_id=project.id,
            program_node_id=node.id,
            text=REFERENCE,
            origin_kind=ReferenceAnswerOrigin.MANUAL,
            match_method=ReferenceAnswerMatchMethod.MANUAL,
            is_confirmed=True,
            is_active=True,
            revision=1,
        )
    )
    session.commit()
    return project, node


def _seed_material(session: Session, project_id: UUID) -> None:
    material = Material(
        sha256="b" * 64,
        original_name="Конспект.txt",
        storage_path="text/check-exam-chat.txt",
        media_type="text/plain",
        source_kind=MaterialSourceKind.TEXT,
        size_bytes=64,
        page_count=1,
        status=MaterialState.READY,
        active_parse_revision=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(material)
    session.flush()
    session.add(
        ProjectMaterial(
            project_id=project_id,
            material_id=material.id,
            source_role=SourceRole.ADDITIONAL,
            priority=0,
            affects_program=False,
            purposes=["study_source"],
            created_at=utc_now(),
        )
    )
    page = MaterialPage(
        material_id=material.id,
        revision=1,
        page_number=1,
        width=595,
        height=842,
        text="Индекс — вспомогательная структура для быстрого поиска строк.",
        markdown="Индекс — вспомогательная структура для быстрого поиска строк.",
        quality=PageQuality.NATIVE,
        elements=[],
        diagnostics=[],
        created_at=utc_now(),
    )
    session.add(page)
    session.flush()
    block = MaterialBlock(
        material_id=material.id,
        revision=1,
        sort_order=0,
        title="Индексы",
        block_class=BlockClass.CONTENT,
        page_from=1,
        page_to=1,
    )
    session.add(block)
    session.flush()
    session.add(
        MaterialFragment(
            material_id=material.id,
            page_id=page.id,
            block_id=block.id,
            sort_order=0,
            text="Индекс — вспомогательная структура для быстрого поиска строк.",
            bbox=[0, 0, 1, 1],
            element_kind="paragraph",
            degraded_structure=False,
            quality=PageQuality.NATIVE,
        )
    )
    session.commit()
    reindex_material(session, material.id)
    session.commit()


def _judge_completion() -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(
            {
                "outcome": "partial",
                "credited": [
                    {"point": "Назначение индекса", "quote": "ускоряет выборку"}
                ],
                "missed": [{"point": "Цена индекса", "quote": ""}],
                "wrong": [],
                "summary": "Назначение названо, ограничения пропущены.",
            },
            ensure_ascii=False,
        ),
        actual_model_id=MODEL_ID,
        request_id="judge-1",
        usage=ProviderUsage(
            input_tokens=120,
            output_tokens=40,
            cost_usd=Decimal("0.01"),
        ),
    )


async def _run(engine: object, session: Session) -> None:
    _configure_ai(session)
    project, node = _seed_exam(session)
    chat = chat_service.create_session(session, project.id, node.id)
    fake = FakeTransport(
        streams=[
            [
                ProviderStreamEvent(delta="Индекс "),
                ProviderStreamEvent(
                    delta="ускоряет поиск.",
                    usage=ProviderUsage(input_tokens=8, output_tokens=4),
                    actual_model_id=MODEL_ID,
                    request_id="reply-1",
                ),
            ]
        ],
        completions=[_judge_completion()],
    )

    original_transport = gateway_module.production_transport
    original_session_local = chat_router.SessionLocal
    gateway_module.production_transport = lambda db, modality: fake
    chat_router.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        response = await chat_router.post_chat_message(
            project_id=project.id,
            session_id=chat.id,
            command=ChatMessageWrite(text="Объясни коротко"),
            session=session,
            gateway=ModelGateway(session, fake),
        )
        frames = "".join([chunk async for chunk in response.body_iterator])
        assert "event: started" in frames
        assert "event: delta" in frames
        assert "event: completed" in frames
        detail = chat_service.get_session_detail(session, project.id, chat.id)
        assert detail.messages[-1].text == "Индекс ускоряет поиск."
        assert detail.messages[-1].stream_state.value == "complete"
        session.commit()

        exact = await chat_router.post_chat_answer(
            project_id=project.id,
            session_id=chat.id,
            command=ChatAnswerWrite(text=REFERENCE),
            session=session,
            gateway=ModelGateway(session, fake),
        )
        assert exact.grade.method == GradeMethod.EXACT_MATCH.value
        assert exact.grade.outcome == AttemptOutcome.PASSED.value
        assert exact.grade.usage.actual_cost_usd == Decimal("0")
        session.commit()

        judged = await chat_router.post_chat_answer(
            project_id=project.id,
            session_id=chat.id,
            command=ChatAnswerWrite(text="Индекс ускоряет выборку."),
            session=session,
            gateway=ModelGateway(session, fake),
        )
        assert judged.grade.method == GradeMethod.AI_JUDGE.value
        assert judged.grade.outcome == AttemptOutcome.PARTIAL.value
        assert judged.grade.credited_points[0].quote_start == 7
        assert judged.grade.usage.actual_cost_usd == Decimal("0.01")
        assert fake.complete_calls == 1
        session.commit()

        cached = await chat_router.post_chat_answer(
            project_id=project.id,
            session_id=chat.id,
            command=ChatAnswerWrite(text="Индекс ускоряет выборку."),
            session=session,
            gateway=ModelGateway(session, fake),
        )
        assert cached.grade.method == GradeMethod.AI_JUDGE.value
        assert cached.grade.cached is True
        assert cached.grade.usage.actual_cost_usd == Decimal("0")
        assert fake.complete_calls == 1
        session.commit()

        assessed = chat_router.put_attempt_self_assessment(
            project.id,
            cached.attempt.id,
            SelfAssessmentWrite(outcome=AttemptOutcome.FAILED),
            session,
        )
        assert assessed.outcome == AttemptOutcome.PARTIAL.value
        assert assessed.self_assessment == AttemptOutcome.FAILED.value
        assert assessed.method == GradeMethod.AI_JUDGE.value
        session.commit()

        ai_settings = session.get(AiSettings, 1)
        assert ai_settings is not None
        ai_settings.external_models_enabled = False
        session.commit()
        offline = await chat_router.post_chat_answer(
            project_id=project.id,
            session_id=chat.id,
            command=ChatAnswerWrite(text="Индекс ускоряет поиск таблицы."),
            session=session,
            gateway=ModelGateway(session, fake),
        )
        assert offline.grade.method == GradeMethod.KEY_TERMS.value
        assert offline.grade.outcome in {
            AttemptOutcome.PARTIAL.value,
            AttemptOutcome.FAILED.value,
        }
        assert "внешние модели выключены" in offline.grade.summary
        assert fake.complete_calls == 1
        session.commit()

        history = chat_router.get_attempts(project.id, node.id, session)
        assert [item.ordinal for item in history] == [4, 3, 2, 1]
        assert history[0].method == GradeMethod.KEY_TERMS.value
        session.commit()
        cached_detail = chat_router.get_attempt_detail(
            project.id, cached.attempt.id, session
        )
        assert cached_detail.grade is not None
        assert cached_detail.grade.self_assessment == AttemptOutcome.FAILED.value
        session.commit()
        stored = attempt_service.list_attempts(session, project.id, node.id)
        assert len(stored) == 4
        session.commit()

        # Захватываем id заранее: rollback ниже истощает атрибуты загруженных
        # ORM-объектов, а повторное обращение к project.id/chat.id после отката
        # само по себе автоначинает транзакцию и ломает следующий `with session.begin()`.
        project_id, node_id, chat_id = project.id, node.id, chat.id

        # Настройки: частичный PATCH не сбрасывает неуказанные поля.
        chat_router.patch_chat_settings(
            project_id, chat_id,
            ChatSettingsWrite(strictness=ExaminerStrictness.STRICT), session,
        )
        session.commit()
        after_strictness = chat_router.patch_chat_settings(
            project_id, chat_id,
            ChatSettingsWrite(persona=ExaminerPersona.CALM_TEACHER), session,
        )
        assert after_strictness.persona == ExaminerPersona.CALM_TEACHER.value
        assert after_strictness.strictness == ExaminerStrictness.STRICT.value
        assert after_strictness.context_flags["profile"] is True
        session.commit()

        # study — зарегистрирован, но стабильно недоступен.
        try:
            chat_router.patch_chat_settings(
                project_id, chat_id, ChatSettingsWrite(mode="study"), session
            )
        except Exception as error:  # noqa: BLE001 — проверяем стабильный код домена
            assert getattr(error, "code", None) == "chat_mode_unavailable"
        else:
            raise AssertionError("study должен быть недоступен в первой итерации")
        session.commit()

        # Неизвестная модель отклоняется без сохранения.
        try:
            chat_router.patch_chat_settings(
                project_id, chat_id,
                ChatSettingsWrite(
                    model_override=ChatModelOverrideWrite(
                        provider_id="00000000-0000-0000-0000-000000000000",
                        model_id="ghost-model",
                    )
                ),
                session,
            )
        except Exception as error:  # noqa: BLE001
            assert getattr(error, "code", None) == "ai_model_not_in_catalog"
        else:
            raise AssertionError("неизвестная модель должна быть отклонена")
        session.commit()

        capabilities = chat_router.get_chat_capabilities(project_id, node_id, session)
        modes = {item.key: item.available for item in capabilities.modes}
        assert modes == {"exam": True, "study": False}
        tools = {item.key: item.available for item in capabilities.tools}
        assert tools["search_project_materials"] is True
        assert tools["search_external_sources"] is False
        session.commit()

        preview = chat_router.get_chat_context(project_id, chat_id, session)
        assert preview.fingerprint
        session.commit()

        # BM25 Tool: настоящий поиск через общий реестр, без обращения к модели.
        _seed_material(session, project_id)
        calls_before_tool = fake.complete_calls
        run = chat_router.post_tool_run(
            project_id, chat_id, "search_project_materials",
            ToolRunCreateWrite(input={"query": "индекс"}), session,
        )
        assert run.state == "succeeded"
        assert run.result is not None
        assert len(run.result["items"]) == 1
        assert fake.complete_calls == calls_before_tool
        session.commit()

        detail_with_tool = chat_service.get_session_detail(session, project_id, chat_id)
        tool_messages = [
            m for m in detail_with_tool.messages if m.payload_kind.value == "tool_result"
        ]
        assert len(tool_messages) == 1
        assert tool_messages[0].skill == "search_project_materials"
        session.commit()

        try:
            chat_router.post_tool_run(
                project_id, chat_id, "no_such_tool",
                ToolRunCreateWrite(input={"query": "индекс"}), session,
            )
        except Exception as error:  # noqa: BLE001
            assert getattr(error, "code", None) == "chat_tool_not_found"
        else:
            raise AssertionError("неизвестный Tool должен быть отклонён")
    finally:
        gateway_module.production_transport = original_transport
        chat_router.SessionLocal = original_session_local


def main() -> None:
    with TemporaryDirectory(prefix="tentex-exam-chat-") as temporary:
        settings.data_dir = Path(temporary)
        database_path = Path(temporary) / "check.sqlite"
        engine = create_engine(f"sqlite+pysqlite:///{database_path}")

        @event.listens_for(engine, "connect")
        def _foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                create_fragment_search(connection)
            with Session(engine, expire_on_commit=False) as session:
                asyncio.run(_run(engine, session))
                assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        finally:
            engine.dispose()
    print("check_exam_chat: OK")


if __name__ == "__main__":
    main()
