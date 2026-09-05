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

    hits = search.search_fragments(session, [material.id], "транзакций").hits

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

    hits = search.search_fragments(session, [included.id], "индекс").hits

    assert len(hits) == 1
    assert hits[0].material_id == included.id


def test_deleted_material_disappears_from_results(session: Session) -> None:
    material = make_material(session, "dd")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Нормальная форма отношения."]
    )
    search.reindex_material(session, material.id)
    assert search.search_fragments(session, [material.id], "нормальная форма").hits

    search.delete_material_index(session, material.id)

    assert search.search_fragments(session, [material.id], "нормальная форма").hits == []


def test_reprocessing_does_not_duplicate_index_rows(session: Session) -> None:
    material = make_material(session, "ee")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Первичный ключ уникален."]
    )
    search.reindex_material(session, material.id)
    search.reindex_material(session, material.id)

    hits = search.search_fragments(session, [material.id], "ключ", limit=10).hits

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

    def ids() -> list[list]:
        found = search.search_fragments(session, [material.id], query)
        return [hit.fragment_ids for hit in found.hits]

    first, second = ids(), ids()

    assert first == second


def test_empty_query_returns_no_hits(session: Session) -> None:
    material = make_material(session, "aa11")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст без запроса."]
    )
    search.reindex_material(session, material.id)

    assert search.search_fragments(session, [material.id], "").hits == []


def test_partial_word_finds_the_full_word(session: Session) -> None:
    """Главный регресс: «мил» обязано находить «Мили».

    Лемматизировать огрызок нельзя — pymorphy3 достраивает «мил» до «мила»,
    поэтому недопечатанное слово ищется префиксом по колонке `norm`.
    """
    material = make_material(session, "a1")
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Модель Мили задаётся шестёркой множеств."],
    )
    search.reindex_material(session, material.id)

    hits = search.search_fragments(session, [material.id], "мил").hits

    assert len(hits) == 1
    assert "Мили" in hits[0].text


def test_partial_word_finds_a_longer_term(session: Session) -> None:
    material = make_material(session, "a2")
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Отношение эквивалентности разбивает множество на классы."],
    )
    search.reindex_material(session, material.id)

    assert search.search_fragments(session, [material.id], "эквив").hits


def test_yo_and_ye_are_the_same_letter_for_the_prefix(session: Session) -> None:
    """`unicode61 remove_diacritics 2` не сводит ё к е — это делает колонка `norm`."""
    material = make_material(session, "a3")
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Чётность перестановки не зависит от способа разложения."],
    )
    search.reindex_material(session, material.id)

    assert search.search_fragments(session, [material.id], "чёт").hits
    assert search.search_fragments(session, [material.id], "чет").hits


def test_question_wording_finds_material_without_containing_every_word(
    session: Session,
) -> None:
    """Раньше неявный AND требовал все леммы разом и давал ноль на любом вопросе."""
    material = make_material(session, "a4")
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Реляционная модель данных опирается на отношение и его схему."],
    )
    search.reindex_material(session, material.id)

    query = "Дать определение реляционной модели данных и перечислить её основные свойства"
    hits = search.search_fragments(session, [material.id], query).hits

    assert len(hits) == 1


def test_phrase_beats_the_same_words_scattered(session: Session) -> None:
    """Биграмма даёт словосочетанию собственный IDF — фрагмент с ним идёт первым."""
    scattered = make_material(session, "a5")
    phrased = make_material(session, "a8")
    add_page_with_fragments(
        session,
        scattered,
        page_number=1,
        revision=1,
        fragments=["Данные о модели хранит отдельная реляционная таблица."],
        block_title="Вразнобой",
    )
    add_page_with_fragments(
        session,
        phrased,
        page_number=1,
        revision=1,
        fragments=["Реляционная модель данных описывает отношения."],
        block_title="Словосочетание",
    )
    search.reindex_material(session, scattered.id)
    search.reindex_material(session, phrased.id)

    query = "реляционная модель данных"
    hits = search.search_fragments(session, [scattered.id, phrased.id], query).hits

    assert [hit.block_title for hit in hits] == ["Словосочетание", "Вразнобой"]


def test_outcome_reports_the_words_it_searched_by(session: Session) -> None:
    material = make_material(session, "a6")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Первичный ключ уникален."]
    )
    search.reindex_material(session, material.id)

    outcome = search.search_fragments(session, [material.id], "Дать определение первичного ключа")

    assert "дать" not in outcome.terms
    assert {"определение", "первичный", "ключ"} <= set(outcome.terms)
    assert outcome.prefix == "ключа"


def test_matched_forms_carry_the_wordform_not_the_lemma(session: Session) -> None:
    """Клиенту нужна форма из текста: подсветить «Мили» по лемме «миля» нечем."""
    material = make_material(session, "a7")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Автомат Мили и автомат Мура."]
    )
    search.reindex_material(session, material.id)

    hits = search.search_fragments(session, [material.id], "мил").hits

    assert hits[0].matched_forms == ["Мили"]


def test_hit_splits_into_pages_with_their_own_preview(session: Session) -> None:
    """Блок через две страницы даёт две записи: у каждой свои фрагменты и свой текст.

    Интерфейс группирует выдачу по страницам, и превью страницы 2 не должно
    приезжать со страницы 1 — иначе карточка врёт о том, что на ней найдено.
    """
    material = make_material(session, "a8")
    first = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Второе неравенство Чебышёва оценивает отклонение."],
        block_title="Неравенства",
    )
    second = add_page_with_fragments(
        session,
        material,
        page_number=2,
        revision=1,
        fragments=["Доказательство второго неравенства Чебышёва."],
        block_id=first.block_id,
    )
    search.reindex_material(session, material.id)

    hits = search.search_fragments(session, [material.id], "неравенство Чебышёва").hits

    assert len(hits) == 1
    hit = hits[0]
    assert (hit.page_from, hit.page_to) == (1, 2)
    assert [page.page_number for page in hit.pages] == [1, 2]
    assert hit.pages[0].fragment_ids == first.fragment_ids
    assert hit.pages[1].fragment_ids == second.fragment_ids
    assert hit.pages[0].text.startswith("Второе неравенство")
    assert hit.pages[1].text.startswith("Доказательство")
    assert all(page.highlights for page in hit.pages)


def test_hit_carries_presentation_kind_of_its_material(session: Session) -> None:
    """Предпросмотр выбирает растр или текст до запроса, а не по ошибке 422."""
    material = make_material(session, "a9")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Схема нормализации отношений."]
    )
    search.reindex_material(session, material.id)

    hits = search.search_fragments(session, [material.id], "нормализация").hits

    assert hits[0].presentation_kind == "plain_text"
