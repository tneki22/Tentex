from app.exam.checking import deterministic_check, key_terms, locate_quote
from app.models import AttemptOutcome, GradeMethod


def test_exact_match_ignores_case_punctuation_spacing_and_yo() -> None:
    result = deterministic_check(
        "Елка — это дерево!",
        "ёлка это дерево",
        "Что такое ёлка?",
    )

    assert result.outcome is AttemptOutcome.PASSED
    assert result.method is GradeMethod.EXACT_MATCH
    assert result.decided is True


def test_key_term_coverage_one_is_decided() -> None:
    result = deterministic_check(
        "Транзакция обладает атомарностью, согласованностью, изоляцией и долговечностью.",
        "Атомарность, согласованность, изоляция и долговечность — свойства транзакции.",
        "Назовите свойства транзакции.",
    )

    assert result.outcome is AttemptOutcome.PASSED
    assert result.method is GradeMethod.KEY_TERMS
    assert result.decided is True
    assert result.missed == []


def test_key_term_coverage_zero_is_preliminary_failure() -> None:
    result = deterministic_check(
        "Затрудняюсь ответить.",
        "Индекс ускоряет поиск строк в таблице базы данных.",
        "Для чего нужен индекс?",
    )

    assert result.outcome is AttemptOutcome.FAILED
    assert result.method is GradeMethod.KEY_TERMS
    assert result.decided is False
    assert result.credited == []
    assert result.wrong == []


def test_coverage_point_eight_stops_before_expensive_check() -> None:
    result = deterministic_check(
        "Альфа бета гамма дельта.",
        "Альфа бета гамма дельта эпсилон.",
        "Перечислите элементы.",
    )

    assert result.outcome is AttemptOutcome.PASSED
    assert result.decided is True


def test_coverage_point_five_requires_expensive_check() -> None:
    result = deterministic_check(
        "Альфа бета.",
        "Альфа бета гамма дельта.",
        "Перечислите элементы.",
    )

    assert result.outcome is AttemptOutcome.PARTIAL
    assert result.decided is False


def test_question_words_are_not_counted_as_reference_terms() -> None:
    assert key_terms(
        "Индекс ускоряет поиск строк.",
        "Как индекс ускоряет поиск?",
    ) == ["строка"]


def test_inflected_word_counts_as_key_term_and_keeps_source_offsets() -> None:
    result = deterministic_check(
        "Создание индексов ускоряет выборку.",
        "Индекс ускоряет чтение таблицы.",
        "Что ускоряет чтение?",
    )

    index_point = next(point for point in result.credited if point.point == "индекс")
    assert index_point.quote == "индексов"
    assert result.outcome is AttemptOutcome.PARTIAL


def test_missing_reference_is_unscored() -> None:
    result = deterministic_check("Ответ", None, "Вопрос")

    assert result.outcome is AttemptOutcome.UNSCORED
    assert result.method is None
    assert result.decided is False


def test_locate_quote_ignores_case_and_punctuation_between_tokens() -> None:
    answer = "Первая НОРМАЛЬНАЯ форма — важна."

    assert locate_quote(answer, "нормальная форма") == (7, 23)


def test_locate_quote_rejects_invented_quote() -> None:
    assert locate_quote("Короткий ответ", "несуществующая цитата") is None
