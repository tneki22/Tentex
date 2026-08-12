"""FTS5-индекс фрагментов материала: запись, очистка и лексический поиск.

Р4 плана: индекс пишется в той же транзакции, что и фрагменты страницы, поэтому
`reindex_material` вызывается из `materials.worker` и `materials.service` уже
после того, как фрагменты активной ревизии сохранены в этой же сессии.
Р5: `MATCH` идёт по колонке `lemmas`, подсветка совпадений — на сервере по
позициям токенов в исходном `text`, потому что `snippet()` не умеет подсвечивать
колонку, по которой не было совпадения.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.materials.lexicon import index_text, lemmatize, query_terms, tokenize_with_positions
from app.models import Material, MaterialBlock, MaterialFragment, MaterialPage, PageQuality

RESULT_LIMIT = 50
_RAW_HIT_MULTIPLIER = 4


def reindex_material(session: Session, material_id: UUID) -> int:
    """Пересобрать индекс материала по текущей активной ревизии. Возвращает число строк."""
    session.flush()
    delete_material_index(session, material_id)
    material = session.get(Material, material_id)
    if material is None or material.active_parse_revision == 0:
        return 0
    rows = session.execute(
        select(MaterialFragment.id, MaterialFragment.text)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(
            MaterialFragment.material_id == material_id,
            MaterialPage.revision == material.active_parse_revision,
        )
    ).all()
    for fragment_id, fragment_text in rows:
        _insert_fragment(session, fragment_id, material_id, fragment_text)
    return len(rows)


def delete_material_index(session: Session, material_id: UUID) -> None:
    material_hex = material_id.hex
    session.execute(
        text(
            "DELETE FROM fragment_search WHERE rowid IN "
            "(SELECT rowid FROM fragment_search_map WHERE material_id = :material_id)"
        ),
        {"material_id": material_hex},
    )
    session.execute(
        text("DELETE FROM fragment_search_map WHERE material_id = :material_id"),
        {"material_id": material_hex},
    )


def _insert_fragment(
    session: Session, fragment_id: UUID, material_id: UUID, fragment_text: str
) -> None:
    lemmas = index_text(fragment_text)
    session.execute(
        text(
            "INSERT INTO fragment_search(text, lemmas, fragment_id, material_id) "
            "VALUES (:text, :lemmas, :fragment_id, :material_id)"
        ),
        {
            "text": fragment_text,
            "lemmas": lemmas,
            "fragment_id": fragment_id.hex,
            "material_id": material_id.hex,
        },
    )
    rowid = session.execute(text("SELECT last_insert_rowid()")).scalar_one()
    session.execute(
        text(
            "INSERT INTO fragment_search_map(fragment_id, material_id, rowid) "
            "VALUES (:fragment_id, :material_id, :rowid)"
        ),
        {"fragment_id": fragment_id.hex, "material_id": material_id.hex, "rowid": rowid},
    )


@dataclass(frozen=True, slots=True)
class Highlight:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    fragment_ids: list[UUID]
    material_id: UUID
    material_name: str
    block_id: UUID
    block_title: str | None
    page_from: int
    page_to: int
    quality: PageQuality
    text: str
    highlights: list[Highlight]


def _highlights(fragment_text: str, terms: set[str]) -> list[Highlight]:
    return [
        Highlight(start, end)
        for token, start, end in tokenize_with_positions(fragment_text)
        if lemmatize([token])[0] in terms
    ]


def search_fragments(
    session: Session,
    material_ids: Sequence[UUID],
    query: str,
    *,
    limit: int = RESULT_LIMIT,
) -> list[SearchHit]:
    """Топ-N кандидатов по формулировке, сгруппированных по блоку материала (Р5)."""
    terms = query_terms(query)
    if not terms or not material_ids:
        return []
    match_expr = " ".join(f'"{term}"' for term in terms)
    material_hex = [material_id.hex for material_id in material_ids]
    placeholders = ", ".join(f":m{index}" for index in range(len(material_hex)))
    params: dict[str, object] = {f"m{index}": value for index, value in enumerate(material_hex)}
    params["q"] = match_expr
    params["raw_limit"] = limit * _RAW_HIT_MULTIPLIER
    rows = session.execute(
        text(
            "SELECT fragment_id, bm25(fragment_search, 0.0, 1.0) AS rank FROM fragment_search "
            f"WHERE lemmas MATCH :q AND material_id IN ({placeholders}) "
            "ORDER BY rank LIMIT :raw_limit"
        ),
        params,
    ).all()
    if not rows:
        return []

    rank_by_fragment_id: dict[UUID, float] = {}
    ranked_order: list[UUID] = []
    for fragment_hex, rank in rows:
        fragment_id = UUID(hex=fragment_hex)
        rank_by_fragment_id[fragment_id] = rank
        ranked_order.append(fragment_id)

    fragment_rows = session.execute(
        select(MaterialFragment, MaterialPage, MaterialBlock, Material)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .join(Material, Material.id == MaterialFragment.material_id)
        .where(MaterialFragment.id.in_(ranked_order))
    ).all()
    by_fragment_id = {row[0].id: row for row in fragment_rows}

    term_set = set(terms)
    groups: dict[UUID, dict] = {}
    group_order: list[UUID] = []
    for fragment_id in ranked_order:
        row = by_fragment_id.get(fragment_id)
        if row is None:
            continue
        fragment, page, block, material = row
        rank = rank_by_fragment_id[fragment_id]
        group = groups.get(block.id)
        if group is None:
            group = {
                "block": block,
                "material": material,
                "fragment_ids": [],
                "page_numbers": [],
                "best_rank": rank,
                "best_fragment": fragment,
            }
            groups[block.id] = group
            group_order.append(block.id)
        group["fragment_ids"].append(fragment_id)
        group["page_numbers"].append(page.page_number)
        if rank < group["best_rank"]:
            group["best_rank"] = rank
            group["best_fragment"] = fragment

    group_order.sort(key=lambda block_id: groups[block_id]["best_rank"])
    hits: list[SearchHit] = []
    for block_id in group_order[:limit]:
        group = groups[block_id]
        fragment = group["best_fragment"]
        block = group["block"]
        material = group["material"]
        hits.append(
            SearchHit(
                fragment_ids=group["fragment_ids"],
                material_id=material.id,
                material_name=material.original_name,
                block_id=block.id,
                block_title=block.title,
                page_from=min(group["page_numbers"]),
                page_to=max(group["page_numbers"]),
                quality=fragment.quality,
                text=fragment.text,
                highlights=_highlights(fragment.text, term_set),
            )
        )
    return hits
