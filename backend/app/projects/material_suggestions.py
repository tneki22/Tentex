"""Подбор материалов Библиотеки под цель или темы проекта — без модели.

Детерминированное чтение пробелов (`TEXTBOOK_MODE.md` §11): для цели мастера или
для темы без материала общий `HybridRetriever` ищет по всей готовой Библиотеке,
кроме уже подключённого к проекту, а найденные места сводятся к материалам.
Работает офлайн: без активного индекса поиск идёт по словам (BM25), и ответ
прямо говорит об этом. Ничего не подключает и не привязывает сам.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materials.naming import material_display_name
from app.models import (
    GoalPassport,
    Material,
    MaterialFragment,
    MaterialPage,
    MaterialState,
    NodeType,
    ProgramNode,
    Project,
)
from app.projects.errors import ProjectNotFoundError
from app.retrieval.schemas import RetrievalHitRead, RetrievalScope, RetrievalSearchWrite
from app.retrieval.search import HybridRetriever

MAX_NODES = 40
EXCERPT_CHARS = 240


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialSuggestionsWrite(ApiModel):
    """Либо свободный запрос (цель мастера), либо темы программы — не оба сразу."""

    query: str | None = Field(default=None, min_length=1, max_length=2_000)
    node_ids: list[UUID] = Field(default_factory=list, max_length=MAX_NODES)
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def one_input(self):
        if (self.query is None) == (not self.node_ids):
            raise ValueError("Нужен либо query, либо node_ids")
        return self


class MaterialSuggestionRead(ApiModel):
    material_id: UUID
    display_name: str
    subject: str | None
    page_count: int | None
    has_outline: bool
    subject_match: bool
    hit_count: int
    signals: list[Literal["lexical", "semantic"]]
    block_title: str | None
    page_from: int | None
    page_to: int | None
    excerpt: str


class MaterialSuggestionsRead(ApiModel):
    query: str
    items: list[MaterialSuggestionRead]
    # Активного индекса нет — подбор шёл только по словам.
    words_only: bool


class MaterialSuggestionsResult(ApiModel):
    by_query: MaterialSuggestionsRead | None = None
    by_node: dict[UUID, MaterialSuggestionsRead] = Field(default_factory=dict)


def _normalized(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _node_query(node: ProgramNode, parent: ProgramNode | None) -> str:
    parts = [node.title]
    if parent is not None and parent.node_type == NodeType.SECTION:
        parts.append(parent.title)
    if node.material_search_queries:
        parts.append(node.material_search_queries[0])
    return ". ".join(parts)


def _materials_with_headings(session: Session, material_ids: list[UUID]) -> set[UUID]:
    """Тот же признак «есть оглавление», что у Библиотеки, по частичному индексу заголовков."""
    if not material_ids:
        return set()
    return set(
        session.scalars(
            select(MaterialFragment.material_id)
            .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
            .join(Material, Material.id == MaterialFragment.material_id)
            .where(
                MaterialFragment.material_id.in_(material_ids),
                MaterialPage.revision == Material.active_parse_revision,
                MaterialFragment.structure_level.is_not(None),
            )
            .distinct()
        )
    )


def _group(
    session: Session, hits: list[RetrievalHitRead], subject: str | None, limit: int
) -> list[MaterialSuggestionRead]:
    """Места выдачи → материалы: первое место материала задаёт его ранг и пример."""
    order: list[UUID] = []
    grouped: dict[UUID, list[RetrievalHitRead]] = {}
    for hit in hits:
        material_id = hit.locator.material_id
        if material_id not in grouped:
            order.append(material_id)
            grouped[material_id] = []
        grouped[material_id].append(hit)
    materials = {
        material.id: material
        for material in session.scalars(select(Material).where(Material.id.in_(order)))
    }
    with_headings = _materials_with_headings(session, order)
    wanted_subject = _normalized(subject)
    items: list[MaterialSuggestionRead] = []
    for material_id in order:
        material = materials.get(material_id)
        if material is None:
            continue
        material_hits = grouped[material_id]
        best = material_hits[0]
        signals = sorted({signal for hit in material_hits for signal in hit.signals})
        items.append(
            MaterialSuggestionRead(
                material_id=material.id,
                display_name=material_display_name(material),
                subject=material.subject,
                page_count=material.page_count,
                has_outline=bool(material.outline) or material.id in with_headings,
                subject_match=bool(wanted_subject)
                and _normalized(material.subject) == wanted_subject,
                hit_count=len(material_hits),
                signals=signals,  # type: ignore[arg-type]
                block_title=best.locator.block_title,
                page_from=best.locator.page_from,
                page_to=best.locator.page_to,
                excerpt=" ".join(best.text.split())[:EXCERPT_CHARS],
            )
        )
    # Совпадение предмета — повышающий сигнал, а не фильтр: внутри групп
    # сохраняется порядок выдачи поиска.
    items.sort(key=lambda item: not item.subject_match)
    return items[:limit]


async def _suggest(
    session: Session, project_id: UUID, query: str, subject: str | None, limit: int
) -> MaterialSuggestionsRead:
    has_library = session.scalar(
        select(Material.id).where(Material.status == MaterialState.READY).limit(1)
    )
    if has_library is None:
        return MaterialSuggestionsRead(query=query, items=[], words_only=False)
    result = await HybridRetriever().search(
        session,
        RetrievalSearchWrite(
            query=query,
            scope=RetrievalScope.LIBRARY,
            project_id=project_id,
            limit=50,
        ),
    )
    return MaterialSuggestionsRead(
        query=query,
        items=_group(session, result.results, subject, limit),
        words_only=result.index_id is None,
    )


async def suggest_materials(
    session: Session, project_id: UUID, command: MaterialSuggestionsWrite
) -> MaterialSuggestionsResult:
    if session.get(Project, project_id) is None:
        raise ProjectNotFoundError()
    passport = session.get(GoalPassport, project_id)
    subject = passport.subject if passport is not None else None
    if command.query is not None:
        return MaterialSuggestionsResult(
            by_query=await _suggest(session, project_id, command.query, subject, command.limit)
        )
    nodes = {
        node.id: node
        for node in session.scalars(
            select(ProgramNode).where(ProgramNode.project_id == project_id)
        )
    }
    by_node: dict[UUID, MaterialSuggestionsRead] = {}
    for node_id in command.node_ids:
        node = nodes.get(node_id)
        if node is None:
            raise ProjectNotFoundError("Тема программы не найдена")
        parent = nodes.get(node.parent_id) if node.parent_id else None
        by_node[node_id] = await _suggest(
            session, project_id, _node_query(node, parent), subject, command.limit
        )
    return MaterialSuggestionsResult(by_node=by_node)
