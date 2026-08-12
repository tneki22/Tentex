from app.materials.lexicon import (
    _get_analyzer,
    index_text,
    lemmatize,
    normalize,
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
