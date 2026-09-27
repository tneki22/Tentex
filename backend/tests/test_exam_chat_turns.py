"""Ход чата: подтверждение, предел контекста, стабильные S-ID и повтор без дублей."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy.orm import Session, sessionmaker

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderStreamEvent
from app.exam import chat as chat_service
from app.exam import reply as chat_reply
from app.exam import router as chat_router
from app.exam import sources as chat_sources
from app.exam.schemas import ChatMessageWrite, ChatSettingsWrite
from app.models import (
    AiModelCatalogEntry,
    AiSettings,
    ChatMessageRole,
    ChatMode,
    ChatSession,
    ChatStreamState,
    PageQuality,
)
from app.projects.errors import ProjectDomainError
from app.retrieval.citations import citation_error
from app.retrieval.context import AssembledContext
from app.retrieval.schemas import (
    RetrievalHitRead,
    RetrievalLocatorRead,
    RetrievalSearchRead,
    RetrievalSearchWrite,
    SearchStrategy,
)

CHUNKS = [UUID(int=index + 1) for index in range(6)]


def _hit(index: int, text: str) -> RetrievalHitRead:
    return RetrievalHitRead(
        locator=RetrievalLocatorRead(
            chunk_id=CHUNKS[index],
            material_id=UUID(int=100 + index % 2),
            material_name=f"Материал {index % 2 + 1}",
            block_id=None,
            block_title=None,
            page_from=index + 1,
            page_to=None,
            fragment_ids=[],
        ),
        text=text,
        quality=PageQuality.NATIVE,
        score=1.0,
        signals=["lexical"],
    )


class _Search:
    """Подставленный поиск: выдача задаётся на каждый ход."""

    def __init__(self) -> None:
        self.results: list[RetrievalHitRead] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        search = self

        class Retriever:
            async def search(
                self, session: Session, command: RetrievalSearchWrite
            ) -> RetrievalSearchRead:
                del session
                return RetrievalSearchRead(
                    query=command.query, strategy=SearchStrategy.HYBRID, index_id=None,
                    degraded=False, degradation_reasons=[], results=search.results,
                )

        class Assembler:
            def assemble(self, session: Session, result: RetrievalSearchRead) -> AssembledContext:
                del session
                return AssembledContext(sources=result.results, token_count=0, truncated=False)

        monkeypatch.setattr(chat_sources, "HybridRetriever", Retriever)
        monkeypatch.setattr(chat_sources, "ContextAssembler", Assembler)


@pytest.fixture
def study(session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch):
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Нормальные формы")
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(mode=ChatMode.STUDY)
    )
    search = _Search()
    search.install(monkeypatch)
    fake = FakeTransport()
    monkeypatch.setattr("app.ai.gateway.production_transport", lambda db, modality: fake)
    monkeypatch.setattr(
        chat_router, "SessionLocal", sessionmaker(bind=session.bind, expire_on_commit=False)
    )
    return project, chat, search, fake


def _frames(chunks: list[str]) -> list[tuple[str, dict]]:
    frames = []
    for chunk in chunks:
        event, data = chunk.strip().split("\n", 1)
        frames.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return frames


async def _send(session: Session, project, chat, **fields) -> list[tuple[str, dict]]:
    response = await chat_router.post_chat_message(
        project_id=project.id,
        session_id=chat.id,
        command=ChatMessageWrite(**{"text": "Что такое 2НФ?", **fields}),
        session=session,
        gateway=ModelGateway(session),
    )
    return _frames([chunk async for chunk in response.body_iterator])


def _messages(session: Session, project, chat):
    return chat_service.get_session_detail(session, project.id, chat.id).messages


def _answer(text: str) -> list[ProviderStreamEvent]:
    return [ProviderStreamEvent(delta=text)]


@pytest.mark.asyncio
async def test_expensive_turn_asks_first_and_writes_nothing_until_confirmed(
    session: Session, study
) -> None:
    project, chat, search, fake = study
    session.get(AiSettings, 1).confirm_cost_usd = Decimal("0")
    session.commit()
    search.results = [_hit(0, "Вторая нормальная форма исключает частичные зависимости.")]
    fake.streams.append(_answer("Ответ [S1]."))

    with pytest.raises(ProjectDomainError) as asked:
        await _send(session, project, chat, client_turn_id="turn-0001")
    context = asked.value.context
    assert asked.value.code == "ai_confirmation_required"
    assert context["reasons"] == ["cost_threshold"]
    assert Decimal(context["max_cost_usd"]) == Decimal(context["estimated_cost_usd"]) * 2
    assert _messages(session, project, chat) == []
    assert fake.stream_calls == 0

    frames = await _send(
        session, project, chat, client_turn_id="turn-0001",
        confirmed_request_hash=context["request_hash"],
    )
    assert frames[-1][0] == "completed"
    # Модель получила ровно подтверждённый запрос, вопрос — один раз в конце.
    messages = fake.stream_requests[0]["messages"]
    assert messages[-1]["content"] == "Что такое 2НФ?"
    assert sum(message["content"] == "Что такое 2НФ?" for message in messages) == 1


@pytest.mark.asyncio
async def test_changed_settings_after_the_estimate_need_a_new_confirmation(
    session: Session, study
) -> None:
    project, chat, search, fake = study
    session.get(AiSettings, 1).confirm_cost_usd = Decimal("0")
    session.commit()
    search.results = [_hit(0, "Место")]
    with pytest.raises(ProjectDomainError) as first:
        await _send(session, project, chat)
    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(context_flags={"profile": False})
    )
    search.results = [_hit(1, "Другое место после смены ревизии")]

    with pytest.raises(ProjectDomainError) as again:
        await _send(
            session, project, chat, confirmed_request_hash=first.value.context["request_hash"]
        )
    assert again.value.code == "ai_confirmation_required"
    assert again.value.context["request_hash"] != first.value.context["request_hash"]


@pytest.mark.asyncio
async def test_over_budget_offers_trimmed_expanded_or_nothing(session: Session, study) -> None:
    project, chat, search, fake = study
    # Обычные фразы: ≈ 1140 токенов локальной оценки на место, шесть мест
    # не влезают в долю источников (6000) предела по умолчанию.
    long_text = "Нормальная форма устраняет избыточность данных. " * 190
    search.results = [_hit(index, f"{index} {long_text}") for index in range(6)]

    with pytest.raises(ProjectDomainError) as asked:
        await _send(session, project, chat, client_turn_id="turn-budget")
    context = asked.value.context
    assert context["reasons"] == ["context_over_budget"]
    budget = context["budget"]
    assert budget["limit"] == chat_reply.DEFAULT_BUDGET_TOKENS
    assert budget["needed"] > budget["limit"]
    assert context["manifest"], "сокращённое и исключённое видно до отправки"
    expanded = context["expanded"]
    assert expanded["budget_tokens"] == budget["needed"]

    # «Отправить сокращённым» — тот же хеш, пять мест из шести не влезли целиком.
    fake.streams.append(_answer("Коротко [S1]."))
    frames = await _send(
        session, project, chat, client_turn_id="turn-budget",
        confirmed_request_hash=context["request_hash"],
    )
    assert frames[-1][0] == "completed"
    trimmed_sources = frames[0][1]["sources"]
    assert len(trimmed_sources) < 6

    # «Увеличить предел и отправить» — новый ход с пределом и хешем из expanded.
    fake.streams.append(_answer("Полно [S1]."))
    frames = await _send(
        session, project, chat, client_turn_id="turn-budget-2",
        context_budget_tokens=expanded["budget_tokens"],
        confirmed_request_hash=expanded["request_hash"], remember_budget=True,
    )
    assert frames[-1][0] == "completed"
    assert len(frames[0][1]["sources"]) == 6
    session.expire_all()
    assert session.get(ChatSession, chat.id).context_budget_tokens == expanded["budget_tokens"]


@pytest.mark.asyncio
async def test_budget_beyond_the_model_window_is_refused(session: Session, study) -> None:
    project, chat, search, fake = study
    entry = session.query(AiModelCatalogEntry).one()
    entry.context_length = 4_000
    session.commit()
    search.results = [
        _hit(index, "Нормальная форма устраняет избыточность данных. " * 190) for index in range(6)
    ]

    with pytest.raises(ProjectDomainError) as asked:
        await _send(session, project, chat)
    assert asked.value.context["expanded"] is None
    assert asked.value.context["budget"]["maximum"] < asked.value.context["budget"]["needed"]

    with pytest.raises(ProjectDomainError) as refused:
        await _send(session, project, chat, context_budget_tokens=50_000)
    assert refused.value.code == "chat_context_budget_too_large"


@pytest.mark.asyncio
async def test_source_ids_stay_the_same_across_turns_and_can_be_asked_about(
    session: Session, study
) -> None:
    project, chat, search, fake = study
    search.results = [_hit(0, "Первое место"), _hit(1, "Второе место")]
    fake.streams.append(_answer("Первое [S1], второе [S2]."))
    await _send(session, project, chat, text="Что такое 1НФ?")

    search.results = [_hit(2, "Третье место"), _hit(1, "Второе место")]
    fake.streams.append(_answer("Новое [S3], прежнее [S2]; а что в S1 — [S1]."))
    frames = await _send(session, project, chat, text="А что было в S1?")

    ids = {source["id"]: source["text"] for source in frames[0][1]["sources"]}
    assert ids == {"S3": "Третье место", "S2": "Второе место", "S1": "Первое место"}
    assert frames[-1][0] == "completed"


@pytest.mark.asyncio
async def test_retry_with_the_same_turn_id_does_not_duplicate_the_question(
    session: Session, study
) -> None:
    project, chat, search, fake = study
    search.results = [_hit(0, "Место")]
    fake.streams.append(_answer("Без ссылок вообще."))
    fake.streams.append(_answer("Снова без ссылок."))
    first = await _send(
        session, project, chat, client_turn_id="turn-retry", operation="compare_sources"
    )
    assert first[-1][0] == "error"

    fake.streams.append(_answer("Теперь со ссылкой [S1]."))
    # Клиент прислал другую операцию — повтор всё равно берёт её из снимка хода.
    again = await _send(session, project, chat, client_turn_id="turn-retry")
    assert again[-1][0] == "completed", again[-1]
    messages = _messages(session, project, chat)
    assert [message.role for message in messages].count(ChatMessageRole.USER) == 1
    assert "Операция: сравнить источники" in fake.stream_requests[-1]["messages"][0]["content"]
    history = fake.stream_requests[-1]["messages"]
    assert sum(message["content"] == "Что такое 2НФ?" for message in history) == 1

    # Уже отвеченный ход не вызывает модель ещё раз.
    calls = fake.stream_calls
    replay = await _send(session, project, chat, client_turn_id="turn-retry")
    assert replay[-1][0] == "completed" and replay[-1][1]["cached"] is True
    assert fake.stream_calls == calls


@pytest.mark.asyncio
async def test_history_excludes_failed_and_service_messages_and_legacy_ids(
    session: Session, study
) -> None:
    project, chat, search, fake = study
    user = chat_service.append_message(
        session, chat, role=ChatMessageRole.USER, text="Старый вопрос"
    )
    chat_service.append_message(
        session, chat, role=ChatMessageRole.EXAMINER, text="Старый ответ [S1].",
        context_snapshot={"retrieval_sources": [
            {"id": "S1", "material": "Лекции", "locator": "стр. 3", "chunk_id": str(uuid4())}
        ]},
    )
    chat_service.append_message(session, chat, role=ChatMessageRole.USER, text="Упавший вопрос")
    chat_service.append_message(
        session, chat, role=ChatMessageRole.EXAMINER, text="",
        stream_state=ChatStreamState.FAILED,
    )
    chat_service.append_message(session, chat, role=ChatMessageRole.SYSTEM, text="Модель: A → B")
    del user
    search.results = [_hit(0, "Место")]
    fake.streams.append(_answer("Ответ [S1]."))

    await _send(session, project, chat)

    contents = [message["content"] for message in fake.stream_requests[0]["messages"]]
    assert "Старый ответ [Лекции, стр. 3]." in contents
    assert "Упавший вопрос" not in contents
    assert not any("Модель: A → B" in content for content in contents)


@pytest.mark.asyncio
async def test_retrieval_can_be_switched_off_and_unknown_ids_fail_without_sources(
    session: Session, study
) -> None:
    project, chat, search, fake = study
    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(context_flags={"retrieval": False})
    )
    search.results = [_hit(0, "Место, которое не должно уйти")]
    fake.streams.append(_answer("Выдуманная ссылка [S7]."))
    fake.streams.append(_answer("Опять [S7]."))

    frames = await _send(session, project, chat)

    assert frames[0][1]["sources"] == []
    assert not any(
        "Место, которое не должно уйти" in message["content"]
        for message in fake.stream_requests[0]["messages"]
    )
    assert frames[-1][0] == "error"
    assert frames[-1][1]["code"] == "chat_invalid_citations"


def test_citation_check_reads_grouped_ids_and_rejects_invented_ones() -> None:
    allowed = {"S1", "S2"}
    assert citation_error("Факт [S1, S2]; ещё [S2][S1].", allowed) is None
    assert citation_error("Факт без ссылки.", allowed) is not None
    assert citation_error("Факт [S1; S9].", allowed) is not None
    assert citation_error("Без источников и без ссылок.", set()) is None
    assert citation_error("Без источников, но [S1].", set()) is not None
