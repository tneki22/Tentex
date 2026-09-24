"""Чат «Поиск в интернете»: план запросов → SearXNG → страницы → отбор по номеру кандидата."""

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.chat import project_sessions
from app.exam import chat as exam_chat
from app.materials import web_search
from app.materials.web_search import PageProbe, WebHit, WebSearchPage
from app.models import (
    ChatMessage,
    ChatMessageRole,
    ChatPayloadKind,
    ChatSession,
    ChatToolRun,
    ChatToolRunState,
    GoalPassport,
    Material,
    MaterialSourceKind,
    MaterialState,
    NodeType,
    ProgramBasisKind,
    ProgramNode,
    ProgramNodeSourcePageRange,
    Project,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    TemplateKey,
    WorkspaceVariant,
    utc_now,
)
from app.projects import program_chat, source_search_chat
from app.projects.errors import ProjectDomainError

CHANNEL = source_search_chat.CHANNEL


def _completion(payload: dict[str, object]) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(payload, ensure_ascii=False),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=50, output_tokens=50, cost_usd=Decimal("0.001")),
    )


def _node(session: Session, project: Project, title: str, **fields: object) -> ProgramNode:
    node = ProgramNode(
        project_id=project.id,
        parent_id=fields.get("parent_id"),
        node_type=fields.get("node_type", NodeType.TOPIC),
        sort_order=fields.get("sort_order", 0),
        title=title,
        is_in_current_program=True,
        needs_material=True,
        is_archived=False,
        basis_kind=ProgramBasisKind.CUSTOM,
        material_search_queries=fields.get("queries", []),
        material_kind=fields.get("kind"),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(node)
    session.commit()
    return node


@pytest.fixture
def project(session: Session) -> Project:
    """Свободный проект «ОС»: раздел с тремя темами, у одной уже есть страницы учебника."""
    value = Project(
        template_key=TemplateKey.FREE,
        workspace_variant=WorkspaceVariant.TEXTBOOK,
        status=ProjectStatus.ACTIVE,
        name="ОС",
    )
    session.add(value)
    session.flush()
    session.add(GoalPassport(project_id=value.id, subject="Операционные системы",
                             goal="Понять, как ОС управляет процессами"))
    session.commit()
    section = _node(session, value, "Процессы и потоки", node_type=NodeType.SECTION)
    _node(session, value, "Планирование процессов", parent_id=section.id, sort_order=0,
          queries=["планирование процессов ОС лекция"], kind="lecture")
    _node(session, value, "Потоки", parent_id=section.id, sort_order=1,
          queries=["потоки переключение контекста"], kind="textbook")
    with_pages = _node(session, value, "Взаимоблокировки", parent_id=section.id, sort_order=2,
                       queries=["взаимная блокировка условия"])
    material = Material(
        sha256=uuid4().hex * 2,
        original_name="Таненбаум.pdf",
        storage_path=f"text/{uuid4()}.txt",
        media_type="text/plain",
        source_kind=MaterialSourceKind.URL,
        source_url="https://attached.example/book",
        size_bytes=100,
        page_count=40,
        status=MaterialState.READY,
        outline=[],
    )
    session.add(material)
    session.flush()
    session.add(ProjectMaterial(
        project_id=value.id, material_id=material.id, source_role=SourceRole.MAIN, priority=0,
        affects_program=True, display_name="Таненбаум", purposes=["study_source"],
        created_at=utc_now(),
    ))
    session.add(ProgramNodeSourcePageRange(
        project_id=value.id, program_node_id=with_pages.id, material_id=material.id,
        source_name_snapshot="Таненбаум", outline_item_key="k", page_from=10, page_to=20,
    ))
    session.commit()
    return value


class _Web:
    """Подменённый SearXNG: выдача по запросам и объём страниц, плюс журнал вызовов."""

    def __init__(self, hits: list[WebHit], probes: dict[str, PageProbe]) -> None:
        self.hits = hits
        self.probes = probes
        self.queries: list[tuple[str, str, str]] = []
        self.probed: list[str] = []

    async def search_many(self, queries, limit: int = 8) -> list[WebSearchPage]:  # noqa: ANN001
        queries = list(queries)
        self.queries.extend(queries)
        return [WebSearchPage(hits=tuple(self.hits), unresponsive_engines=("google",))
                for _query in queries]

    async def probe_pages(self, urls: list[str]) -> dict[str, PageProbe]:
        self.probed.extend(urls)
        return {url: probe for url, probe in self.probes.items() if url in urls}


def _install(monkeypatch: pytest.MonkeyPatch, web: _Web) -> None:
    monkeypatch.setattr(web_search, "search_many", web.search_many)
    monkeypatch.setattr(web_search, "probe_pages", web.probe_pages)


HITS = [
    WebHit(url="https://www.lectures.example/os/sched/", title="Лекция: планирование",
           snippet="Алгоритмы FCFS, SJF, RR", engine="duckduckgo"),
    WebHit(url="https://attached.example/book", title="Уже в проекте", snippet="", engine="brave"),
    WebHit(url="https://files.example/os", title="Все лекции по ОС", snippet="Скачать",
           engine="brave"),
    WebHit(url="https://www.youtube.com/watch?v=abc", title="Видеолекция", snippet="",
           engine="youtube", duration="40:46", author="Кафедра"),
]
PROBES = {
    "https://www.lectures.example/os/sched/": PageProbe(kind="html", words=1800,
                                                        excerpt="Планировщик выбирает..."),
    "https://files.example/os": PageProbe(kind="html", words=90, file_links=14),
}
PLAN = {
    "reply": "Ищу лекции по планированию и общие курсы по ОС",
    "searches": [
        {"query": "планирование процессов ОС лекция", "category": "general", "language": "ru",
         "topics": ["1.1", "9.9"]},
        {"query": "операционные системы курс лекций", "category": "general", "language": "ru",
         "topics": []},
        {"query": "операционные системы курс лекций", "category": "general", "language": "ru",
         "topics": []},
        {"query": "планирование видеолекция", "category": "videos", "language": "ru",
         "topics": ["1.1"]},
    ],
}


@pytest.mark.asyncio
async def test_turn_searches_selected_topics_and_picks_candidates_by_id(
    session: Session, ai_config: str, project: Project, monkeypatch: pytest.MonkeyPatch,
) -> None:
    del ai_config
    web = _Web(HITS, PROBES)
    _install(monkeypatch, web)
    chat = project_sessions.create_session(session, project.id, CHANNEL)
    fake = FakeTransport(completions=[
        _completion(PLAN),
        _completion({
            "summary": "Нашлась лекция по планированию и каталог файлов.",
            "items": [
                {"id": 1, "kind": "lecture", "why": "Разбирает алгоритмы", "gist": "FCFS и RR",
                 "level": "beginner", "topics": ["1.1"]},
                {"id": 99, "kind": "lecture", "why": "Нет такого", "gist": "", "topics": []},
                {"id": 1, "kind": "lecture", "why": "Повтор", "gist": "", "topics": []},
                {"id": 2, "kind": "catalog", "why": "Файлы лекций", "gist": "Ссылки на PDF",
                 "level": "expert", "topics": []},
                {"id": 3, "kind": "weird", "why": "Видео", "gist": "", "topics": []},
            ],
            "follow_ups": ["Найди задачи по планированию"],
        }),
    ])
    message = await source_search_chat.send_message(
        session, ModelGateway(session, fake), project.id, chat.id, "Найди лекции",
    )

    # Дубли запросов схлопнуты, неизвестный номер темы отброшен.
    assert [query for query, _category, _language in web.queries] == [
        "планирование процессов ОС лекция", "операционные системы курс лекций",
        "планирование видеолекция",
    ]
    plan_prompt = json.dumps(fake.complete_requests[0]["messages"], ensure_ascii=False)
    assert "«планирование процессов ОС лекция»" in plan_prompt
    # «Только темы без материала»: тема со страницами учебника не предлагается к поиску.
    focus = plan_prompt.split("<focus_topics область=")[1].split("</focus_topics>")[0]
    assert "Взаимоблокировки" not in focus and "Потоки" in focus

    # Уже подключённый адрес не показывается, видео не открывается ради объёма.
    pick_prompt = fake.complete_requests[1]["messages"][-1]["content"]
    assert "attached.example" not in pick_prompt
    assert "[3] Видеолекция" in pick_prompt and "видео 40:46" in pick_prompt
    assert "https://www.youtube.com/watch?v=abc" not in web.probed

    assert message.role == ChatMessageRole.ASSISTANT
    assert message.payload_kind == ChatPayloadKind.TOOL_RESULT
    assert message.text == "Нашлась лекция по планированию и каталог файлов."
    payload = message.payload
    assert (payload["tool_key"], payload["output_kind"]) == (
        "search_external_sources", "source_search_results",
    )
    result = payload["result"]
    items = result["items"]
    assert [item["url"] for item in items] == [HITS[0].url, HITS[2].url, HITS[3].url]
    first, catalog, video = items
    # Объём — из прочитанной страницы, у модели его не спрашивают.
    assert first["volume"] == {"kind": "html", "words": 1800, "minutes": 10, "pages": None,
                               "size_bytes": None, "file_links": 0}
    assert first["host"] == "lectures.example"
    assert first["level"] == "beginner"
    planning = session.scalar(select(ProgramNode).where(
        ProgramNode.title == "Планирование процессов"))
    assert first["node_ids"] == [str(planning.id)]
    assert (catalog["kind"], catalog["level"], catalog["volume"]["file_links"]) == (
        "catalog", None, 14,
    )
    assert (video["kind"], video["volume"]) == ("video", {"kind": "video", "duration": "40:46"})
    assert result["hidden_attached"] == 1
    assert result["unresponsive_engines"] == ["google"]
    assert result["follow_ups"] == ["Найди задачи по планированию"]
    assert result["searches"][0]["node_ids"] == [str(planning.id)]

    run = session.scalar(select(ChatToolRun).where(ChatToolRun.session_id == chat.id))
    assert run.state == ChatToolRunState.SUCCEEDED
    assert run.message_id == message.id
    assert run.result["urls"] == [HITS[0].url, HITS[2].url, HITS[3].url]


@pytest.mark.asyncio
async def test_next_turn_hides_shown_pages_and_marks_searched_topics(
    session: Session, ai_config: str, project: Project, monkeypatch: pytest.MonkeyPatch,
) -> None:
    del ai_config
    _install(monkeypatch, _Web(HITS, PROBES))
    chat = project_sessions.create_session(session, project.id, CHANNEL)
    first_pick = {"summary": "Готово", "items": [
        {"id": index, "kind": "lecture", "why": "", "gist": "", "topics": []}
        for index in (1, 2, 3)
    ]}
    fake = FakeTransport(completions=[_completion(PLAN), _completion(first_pick),
                                      _completion(PLAN)])
    gateway = ModelGateway(session, fake)
    await source_search_chat.send_message(session, gateway, project.id, chat.id, "Найди")
    second = await source_search_chat.send_message(session, gateway, project.id, chat.id, "Ещё")

    # Всё найденное уже показано — отбирать нечего, второго вызова модели нет.
    assert len(fake.complete_requests) == 3
    assert second.payload["result"]["items"] == []
    assert second.payload["result"]["hidden_seen"] == 3
    assert "уже в проекте или показано раньше" in second.text
    focus = json.dumps(fake.complete_requests[2]["messages"], ensure_ascii=False)
    assert "Планирование процессов · без материала" in focus
    assert "· уже искали" in focus


@pytest.mark.asyncio
async def test_question_without_search_is_a_plain_answer(
    session: Session, ai_config: str, project: Project, monkeypatch: pytest.MonkeyPatch,
) -> None:
    del ai_config
    web = _Web(HITS, PROBES)
    _install(monkeypatch, web)
    chat = project_sessions.create_session(session, project.id, CHANNEL)
    fake = FakeTransport(completions=[
        _completion({"reply": "Для начала хватит одного курса лекций.", "searches": []}),
    ])
    message = await source_search_chat.send_message(
        session, ModelGateway(session, fake), project.id, chat.id, "С чего начать?",
    )
    assert message.payload_kind == ChatPayloadKind.NONE
    assert message.text == "Для начала хватит одного курса лекций."
    assert web.queries == []
    assert session.scalar(select(ChatToolRun).where(ChatToolRun.session_id == chat.id)) is None


@pytest.mark.asyncio
async def test_unavailable_searxng_keeps_user_message_and_logs_failed_run(
    session: Session, ai_config: str, project: Project, monkeypatch: pytest.MonkeyPatch,
) -> None:
    del ai_config

    async def down(*_args: object, **_kwargs: object) -> list[WebSearchPage]:
        raise web_search.WebSearchUnavailableError("SearXNG не отвечает")

    monkeypatch.setattr(web_search, "search_many", down)
    chat = project_sessions.create_session(session, project.id, CHANNEL)
    fake = FakeTransport(completions=[_completion(PLAN)])
    with pytest.raises(ProjectDomainError) as caught:
        await source_search_chat.send_message(
            session, ModelGateway(session, fake), project.id, chat.id, "Найди лекции",
        )
    assert caught.value.code == "web_search_unavailable"
    messages = list(session.scalars(select(ChatMessage).where(ChatMessage.session_id == chat.id)))
    assert [(item.role, item.text) for item in messages] == [(ChatMessageRole.USER, "Найди лекции")]
    run = session.scalar(select(ChatToolRun).where(ChatToolRun.session_id == chat.id))
    assert (run.state, run.error_code, run.message_id) == (
        ChatToolRunState.FAILED, "web_search_unavailable", None,
    )


def test_sessions_do_not_leak_between_project_chats(
    session: Session, ai_config: str, project: Project,
) -> None:
    del ai_config
    search = project_sessions.create_session(session, project.id, CHANNEL)
    build = project_sessions.create_session(session, project.id, program_chat.CHANNEL)
    assert search.title == "Поиск"
    assert [item.id for item in project_sessions.list_session_summaries(
        session, project.id, CHANNEL)] == [search.id]
    assert [item.id for item in project_sessions.list_session_summaries(
        session, project.id, program_chat.CHANNEL)] == [build.id]
    assert exam_chat.list_sessions(session, project.id, None) == []
    with pytest.raises(ProjectDomainError) as caught:
        project_sessions.get_session_detail(session, project.id, search.id, program_chat.CHANNEL)
    assert caught.value.code == "program_chat_session_not_found"


def test_context_flags_and_scope_shape_the_request(
    session: Session, ai_config: str, project: Project,
) -> None:
    del ai_config
    chat = project_sessions.create_session(session, project.id, CHANNEL)
    preview = {entry.kind: entry for entry in source_search_chat.context_preview(
        session, project.id, chat.id).manifest}
    assert preview["program_tree"].included and preview["program_tree"].count == 3
    assert preview["topic_queries"].count == 2
    assert preview["attached_materials"].count == 1

    streams = session.scalar(select(ProgramNode).where(ProgramNode.title == "Потоки"))
    project_sessions.update_context(session, project.id, chat.id,
                                    project_sessions.ProjectChatContextWrite(
                                        section_scope_node_id=streams.id,
                                        context_flags={"only_missing": False,
                                                       "topic_queries": False},
                                    ), CHANNEL)
    session.refresh(chat)
    ctx = source_search_chat.build_search_context(session, chat)
    assert [topic.title for topic in ctx.focus] == ["Потоки"]
    assert ctx.scope_label == "1.2 «Потоки»"
    assert "где искать" not in source_search_chat._context_message(ctx)  # noqa: SLF001

    project_sessions.update_context(session, project.id, chat.id,
                                    project_sessions.ProjectChatContextWrite(
                                        context_flags={"program": False}), CHANNEL)
    preview = {entry.kind: entry for entry in source_search_chat.context_preview(
        session, project.id, chat.id).manifest}
    assert (preview["program_tree"].included, preview["program_tree"].reason) == (
        False, "excluded_by_user",
    )
    with pytest.raises(ProjectDomainError) as caught:
        project_sessions.update_context(session, project.id, chat.id,
                                        project_sessions.ProjectChatContextWrite(
                                            context_flags={"primary_sources": True}), CHANNEL)
    assert caught.value.code == "source_search_chat_context_flag_unknown"
    assert session.get(ChatSession, chat.id).context_flags["program"] is False
