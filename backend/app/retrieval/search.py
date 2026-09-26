from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session, defer

from app.bindings.search import SearchHit, search_fragments
from app.config import settings as app_settings
from app.materials.naming import material_display_name
from app.models import (
    Binding,
    BindingStatus,
    EmbeddingProfile,
    Material,
    MaterialFragment,
    MaterialPage,
    MaterialState,
    ProgramNode,
    Project,
    ProjectMaterial,
    RetrievalChunk,
    RetrievalIndex,
    RetrievalPreset,
    RetrievalSettings,
)
from app.projects.errors import ProjectNotFoundError
from app.retrieval.embeddings import backend_for_profile
from app.retrieval.presets import PRESETS, PresetConfig
from app.retrieval.schemas import (
    RetrievalHitRead,
    RetrievalLocatorRead,
    RetrievalScope,
    RetrievalSearchRead,
    RetrievalSearchWrite,
    SearchStrategy,
)
from app.retrieval.vector import SqliteVecIndex, reciprocal_rank_fusion


@dataclass(frozen=True)
class ScopeFilter:
    material_ids: list[UUID]
    block_ids: list[UUID] | None
    semantic_query: str


class HybridRetriever:
    """Единственная точка общего lexical+dense retrieval для всех потребителей."""

    def __init__(
        self,
        vector_index: SqliteVecIndex | None = None,
        *,
        index_id: UUID | None = None,
    ) -> None:
        self.vector_index = vector_index or SqliteVecIndex()
        self.index_id = index_id

    async def search(self, session: Session, command: RetrievalSearchWrite) -> RetrievalSearchRead:
        """Найти места по стратегии запроса и собрать из них проверяемую выдачу.

        Порядок фиксированный: кандидаты BM25 → кандидаты по смыслу → слияние →
        optional reranker → чтение кусков. Отсутствие индекса, устаревшая ревизия
        и недоступный reranker не прерывают поиск: каждая такая потеря
        превращается в причину деградации рядом с результатом.
        """
        scope = resolve_scope(session, command)
        settings = session.get(RetrievalSettings, 1)
        active = self._active_index(session, settings)
        preset = PRESETS[settings.preset] if settings else PRESETS[RetrievalPreset.BALANCED]
        expert = settings.expert_parameters if settings else {}
        reasons: list[str] = []
        pseudo_by_id: dict[UUID, SearchHit] = {}

        lexical_ids: list[UUID] = []
        if command.strategy != SearchStrategy.SEMANTIC:
            hits = _lexical_candidates(session, scope, command.query, preset.lexical_candidates)
            lexical_ids = _lexical_ids(session, active, hits, pseudo_by_id)

        semantic_ids: list[UUID] = []
        if command.strategy != SearchStrategy.LEXICAL:
            semantic_ids = await self._semantic_ids(session, scope, active, preset, reasons)

        if not semantic_ids and command.strategy == SearchStrategy.SEMANTIC:
            # Чистый semantic-запрос без индекса возвращает не пустоту, а BM25:
            # это явно названная деградация, а не отсутствие ответа.
            hits = _lexical_candidates(session, scope, command.query, preset.lexical_candidates)
            lexical_ids = _lexical_ids(session, active, hits, pseudo_by_id)
            reasons.append("Semantic-поиск заменён поиском по словам")

        reasons.extend(_degradation_notes(session, active, scope))
        ranking = _ranking(command.strategy, lexical_ids, semantic_ids, preset, expert)
        chunk_by_id = _load_chunks(session, [item_id for item_id, _, _ in ranking])

        if preset.rerank_depth and ranking:
            try:
                ranking = await _rerank(
                    command.query,
                    ranking,
                    chunk_by_id,
                    pseudo_by_id,
                    depth=int(expert.get("rerank_depth", preset.rerank_depth)),
                    model_id=str(expert.get("reranker_model_id", "Qwen/Qwen3-Reranker-0.6B")),
                )
            except Exception as error:  # noqa: BLE001 — RRF remains a valid result
                reasons.append(f"Reranker недоступен; сохранён порядок RRF: {error}")

        return RetrievalSearchRead(
            query=command.query,
            strategy=command.strategy,
            index_id=active.id if active else None,
            degraded=bool(reasons),
            degradation_reasons=reasons,
            results=self._read_ranking(
                session, ranking, chunk_by_id, pseudo_by_id,
                limit=min(command.limit, preset.final_results),
            ),
        )

    def _active_index(
        self, session: Session, settings: RetrievalSettings | None
    ) -> RetrievalIndex | None:
        """Индекс запроса: явно переданный (benchmark) или активный на установке."""
        if self.index_id is not None:
            return session.get(RetrievalIndex, self.index_id)
        if settings is None or settings.active_index_id is None:
            return None
        return session.get(RetrievalIndex, settings.active_index_id)

    async def _semantic_ids(
        self,
        session: Session,
        scope: ScopeFilter,
        active: RetrievalIndex | None,
        preset: PresetConfig,
        reasons: list[str],
    ) -> list[UUID]:
        """Кандидаты по смыслу; каждая причина отказа названа словами в `reasons`."""
        if active is None:
            reasons.append("Активный semantic-индекс не выбран; выполнен поиск по словам")
            return []
        profile = session.get(EmbeddingProfile, active.profile_id)
        if profile is None:
            reasons.append("Embedding-профиль активного индекса недоступен")
            return []
        try:
            vector = await backend_for_profile(session, profile).embed_query(scope.semantic_query)
            return [
                hit.chunk_id
                for hit in self.vector_index.search(
                    session,
                    index_id=active.id,
                    material_ids=scope.material_ids,
                    query_vector=vector,
                    limit=preset.semantic_candidates,
                    block_ids=scope.block_ids,
                )
            ]
        except Exception as error:  # noqa: BLE001 — lexical fallback is the contract
            reasons.append(f"Поиск по смыслу недоступен: {error}")
            return []

    def _read_ranking(
        self,
        session: Session,
        ranking: list[tuple[UUID, float, list[str]]],
        chunk_by_id: dict[UUID, RetrievalChunk],
        pseudo_by_id: dict[UUID, SearchHit],
        *,
        limit: int,
    ) -> list[RetrievalHitRead]:
        """Прочитать выбранные места: куски индекса, иначе — исходный фрагмент BM25."""
        results: list[RetrievalHitRead] = []
        for item_id, score, signals in ranking:
            chunk = chunk_by_id.get(item_id)
            if chunk is not None:
                results.append(chunk_read(session, chunk, score, signals))
            elif (lexical := pseudo_by_id.get(item_id)) is not None:
                results.append(_lexical_read(lexical, score))
            if len(results) >= limit:
                break
        return results


