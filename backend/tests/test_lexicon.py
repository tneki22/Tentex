from app.materials.lexicon import (
    _get_analyzer,
    index_text,
    lemmatize,
    norm_text,
    normalize,
    prefix_term,
    query_terms,
)


def test_wordforms_of_one_word_share_a_lemma() -> None:
    forms = ["транзакция", "транзакции", "транзакций", "транзакцию"]
    lemmas = {lemmatize(normalize(form))[0] for form in forms}
    assert lemmas == {"транзакция"}


def test_latin_and_numbers_are_not_lemmatized() -> None:
    assert lemmatize(normalize("SQL ACID INSERT 2026")) == ["sql", "acid", "insert", "2026"]


def test_yo_and_ye_forms_collapse_to_the_same_lemma() -> None:
    assert lemmatize(["ёж"]) == lemmatize(["еж"])


def test_empty_query_returns_empty_terms() -> None:
    assert query_terms("") == []
    assert query_terms("   ") == []


def test_stop_word_only_query_returns_empty_terms() -> None:
    assert query_terms("это и то") == []


def test_meaningful_query_survives_stop_words() -> None:
    terms = query_terms("что такое нормальные формы")
    assert "нормальный" in terms
    assert "форма" in terms


def test_index_text_joins_lemmas_with_spaces() -> None:
    assert index_text("Нормальные формы") == "нормальный форма"


def test_analyzer_is_a_process_wide_singleton() -> None:
    assert _get_analyzer() is _get_analyzer()


def test_question_stem_words_are_dropped() -> None:
    """«Дать определение X» — «дать» ищется по всему учебнику и только шумит."""
    terms = query_terms("Дать определение первичного ключа")
    assert "дать" not in terms
    assert {"определение", "первичный", "ключ"} <= set(terms)


def test_normalize_folds_yo_into_ye() -> None:
    assert normalize("Чётность задаётся") == ["четность", "задается"]


def test_norm_text_keeps_wordforms_without_morphology() -> None:
    assert norm_text("Модель Мили") == "модель мили"
    assert index_text("Модель Мили") == "модель миля"


def test_prefix_term_takes_the_last_token() -> None:
    assert prefix_term("автомат мил") == "мил"
    assert prefix_term("Чёт") == "чет"


def test_prefix_term_ignores_too_short_and_empty_queries() -> None:
    assert prefix_term("") is None
    assert prefix_term("   ") is None
    assert prefix_term("а") is None
