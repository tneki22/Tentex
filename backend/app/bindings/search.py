"""FTS5-индекс фрагментов материала: запись, очистка и лексический поиск.

Р4 плана: индекс пишется в той же транзакции, что и фрагменты страницы, поэтому
`reindex_material` вызывается из `materials.worker` и `materials.service` уже
после того, как фрагменты активной ревизии сохранены в этой же сессии.

Р5: у индекса две поисковые колонки. `lemmas` — нормальные формы слов, по ней
идёт основной поиск и совпадают разные словоформы. `norm` — те же слова без
морфологии (нижний регистр, ё→е), по ней идёт префиксный поиск недопечатанного
слова: лемматизировать огрызок нельзя, pymorphy3 достраивает «мил» до «мила»,
и ни одна лемма с него не начинается.

Запрос любой длины собирается в одно выражение `MATCH` (см. `_match_expression`),
ранжирует BM25. Ветки соединяются через `OR` сознательно: BM25 — ранжирующая
модель, а не фильтрующая, и неявный `AND` заставлял её отбрасывать всё, что не
содержит формулировку вопроса целиком.

Подсветка — на сервере по позициям токенов в исходном `text`, потому что
`snippet()` не умеет подсвечивать колонку, по которой не было совпадения.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.materials.lexicon import (
    index_text,
    lemmatize,
    norm_text,
    prefix_term,
    query_terms,
    tokenize_with_positions,
)
from app.models import Material, MaterialBlock, MaterialFragment, MaterialPage, PageQuality

RESULT_LIMIT = 50
_RAW_HIT_MULTIPLIER = 4

#: Длинная формулировка не улучшает выдачу, но раздувает выражение MATCH.
_MAX_QUERY_TERMS = 12

#: Единственное описание схемы индекса: миграция, тесты и сквозные проверки
#: создают таблицу отсюда, иначе копии расходятся — так уже случилось с
#: `check_ai_gateway`, где таблица создавалась без `tokenize`.
FRAGMENT_SEARCH_DDL = (
    "CREATE VIRTUAL TABLE fragment_search USING fts5("
    "norm, lemmas, fragment_id UNINDEXED, material_id UNINDEXED, "
    'tokenize = "unicode61 remove_diacritics 2", prefix = "2 3")'
)

#: FTS5 не умеет индексированный WHERE по UNINDEXED-колонке, поэтому rowid
#: строк индекса держит обычная таблица — по ней идёт удаление по материалу.
FRAGMENT_SEARCH_MAP_DDL = (
    "CREATE TABLE fragment_search_map ("
    "fragment_id TEXT PRIMARY KEY, material_id TEXT NOT NULL, rowid INTEGER NOT NULL)"
)


def create_fragment_search(connection: Connection) -> None:
    """Создать индекс и таблицу-спутник в обход Alembic: тесты и сквозные проверки."""
    connection.exec_driver_sql(FRAGMENT_SEARCH_DDL)
    connection.exec_driver_sql(FRAGMENT_SEARCH_MAP_DDL)


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
    session.execute(
        text(
            "INSERT INTO fragment_search(norm, lemmas, fragment_id, material_id) "
            "VALUES (:norm, :lemmas, :fragment_id, :material_id)"
        ),
        {
            "norm": norm_text(fragment_text),
            "lemmas": index_text(fragment_text),
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
    matched_forms: list[str]


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Результат поиска вместе с тем, по чему искали.

    Слова запроса нужны интерфейсу: без них пустая выдача по длинной
    формулировке выглядит поломкой, а не отсутствием материала.
    """

    terms: list[str]
    prefix: str | None
    hits: list[SearchHit]


def _match_expression(terms: Sequence[str], prefix: str | None) -> str:
    """Собрать выражение MATCH: словосочетания, отдельные слова, недопечатанное слово.

    Биграммы соседних лемм идут отдельными фразами: у словосочетания
    «реляционная модель данных» собственный высокий IDF, поэтому фрагмент с ним
    поднимается над фрагментом с теми же словами вразнобой без ручных весов.
    Триграммы не нужны — трёхсловный термин совпадает с обеими биграммами сразу.
    """
    bigrams = zip(terms, terms[1:], strict=False)
    branches = [f'lemmas:"{first} {second}"' for first, second in bigrams]
    branches += [f'lemmas:"{term}"' for term in terms]
    if prefix:
        branches.append(f"norm:{prefix}*")
    return " OR ".join(branches)


def _highlights(
    fragment_text: str, terms: set[str], prefix: str | None
) -> tuple[list[Highlight], list[str]]:
    """Позиции совпадений и сами словоформы из текста.

    Словоформы отдаются наружу, потому что подсветить «Мили» по лемме «миля»
    на клиенте нечем — там нет морфологии, только поиск подстроки.
    """
    spans: list[Highlight] = []
    forms: dict[str, str] = {}
    for token, start, end in tokenize_with_positions(fragment_text):
        if lemmatize([token])[0] not in terms and not (prefix and token.startswith(prefix)):
            continue
        spans.append(Highlight(start, end))
        forms.setdefault(token, fragment_text[start:end])
    return spans, list(forms.values())


def matched_forms(fragment_text: str, terms: set[str], prefix: str | None) -> list[str]:
    """Словоформы из текста, совпавшие с запросом, — для подсветки на клиенте."""
    return _highlights(fragment_text, terms, prefix)[1]


def matches_query(fragment_text: str, terms: set[str], prefix: str | None) -> bool:
    """Совпадает ли текст с запросом без обращения к индексу.

    Нужно историческим ревизиям: они в индексе не лежат, но правило совпадения
    должно быть тем же, что и у `search_fragments`.
    """
    if terms & set(index_text(fragment_text).split()):
        return True
    return bool(prefix) and any(
        token.startswith(prefix) for token in norm_text(fragment_text).split()
    )


def search_fragments(
    session: Session,
    material_ids: Sequence[UUID],
    query: str,
    *,
    limit: int = RESULT_LIMIT,
) -> SearchOutcome:
    """Топ-N кандидатов по формулировке, сгруппированных по блоку материала (Р5)."""
    terms = query_terms(query)[:_MAX_QUERY_TERMS]
    prefix = prefix_term(query)
    empty = SearchOutcome(terms=terms, prefix=prefix, hits=[])
    if not (terms or prefix) or not material_ids:
        return empty
    material_hex = [material_id.hex for material_id in material_ids]
    placeholders = ", ".join(f":m{index}" for index in range(len(material_hex)))
    params: dict[str, object] = {f"m{index}": value for index, value in enumerate(material_hex)}
    params["q"] = _match_expression(terms, prefix)
    params["raw_limit"] = limit * _RAW_HIT_MULTIPLIER
    rows = session.execute(
        text(
            "SELECT fragment_id, bm25(fragment_search, 1.0, 2.0) AS rank FROM fragment_search "
            f"WHERE fragment_search MATCH :q AND material_id IN ({placeholders}) "
            "ORDER BY rank LIMIT :raw_limit"
        ),
        params,
    ).all()
    if not rows:
        return empty

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
        spans, forms = _highlights(fragment.text, term_set, prefix)
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
                highlights=spans,
                matched_forms=forms,
            )
        )
    return SearchOutcome(terms=terms, prefix=prefix, hits=hits)