def _lexical_candidates(
    session: Session, scope: ScopeFilter, query: str, limit: int
) -> list[SearchHit]:
    """Кандидаты BM25 внутри границ области."""
    outcome = search_fragments(session, scope.material_ids, query, limit=limit)
    return [
        hit for hit in outcome.hits if scope.block_ids is None or hit.block_id in scope.block_ids
    ]


def _lexical_ids(
    session: Session,
    active: RetrievalIndex | None,
    hits: list[SearchHit],
    pseudo_by_id: dict[UUID, SearchHit],
) -> list[UUID]:
    """Перевести найденные BM25 фрагменты в куски активного индекса.

    Место — кусок, в котором лежит найденный фрагмент, а не первый кусок его
    блока: иначе совпадение в середине длинного раздела показывало его начало.
    Фрагмент есть в поиске по словам, но не попал в куски проиндексированного
    материала — это колонтитул или номер страницы, такое место не выдаётся.
    Материала нет в индексе — например, он переиндексируется прямо сейчас, —
    и место остаётся под id своего фрагмента в `pseudo_by_id`: BM25 продолжает
    отвечать и без готового индекса.
    """
    chunk_by_fragment, indexed_materials = _chunk_lookup(session, active, hits)
    ids: list[UUID] = []
    for hit in hits:
        chunk_id = next(
            (
                chunk_by_fragment[str(fragment_id)]
                for fragment_id in hit.fragment_ids
                if str(fragment_id) in chunk_by_fragment
            ),
            None,
        )
        if chunk_id is None:
            if hit.material_id in indexed_materials:
                continue
            chunk_id = hit.fragment_ids[0]
            pseudo_by_id[chunk_id] = hit
        if chunk_id not in ids:
            ids.append(chunk_id)
    return ids


