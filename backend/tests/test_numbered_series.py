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
