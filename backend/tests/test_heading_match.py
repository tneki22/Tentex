"""Подбор вопроса по заголовку раздела ответов.

Место, где поведение ломается тише всего: порог сдвинулся — и либо половина файла
перестала привязываться, либо ответы легли не на те вопросы. Примеры взяты с
реального файла пользователя (`Подготовка к экзамену НБД.pdf`).
"""

from uuid import uuid4

from app.models import ReferenceAnswerMatchMethod
from app.projects.heading_match import HeadingIndex

QUESTIONS = [
    "Ключи, как средство создания связей",
    "Об индексах",
    "Ключи и индексы",
    "Транзакции и блокировки",
    "Нормализация отношения",
    "Использование индексов",
    "Использование индексов и основные сведения о индексах.",
    "Трезвенная архитектура и  ее преимущества.",
    "Не реляционные модели данных. Примеры реализации.",
    "Удаление записей и согласованность  Нереляционные базы данных.",
]


def build_index() -> tuple[HeadingIndex, dict[str, str]]:
    ids = {title: uuid4() for title in QUESTIONS}
    index = HeadingIndex((node_id, title) for title, node_id in ids.items())
    return index, {title: node_id for title, node_id in ids.items()}


def test_punctuation_difference_stays_an_exact_match() -> None:
    index, ids = build_index()
    match = index.match("Ключи как средство создания связей")
    assert match.node_ids == (ids["Ключи, как средство создания связей"],)
    assert match.method == ReferenceAnswerMatchMethod.EXACT_TITLE


def test_numbered_heading_finds_its_question() -> None:
    index, ids = build_index()
    match = index.match("Вопрос 21 Использование индексов")
    assert match.node_ids == (ids["Использование индексов"],)
    assert match.method == ReferenceAnswerMatchMethod.EXACT_TITLE


def test_one_letter_difference_is_matched_as_fuzzy() -> None:
    index, ids = build_index()
    match = index.match("О индексах")
    assert match.node_ids == (ids["Об индексах"],)
    assert match.method == ReferenceAnswerMatchMethod.FUZZY_TITLE


def test_word_form_difference_is_matched_as_fuzzy() -> None:
    index, ids = build_index()
    match = index.match("Нормализация отношений")
    assert match.node_ids == (ids["Нормализация отношения"],)
    assert match.method == ReferenceAnswerMatchMethod.FUZZY_TITLE


def test_shorter_heading_is_not_bound_to_a_longer_question() -> None:
    index, _ = build_index()
    match = index.match("Транзакции")
    assert not match.matched


def test_unmatched_heading_offers_candidates() -> None:
    index, ids = build_index()
    match = index.match("Ключи и индексы в реляционных базах данных")
    assert not match.matched
    assert ids["Ключи и индексы"] in {candidate.node_id for candidate in match.candidates}


def test_number_prefix_does_not_dilute_the_comparison() -> None:
    """Номер вопроса не участвует в сравнении: иначе он тянет совпадение вниз."""
    index, ids = build_index()
    match = index.match("Вопрос 21 Использование индексов и основные сведения об индексах")
    assert match.node_ids == (ids["Использование индексов и основные сведения о индексах."],)
    assert match.method == ReferenceAnswerMatchMethod.FUZZY_TITLE


def test_typo_in_one_word_still_matches() -> None:
    index, ids = build_index()
    match = index.match("Вопрос 35 Трёхзвенная архитектура и её преимущества")
    assert match.node_ids == (ids["Трезвенная архитектура и  ее преимущества."],)


def test_word_split_in_two_still_matches() -> None:
    index, ids = build_index()
    match = index.match("Вопрос 3 Нереляционные модели данных. Примеры реализации")
    assert match.node_ids == (ids["Не реляционные модели данных. Примеры реализации."],)


def test_title_page_line_is_not_bound_to_a_question_about_the_same_words() -> None:
    """Титульная строка делит слова с настоящим вопросом — и не должна к нему лечь."""
    index, _ = build_index()
    match = index.match("Дисциплина: Нереляционные базы данных")
    assert not match.matched
    assert match.candidates  # но подсказать кандидатов не мешает


def test_heading_without_common_words_offers_nothing() -> None:
    index, _ = build_index()
    match = index.match("Министерство образования и науки")
    assert not match.matched
    assert match.candidates == ()


def test_repeated_question_binds_to_every_copy() -> None:
    first, second = uuid4(), uuid4()
    index = HeadingIndex([(first, "Ключи и индексы"), (second, "Ключи и индексы.")])
    match = index.match("Ключи и индексы")
    assert set(match.node_ids) == {first, second}
    assert match.method == ReferenceAnswerMatchMethod.EXACT_TITLE
