"""Поиск материалов в интернете: плагин `web` OpenRouter и сверка адресов с выдачей."""

import asyncio
import json
from decimal import Decimal

import pytest
from conftest import link_material, make_free_project, make_material, make_topic_node
from sqlalchemy.orm import Session

from app.ai.gateway import AiGatewayError, ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import (
    FakeTransport,
    ProviderCompletion,
    ProviderUsage,
    UrlCitation,
    _citations,
)
from app.background import registry
from app.models import (
    AiProviderConnection,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    GoalPassport,
)
from app.projects import source_search
from app.projects.errors import ProjectDomainError

CITED = "https://habr.com/ru/articles/convolution/"
VIDEO = "https://www.youtube.com/watch?v=abc123"


def _use_openrouter(session: Session) -> None:
    provider = session.query(AiProviderConnection).one()
    provider.catalog_profile = "openrouter"
    session.commit()


def _completion(candidates: list[dict[str, str]], citations: tuple[UrlCitation, ...]):
    return ProviderCompletion(
        content=json.dumps({"candidates": candidates}, ensure_ascii=False),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=400, output_tokens=120, cost_usd=Decimal("0.02")),
        citations=citations,
    )


def _candidate(url: str, kind: str = "article") -> dict[str, str]:
    return {"url": url, "title": "Свёртка простыми словами", "kind": kind, "why": "Разбирает ядро"}


def _run(session: Session, transport: FakeTransport, project_id, command):
    gateway = ModelGateway(session, transport)
    return asyncio.run(source_search.run(session, gateway, project_id, command))


def _start(session: Session, transport: FakeTransport, project_id, command):
    gateway = ModelGateway(session, transport)
    return asyncio.run(source_search.start(session, gateway, project_id, command))


def _single(url: str) -> FakeTransport:
    return FakeTransport(completions=[_completion([_candidate(url)], (UrlCitation(url=url),))])


def test_only_urls_from_search_results_survive(session: Session, ai_config: str) -> None:
    del ai_config
    _use_openrouter(session)
    project = make_free_project(session)
    topic = make_topic_node(session, project, title="Операция свёртки")
    topic.material_search_queries = ["операция свёртки"]
    session.add(
        GoalPassport(project_id=project.id, subject="Машинное обучение", goal="Понять CNN")
    )
    session.commit()
    transport = FakeTransport(completions=[_completion(
        [
            _candidate(CITED.rstrip("/")),  # тот же адрес без завершающей косой
            _candidate("https://made-up.example/lecture"),  # в выдаче его нет
            _candidate(VIDEO, "video"),
            _candidate("https://example.org/cnn.pdf", "pdf"),
        ],
        (
            UrlCitation(url=CITED, title="Хабр", content="Ядро   скользит по изображению"),
            UrlCitation(url="https://youtube.com/watch?v=abc123", title="Лекция"),
            UrlCitation(url="https://example.org/cnn.pdf"),
        ),
    )])
    command = source_search.SourceSearchWrite(
        query="операция свёртки", program_node_id=topic.id, confirmed=True,
    )

    result = _run(session, transport, project.id, command)

    assert [item.url for item in result.candidates] == [
        CITED, "https://youtube.com/watch?v=abc123", "https://example.org/cnn.pdf",
    ]
    assert [item.import_kind for item in result.candidates] == ["url", "youtube", "pdf_manual"]
    assert result.candidates[0].snippet == "Ядро скользит по изображению"
    assert result.unverified_count == 1
    request = transport.complete_requests[0]
    plugins = [{"id": "web", "max_results": source_search.WEB_RESULTS}]
    assert request["parameters"]["plugins"] == plugins
    messages = request["messages"]
    assert messages[-1] == {"role": "user", "content": "Учебные материалы: операция свёртки"}
    assert "операция свёртки" in messages[1]["content"]  # подсказки темы в контексте


def test_already_attached_urls_are_not_offered_again(session: Session, ai_config: str) -> None:
    del ai_config
    _use_openrouter(session)
    project = make_free_project(session)
    material = make_material(session, "a7")
    material.source_url = CITED
    link_material(session, project, material)
    command = source_search.SourceSearchWrite(query="свёртка", confirmed=True)

    result = _run(session, _single(CITED), project.id, command)

    assert result.candidates == []
    assert result.already_attached_count == 1


def test_other_provider_gets_clear_refusal_before_any_call(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_free_project(session)
    transport = FakeTransport(completions=[])
    command = source_search.SourceSearchWrite(query="свёртка", confirmed=True)

    with pytest.raises(ProjectDomainError) as start_error:
        _start(session, transport, project.id, command)
    assert start_error.value.code == "web_search_unsupported"
    with pytest.raises(AiGatewayError) as run_error:
        _run(session, transport, project.id, command)
    assert run_error.value.code == "web_search_unsupported"
    assert transport.complete_calls == 0


def test_job_result_waits_for_review(session: Session, ai_config: str) -> None:
    del ai_config
    _use_openrouter(session)
    project = make_free_project(session)
    command = source_search.SourceSearchWrite(query="свёртка", confirmed=True)
    gateway = ModelGateway(session, _single(CITED))

    started = asyncio.run(source_search.start(session, gateway, project.id, command))
    job = session.get(BackgroundJob, started.job_id)
    assert job is not None and job.kind == BackgroundJobKind.AI_SOURCE_SEARCH
    process_ai_job(session, job, gateway)

    session.expire_all()
    finished = session.get(BackgroundJob, started.job_id)
    assert finished is not None and finished.state == BackgroundJobState.COMPLETED
    assert finished.checkpoint["result"]["candidates"][0]["url"] == CITED
    assert registry.get_job(session, started.job_id).needs_review is True


def test_citations_are_read_from_openrouter_annotations() -> None:
    class Message:
        def model_dump(self) -> dict[str, object]:
            return {"annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {"url": CITED, "title": "Хабр", "content": "Текст"},
                },
                {"type": "file", "file": {}},
                {"type": "url_citation", "url_citation": {"title": "без адреса"}},
            ]}

    assert _citations(Message()) == (UrlCitation(url=CITED, title="Хабр", content="Текст"),)


def test_schema_retry_keeps_citations_of_the_first_search(session: Session, ai_config: str) -> None:
    """Повтор по схеме ищет заново по тексту замечания; первая выдача не теряется."""
    del ai_config
    _use_openrouter(session)
    project = make_free_project(session)
    first = ProviderCompletion(
        content="```json\n{}\n```",
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=10, output_tokens=5),
        citations=(UrlCitation(url=CITED, content="Ядро свёртки"),),
    )
    second = _completion([_candidate(CITED, "lecture")], (UrlCitation(url=VIDEO),))
    transport = FakeTransport(completions=[first, second])
    command = source_search.SourceSearchWrite(query="свёртка", confirmed=True)

    result = _run(session, transport, project.id, command)

    assert transport.complete_calls == 2
    assert [(item.url, item.kind) for item in result.candidates] == [(CITED, "other")]
    assert result.candidates[0].snippet == "Ядро свёртки"
    assert result.unverified_count == 0
