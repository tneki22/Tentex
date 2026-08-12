from conftest import add_page_with_fragments, make_material
from sqlalchemy.orm import Session

from app.bindings import search


def test_search_finds_a_different_wordform_than_the_query(session: Session) -> None:
    material = make_material(session, "aa")
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Транзакция объединяет изменения в атомарную единицу работы."],
        block_title="Транзакции",
    )
    search.reindex_material(session, material.id)

    hits = search.search_fragments(session, [material.id], "транзакций")

    assert len(hits) == 1
    assert "Транзакция" in hits[0].text


def test_results_are_limited_to_given_materials(session: Session) -> None:
    included = make_material(session, "bb")
    excluded = make_material(session, "cc")
    add_page_with_fragments(
        session, included, page_number=1, revision=1, fragments=["Индекс ускоряет поиск строк."]
    )
    add_page_with_fragments(
        session, excluded, page_number=1, revision=1, fragments=["Индекс ускоряет поиск строк."]
    )
    search.reindex_material(session, included.id)
    search.reindex_material(session, excluded.id)

    hits = search.search_fragments(session, [included.id], "индекс")

    assert len(hits) == 1
    assert hits[0].material_id == included.id


def test_deleted_material_disappears_from_results(session: Session) -> None:
    material = make_material(session, "dd")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Нормальная форма отношения."]
    )
    search.reindex_material(session, material.id)
    assert search.search_fragments(session, [material.id], "нормальная форма")

    search.delete_material_index(session, material.id)

    assert search.search_fragments(session, [material.id], "нормальная форма") == []


def test_reprocessing_does_not_duplicate_index_rows(session: Session) -> None:
    material = make_material(session, "ee")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Первичный ключ уникален."]
    )
    search.reindex_material(session, material.id)
    search.reindex_material(session, material.id)

    hits = search.search_fragments(session, [material.id], "ключ", limit=10)

    assert len(hits) == 1
    assert len(hits[0].fragment_ids) == 1


def test_result_order_is_stable_across_repeated_queries(session: Session) -> None:
    material = make_material(session, "ff")
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=[
            "Нормализация устраняет избыточность данных.",
            "Первая нормальная форма запрещает повторяющиеся группы.",
            "Третья нормальная форма устраняет транзитивные зависимости.",
        ],
    )
    search.reindex_material(session, material.id)

    query = "нормальная форма"
    first = [hit.fragment_ids for hit in search.search_fragments(session, [material.id], query)]
    second = [hit.fragment_ids for hit in search.search_fragments(session, [material.id], query)]

    assert first == second


def test_empty_query_returns_no_hits(session: Session) -> None:
    material = make_material(session, "aa11")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст без запроса."]
    )
    search.reindex_material(session, material.id)

    assert search.search_fragments(session, [material.id], "") == []