def _chunk_lookup(
    session: Session, active: RetrievalIndex | None, hits: list[SearchHit]
) -> tuple[dict[str, UUID], set[UUID]]:
    """Кусок по id фрагмента и материалы, чья текущая ревизия есть в индексе."""
    if active is None or not hits:
        return {}, set()
    fragment_ids = sorted({str(item) for hit in hits for item in hit.fragment_ids})
    material_ids = sorted({hit.material_id.hex for hit in hits})
    fragment_params = {f"f{number}": item for number, item in enumerate(fragment_ids)}
    material_params = {f"m{number}": item for number, item in enumerate(material_ids)}
    material_list = ", ".join(f":{key}" for key in material_params)
    current_revision = (
        "retrieval_chunks.revision = (SELECT active_parse_revision FROM materials "
        "WHERE materials.id = retrieval_chunks.material_id)"
    )
    # Материалы и ревизия сужают поиск до кусков найденных материалов, а
    # покрывающий индекс отдаёт fragment_ids без чтения текста и вектора.
    # Порядок кусков восстанавливается в Python: ORDER BY уводил SQLite на
    # индекс (index_id, sort_order) и полное чтение строк.
    rows = session.execute(
        text(
            "SELECT retrieval_chunks.id, retrieval_chunks.sort_order, item.value "
            "FROM retrieval_chunks, json_each(retrieval_chunks.fragment_ids) AS item "
            "WHERE retrieval_chunks.index_id = :index_id "
            f"AND retrieval_chunks.material_id IN ({material_list}) "
            f"AND {current_revision} "
            f"AND item.value IN ({', '.join(f':{key}' for key in fragment_params)})"
        ),
        {"index_id": active.id.hex, **material_params, **fragment_params},
    ).all()
    chunk_by_fragment: dict[str, UUID] = {}
    for chunk_hex, _, fragment_id in sorted(rows, key=lambda row: row[1]):
        # Из-за перекрытия фрагмент бывает в двух кусках: выдаётся первый.
        chunk_by_fragment.setdefault(fragment_id, UUID(hex=chunk_hex))
    # EXISTS останавливается на первом куске текущей ревизии; DISTINCT по
    # кускам читал строки всех кусков материала вместе с их текстом.
    indexed = session.execute(
        text(
            "SELECT materials.id FROM materials "
            f"WHERE materials.id IN ({material_list}) "
            "AND EXISTS (SELECT 1 FROM retrieval_chunks "
            "WHERE retrieval_chunks.index_id = :index_id "
            "AND retrieval_chunks.material_id = materials.id "
            "AND retrieval_chunks.revision = materials.active_parse_revision)"
        ),
        {"index_id": active.id.hex, **material_params},
    ).all()
    return chunk_by_fragment, {UUID(hex=row[0]) for row in indexed}


def _load_chunks(session: Session, chunk_ids: list[UUID]) -> dict[UUID, RetrievalChunk]:
    """Прочитать только куски из выдачи, без векторов: их может быть тысячи в области."""
    if not chunk_ids:
        return {}
    return {
        chunk.id: chunk
        for chunk in session.scalars(
            select(RetrievalChunk)
            .options(defer(RetrievalChunk.embedding))
            .where(RetrievalChunk.id.in_(chunk_ids))
        )
    }


