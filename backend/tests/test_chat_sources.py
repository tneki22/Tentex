"""Источники учебного чата на настоящей SQLite: области, операции, разнообразие материалов."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from sqlalchemy.orm import Session

from app.bindings import search as search_module
from app.exam import sources
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    ChatMessage,
    ChatMessageRole,
    Material,
    MaterialBlock,
    ProgramNode,
    Project,
)
from app.projects.errors import ProjectDomainError
from app.retrieval.schemas import RetrievalScope, RetrievalSearchRead, RetrievalSearchWrite
from app.retrieval.search import HybridRetriever, resolve_scope


def _material(
    session: Session, project: Project, name: str, blocks: list[str]
) -> tuple[Material, list[tuple[UUID, list[UUID]]]]:
    material = make_material(session, uuid4().hex[:12])
    material.display_name = name
    link_material(session, project, material)
    created = []
    for page, text in enumerate(blocks, start=1):
        added = add_page_with_fragments(
            session, material, page_number=page, revision=1, fragments=[text], block_title=name
        )
        # Хелпер создаёт блок с sort_order=0; следующий блок того же материала
        # иначе нарушил бы уникальность порядка.
        session.get(MaterialBlock, added.block_id).sort_order = page
        session.commit()
        created.append((added.block_id, added.fragment_ids))
    search_module.reindex_material(session, material.id)
    session.commit()
    return material, created


def _bind(
    session: Session,
    project: Project,
    node: ProgramNode,
    material: Material,
    block: tuple[UUID, list[UUID]],
    status: BindingStatus = BindingStatus.MANUAL,
) -> None:
    session.add(
        Binding(
            project_id=project.id,
            program_node_id=node.id,
            fragment_id=block[1][0],
            material_id=material.id,
            block_id=block[0],
            status=status,
            mechanism=BindingMechanism.MANUAL,
        )
    )
    session.commit()


async def _find(session: Session, project: Project, node: ProgramNode | None, text: str, *,
                scope: str = "project", operation: str = "discuss",
                tail: list[ChatMessage] | None = None) -> sources.FoundSources:
    return await sources.find_sources(
        session,
        project_id=project.id,
        node_id=node.id if node else None,
        text=text,
        tail=tail or [],
        scope=scope,
        material_ids=[],
        operation=operation,
    )


NOISE = "Нормализация отношений устраняет аномалии обновления в таблицах базы данных."


@pytest.mark.asyncio
async def test_chat_names_absent_material_answer(session: Session, monkeypatch) -> None:
    project = make_exam_project(session)

    async def no_match(_retriever, _session, command):
        return RetrievalSearchRead(
            query=command.query, strategy=command.strategy, index_id=None,
            degraded=False, degradation_reasons=[], results=[], no_relevant_match=True,
        )

    monkeypatch.setattr(HybridRetriever, "search", no_match)
    found = await _find(session, project, None, "иерархия скоростей OTN")
    assert not found.entries
    assert any("не найдено" in note for note in found.notes)


@pytest.mark.asyncio
async def test_linked_topic_filters_blocks_before_the_lexical_limit(session: Session) -> None:
    """60 совпадений вне темы раньше занимали все 50 мест BM25, и тема оставалась пустой."""
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вторая нормальная форма")
    target = "Вторая форма: нормализация без частичных зависимостей."
    material, blocks = _material(session, project, "Лекции", [NOISE] * 60 + [target])
    _bind(session, project, node, material, blocks[-1])
    _bind(session, project, node, material, blocks[0], BindingStatus.REMOVED)

    found = await _find(session, project, node, "нормализация", scope="linked_topic")

    assert [entry["text"] for entry in found.entries] == [target]


def test_linked_topic_without_live_bindings_is_rejected_before_the_turn(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Без привязок")
    material, blocks = _material(session, project, "Лекции", [NOISE])
    _bind(session, project, node, material, blocks[0], BindingStatus.REMOVED)

    with pytest.raises(ProjectDomainError) as error:
        sources.ensure_scope_has_places(session, project.id, node.id, "linked_topic")
    assert error.value.code == "retrieval_scope_empty"
    # Остальные области не требуют привязок.
    sources.ensure_scope_has_places(session, project.id, node.id, "topic_project")


def test_whole_project_searches_without_the_hidden_topic(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Нормальные формы")

    def semantic(scope: RetrievalScope) -> str:
        return resolve_scope(
            session,
            RetrievalSearchWrite(
                query="индексы", scope=scope, project_id=project.id, node_id=node.id
            ),
        ).semantic_query

    assert semantic(RetrievalScope.PROJECT) == "индексы"
    assert semantic(RetrievalScope.TOPIC_PROJECT) == "Тема: Нормальные формы\nЗапрос: индексы"


@pytest.mark.asyncio
async def test_comparison_does_not_treat_a_weak_word_match_as_second_source(
    session: Session,
) -> None:
    project = make_exam_project(session)
    _material(session, project, "Учебник", [f"{NOISE} Пример {index}." for index in range(12)])
    # Одно слово запроса в длинном тексте — BM25 ставит методичку ниже всех
    # двенадцати мест учебника, и в обычную выдачу из десяти она не попадает.
    _material(session, project, "Методичка", [
        "Тема связана с нормализацией косвенно: подробности в приложениях к курсу, "
        "где разобраны примеры проектирования схем и типичные ошибки студентов."
    ])

    discuss = await _find(session, project, None, "нормализация аномалии обновления")
    compare = await _find(
        session, project, None, "нормализация аномалии обновления", operation="compare_sources"
    )

    assert {entry["material"] for entry in discuss.entries} == {"Учебник"}
    assert {entry["material"] for entry in compare.entries} == {"Учебник"}
    assert sources.NO_SECOND_MATERIAL_NOTE in compare.notes


@pytest.mark.asyncio
async def test_comparison_keeps_a_relevant_second_material(session: Session) -> None:
    project = make_exam_project(session)
    _material(session, project, "Учебник", [NOISE] * 12)
    _material(session, project, "Методичка", [
        "Нормализация устраняет аномалии обновления при проектировании схем данных."
    ])

    compare = await _find(
        session, project, None, "нормализация аномалии обновления",
        operation="compare_sources",
    )

    assert {entry["material"] for entry in compare.entries[:2]} == {"Учебник", "Методичка"}


@pytest.mark.asyncio
async def test_comparison_with_a_single_material_says_so(session: Session) -> None:
    project = make_exam_project(session)
    _material(session, project, "Учебник", [NOISE])

    found = await _find(session, project, None, "нормализация", operation="find_discrepancies")

    assert sources.NO_SECOND_MATERIAL_NOTE in found.notes


@pytest.mark.asyncio
async def test_identical_text_of_two_materials_is_one_place_naming_both(session: Session) -> None:
    project = make_exam_project(session)
    _material(session, project, "main.typ", [NOISE])
    _material(session, project, "Экзамен.zip", [NOISE])

    found = await _find(session, project, None, "нормализация")

    assert len(found.entries) == 1
    kept = found.entries[0]
    other = {"main.typ", "Экзамен.zip"} - {kept["material"]}
    assert kept["also_in"] == list(other)


def test_short_follow_up_is_searched_alone_and_with_the_previous_question() -> None:
    tail = [
        ChatMessage(role=ChatMessageRole.USER, text="Как предотвратить взаимоблокировку?"),
        ChatMessage(role=ChatMessageRole.EXAMINER, text="Нарушить одно из условий Коффмана."),
    ]

    assert sources.retrieval_queries("А подробнее?", tail) == [
        "А подробнее?",
        "Как предотвратить взаимоблокировку?\nА подробнее?",
    ]
    long_question = (
        "Чем отличается предотвращение тупиков от их обхода и обнаружения в операционных системах?"
    )
    assert sources.retrieval_queries(long_question, tail) == [long_question]
    assert sources.retrieval_queries("Подробнее", []) == ["Подробнее"]
