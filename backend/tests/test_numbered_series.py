from app.models import ExamFormat
from app.projects.importer import parse_exam_program
from app.projects.numbered_series import select_numbered_series


def test_selects_main_series_and_ignores_preamble_and_trailing_reset() -> None:
    result = select_numbered_series(
        ["Preparation title", "1. First", "2. Second", "3. Third", "1. Appendix"],
        expected_count=3,
    )

    assert [item.number for item in result.items] == [1, 2, 3]
    assert result.ignored_before == ("Preparation title",)
    assert result.ignored_after == ("1. Appendix",)


def test_rejects_two_equally_valid_series() -> None:
    result = select_numbered_series(["1. A", "2. B", "1. C", "2. D"], expected_count=2)

    assert result.ambiguous is True


def test_keeps_ocr_number_without_space_and_continuation() -> None:
    result = select_numbered_series(["40)First", "continued", "41)Second"])

    assert [(item.number, item.text) for item in result.items] == [
        (40, "First continued"),
        (41, "Second"),
    ]


def test_nested_decimal_heading_is_not_a_top_level_marker() -> None:
    result = select_numbered_series(["1. First", "1.1 Nested", "2. Second"])

    assert [item.number for item in result.items] == [1, 2]


def test_questions_tasks_keeps_separate_numbered_sections() -> None:
    parsed = parse_exam_program(
        "Вопросы\n1. Первый вопрос\nЗадачи\n1. Первая задача",
        ExamFormat.QUESTIONS_TASKS,
    )

    assert (parsed.questions, parsed.tasks) == (1, 1)


def test_stitches_series_across_a_missed_number_when_expected_count_given() -> None:
    result = select_numbered_series(
        ["1. First", "2. Second", "4. Fourth", "5. Fifth"], expected_count=4
    )

    assert [item.number for item in result.items] == [1, 2, 4, 5]
    assert any("сшит" in warning for warning in result.warnings)


def test_does_not_stitch_across_a_gap_without_expected_count() -> None:
    # Без ориентира по числу пунктов сшивка выключена: у сопоставления эталонных
    # ответов по заголовкам сшитый через пропуск номер сдвинул бы привязку.
    result = select_numbered_series(["1. First", "4. Fourth", "5. Fifth", "6. Sixth"])

    assert [item.number for item in result.items] == [4, 5, 6]


def test_split_inline_items_recovers_a_box_merged_pair() -> None:
    parsed = parse_exam_program(
        "1. Первый вопрос. 2. Второй вопрос.\n3. Третий вопрос.",
        ExamFormat.QUESTIONS,
        expected_item_count=3,
    )

    assert [node.title for node in parsed.nodes] == [
        "Первый вопрос.",
        "Второй вопрос.",
        "Третий вопрос.",
    ]