def _degradation_notes(
    session: Session, active: RetrievalIndex | None, scope: ScopeFilter
) -> list[str]:
    """Нейтральные причины неполноты: устаревшие ревизии и визуальные страницы."""
    notes: list[str] = []
    if active is not None:
        stale = _stale_material_names(session, active, scope.material_ids)
        if stale:
            notes.append("Часть источников — только поиск по словам: " + ", ".join(stale))
    visual = visual_page_locators(session, scope.material_ids)
    if visual:
        preview = ", ".join(f"{name}, стр. {page}" for name, page in visual[:5])
        suffix = "" if len(visual) <= 5 else f" и ещё {len(visual) - 5}"
        notes.append("Визуальные страницы не проверены vision-моделью: " + preview + suffix)
    return notes


def _ranking(
    strategy: SearchStrategy,
    lexical_ids: list[UUID],
    semantic_ids: list[UUID],
    preset: PresetConfig,
    expert: dict[str, object],
) -> list[tuple[UUID, float, list[str]]]:
    """Один список мест из одного или двух сигналов."""
    if strategy == SearchStrategy.LEXICAL:
        return [(item_id, 1.0 / rank, ["lexical"]) for rank, item_id in enumerate(lexical_ids, 1)]
    if strategy == SearchStrategy.SEMANTIC:
        source_ids = semantic_ids or lexical_ids
        signal = "semantic" if semantic_ids else "lexical"
        return [(item_id, 1.0 / rank, [signal]) for rank, item_id in enumerate(source_ids, 1)]
    return reciprocal_rank_fusion(
        lexical_ids,
        semantic_ids,
        k=int(expert.get("rrf_k", preset.rrf_k)),
        lexical_weight=float(expert.get("lexical_weight", 1.0)),
        semantic_weight=float(expert.get("semantic_weight", 1.0)),
    )


def resolve_scope(session: Session, command: RetrievalSearchWrite) -> ScopeFilter:
    if command.scope == RetrievalScope.SELECTED_MATERIALS:
        existing = set(
            session.scalars(select(Material.id).where(Material.id.in_(command.material_ids)))
        )
        if len(existing) != len(set(command.material_ids)):
            raise ProjectNotFoundError("Один из выбранных материалов не найден")
        return ScopeFilter(command.material_ids, None, command.query)
    if command.scope == RetrievalScope.LIBRARY:
        query = select(Material.id).where(Material.status == MaterialState.READY)
        if command.project_id is not None:
            query = query.where(
                Material.id.not_in(
                    select(ProjectMaterial.material_id).where(
                        ProjectMaterial.project_id == command.project_id
                    )
                )
            )
        return ScopeFilter(list(session.scalars(query)), None, command.query)
    assert command.project_id is not None
    if session.get(Project, command.project_id) is None:
        raise ProjectNotFoundError()
    material_ids = list(
        session.scalars(
            select(ProjectMaterial.material_id).where(
                ProjectMaterial.project_id == command.project_id
            )
        )
    )
    block_ids: list[UUID] | None = None
    semantic_query = command.query
    if command.node_id is not None:
        node = session.get(ProgramNode, command.node_id)
        if node is None or node.project_id != command.project_id:
            raise ProjectNotFoundError("Тема программы не найдена")
        semantic_query = f"Тема: {node.title}\nЗапрос: {command.query}"
        if command.scope == RetrievalScope.LINKED_TOPIC:
            block_ids = list(
                session.scalars(
                    select(Binding.block_id)
                    .where(
                        Binding.project_id == command.project_id,
                        Binding.program_node_id == command.node_id,
                        Binding.status != BindingStatus.REMOVED,
                        Binding.block_id.is_not(None),
                    )
                    .distinct()
                )
            )
    return ScopeFilter(material_ids, block_ids, semantic_query)


