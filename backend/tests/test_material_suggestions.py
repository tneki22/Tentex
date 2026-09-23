"""Подбор материалов Библиотеки под цель и темы свободного проекта — без модели."""

from uuid import uuid4

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_free_project,
    make_material,
    make_topic_node,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.bindings import search
from app.models import GoalPassport, Material, MaterialState
from app.projects.material_suggestions import MaterialSuggestionsWrite, suggest_materials


def _library_material(session: Session, seed: str, text: str, *, subject: str | None = None,
                      title: str | None = None) -> Material:
    material = make_material(session, seed)
    material.display_name = title or f"Материал {seed}"
    material.subject = subject
    session.commit()
    add_page_with_fragments(
        session, material, page_number=3, revision=1, fragments=[text], block_title="Глава",
    )
    search.reindex_material(session, material.id)
    return material


@pytest.mark.asyncio
async def test_query_groups_hits_by_material_and_skips_linked(session: Session) -> None:
    project = make_free_project(session)
    linked = _library_material(session, "a1", "Свёрточная сеть применяет операцию свёртки.")
    free = _library_material(session, "b2", "Операция свёртки скользит ядром по изображению.")
    _library_material(session, "c3", "Спрос и предложение формируют рыночную цену.")
    link_material(session, project, linked)

    result = await suggest_materials(
        session, project.id, MaterialSuggestionsWrite(query="операция свёртки"),
    )

    assert result.by_query is not None
    assert [item.material_id for item in result.by_query.items] == [free.id]
    item = result.by_query.items[0]
    assert item.hit_count == 1 and item.page_from == 3
    assert "ядром" in item.excerpt
    assert result.by_query.words_only


@pytest.mark.asyncio
async def test_subject_match_lifts_material_above_better_ranked(session: Session) -> None:
    project = make_free_project(session)
    session.add(GoalPassport(project_id=project.id, subject="  Машинное   обучение "))
    session.commit()
    _library_material(
        session, "d4", "Градиентный спуск. Градиентный спуск минимизирует функцию потерь.",
    )
    matching = _library_material(
        session, "e5", "Градиентный спуск в нейросетях.", subject="машинное обучение",
    )

    result = await suggest_materials(
        session, project.id, MaterialSuggestionsWrite(query="градиентный спуск"),
    )

    assert result.by_query is not None
    assert result.by_query.items[0].material_id == matching.id
    assert result.by_query.items[0].subject_match


@pytest.mark.asyncio
async def test_nodes_use_topic_title_and_search_hint(session: Session) -> None:
    project = make_free_project(session)
    wanted = _library_material(session, "f6", "Обратное распространение ошибки считает градиент.")
    topic = make_topic_node(session, project, title="Обучение сети")
    topic.material_search_queries = ["обратное распространение ошибки"]
    session.commit()

    result = await suggest_materials(
        session, project.id, MaterialSuggestionsWrite(node_ids=[topic.id]),
    )

    assert [item.material_id for item in result.by_node[topic.id].items] == [wanted.id]


@pytest.mark.asyncio
async def test_empty_or_unready_library_returns_nothing(session: Session) -> None:
    project = make_free_project(session)
    result = await suggest_materials(
        session, project.id, MaterialSuggestionsWrite(query="что угодно"),
    )
    assert result.by_query is not None and result.by_query.items == []

    processing = _library_material(session, "a7", "Свёртка изображения.")
    processing.status = MaterialState.PROCESSING
    session.commit()
    result = await suggest_materials(
        session, project.id, MaterialSuggestionsWrite(query="свёртка"),
    )
    assert result.by_query is not None and result.by_query.items == []


def test_command_takes_exactly_one_input() -> None:
    with pytest.raises(ValidationError):
        MaterialSuggestionsWrite()
    with pytest.raises(ValidationError):
        MaterialSuggestionsWrite(query="x", node_ids=[uuid4()])
