"""Сквозная серверная проверка первой итерации экзаменационного чата."""

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

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
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.exam import attempts as attempt_service  # noqa: E402
from app.exam import chat as chat_service  # noqa: E402
from app.exam import router as chat_router  # noqa: E402
from app.exam.schemas import (  # noqa: E402
    ChatAnswerWrite,
    ChatMessageWrite,
    SelfAssessmentWrite,
)
from app.models import (  # noqa: E402
    AiConnection,
    AiModelCatalogEntry,
    AiSettings,
    AttemptOutcome,
    ExamKind,
    GradeMethod,
    NodeType,
    ProgramNode,
    Project,
    ProjectStatus,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
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
    session.add_all(
        [
            AiSettings(
                id=1,
                external_models_enabled=True,
                confirm_input_tokens=100_000,
                usd_rub_rate=Decimal("90"),
                usd_rub_rate_date=now.date(),
            ),
            AiConnection(
                modality="text",
                label="Текстовые модели",
                base_url="https://fake.test/v1",
                api_key_ciphertext=encrypt_secret("not-a-real-key"),
                default_model_id=MODEL_ID,
            ),
            AiConnection(
                modality="speech",
                label="Распознавание речи",
                base_url="",
                api_key_ciphertext=None,
            ),
            AiModelCatalogEntry(
                modality="text",
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
                connection.exec_driver_sql(
                    "CREATE VIRTUAL TABLE fragment_search USING fts5("
                    "text, lemmas, fragment_id UNINDEXED, material_id UNINDEXED, "
                    "tokenize = 'unicode61 remove_diacritics 2')"
                )
                connection.exec_driver_sql(
                    "CREATE TABLE fragment_search_map ("
                    "fragment_id TEXT PRIMARY KEY, material_id TEXT NOT NULL, "
                    "rowid INTEGER NOT NULL)"
                )
            with Session(engine, expire_on_commit=False) as session:
                asyncio.run(_run(engine, session))
                assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        finally:
            engine.dispose()
    print("check_exam_chat: OK")


if __name__ == "__main__":
    main()