def chunk_read(
    session: Session, chunk: RetrievalChunk, score: float, signals: list[str]
) -> RetrievalHitRead:
    material = session.get(Material, chunk.material_id)
    assert material is not None
    quality_warning = (
        "Текст распознан с низкой уверенностью — сверьтесь со страницей"
        if chunk.quality and chunk.quality.value == "ocr_low"
        else None
    )
    adjusted_score = score * (0.85 if quality_warning else 1.0)
    return RetrievalHitRead(
        locator=RetrievalLocatorRead(
            chunk_id=chunk.id,
            material_id=chunk.material_id,
            material_name=material_display_name(material),
            block_id=chunk.block_id,
            block_title=chunk.title,
            page_from=chunk.page_from,
            page_to=chunk.page_to,
            fragment_ids=[UUID(item) for item in chunk.fragment_ids],
            typst_path=chunk.locator.get("typst_path"),
            line_from=chunk.locator.get("line_from"),
            line_to=chunk.locator.get("line_to"),
        ),
        text=chunk.text,
        quality=chunk.quality,
        score=adjusted_score,
        signals=signals,
        warning=quality_warning,
    )


def _lexical_read(hit: SearchHit, score: float) -> RetrievalHitRead:
    return RetrievalHitRead(
        locator=RetrievalLocatorRead(
            chunk_id=hit.fragment_ids[0],
            material_id=hit.material_id,
            material_name=hit.material_name,
            block_id=hit.block_id,
            block_title=hit.block_title,
            page_from=hit.page_from,
            page_to=hit.page_to,
            fragment_ids=hit.fragment_ids,
        ),
        text=hit.text,
        quality=hit.quality,
        score=score,
        signals=["lexical"],
        warning=(
            "Текст распознан с низкой уверенностью — сверьтесь со страницей"
            if hit.quality.value == "ocr_low"
            else None
        ),
    )


def _stale_material_names(
    session: Session, index: RetrievalIndex, material_ids: list[UUID]
) -> list[str]:
    revisions = {UUID(item["material_id"]): item["revision"] for item in index.corpus_manifest}
    materials = list(session.scalars(select(Material).where(Material.id.in_(material_ids))))
    return [
        material_display_name(material)
        for material in materials
        if revisions.get(material.id) != material.active_parse_revision
    ]


def visual_page_locators(
    session: Session, material_ids: list[UUID]
) -> list[tuple[str, int]]:
    """Вернуть страницы с визуальными заглушками, которые retrieval не выдаёт за текст."""
    if not material_ids:
        return []
    rows = session.execute(
        select(Material, MaterialPage.page_number)
        .join(MaterialPage, MaterialPage.material_id == Material.id)
        .join(MaterialFragment, MaterialFragment.page_id == MaterialPage.id)
        .where(
            Material.id.in_(material_ids),
            MaterialPage.revision == Material.active_parse_revision,
            MaterialFragment.text.like("[Изображение]%"),
        )
        .distinct()
        .order_by(Material.created_at, MaterialPage.page_number)
        # Оглавление учебника (~120 КБ JSON) иначе читалось, сравнивалось в
        # DISTINCT и разбиралось в каждой строке с картинкой.
        .options(defer(Material.outline), defer(Material.diagnostics))
    ).all()
    return [(material_display_name(material), page_number) for material, page_number in rows]


async def _rerank(
    query: str,
    ranking: list[tuple[UUID, float, list[str]]],
    chunks: dict[UUID, RetrievalChunk],
    lexical: dict[UUID, SearchHit],
    *,
    depth: int,
    model_id: str,
) -> list[tuple[UUID, float, list[str]]]:
    head = ranking[:depth]
    documents = [
        chunks[item_id].text if item_id in chunks else lexical[item_id].text
        for item_id, _, _ in head
    ]
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{app_settings.retrieval_model_url}/rerank",
            json={"model": model_id, "query": query, "documents": documents},
        )
    response.raise_for_status()
    order = response.json()["results"]
    reranked = [
        (head[item["index"]][0], float(item["score"]), head[item["index"]][2]) for item in order
    ]
    return [*reranked, *ranking[depth:]]
