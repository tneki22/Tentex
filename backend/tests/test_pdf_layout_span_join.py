from app.materials.parsers.pdf_layout import _join_box_lines, _line_text


def test_line_text_inserts_space_at_word_gap_without_explicit_space() -> None:
    # LaTeX-вёрстка часто отдаёт каждое слово отдельным спаном без символа
    # пробела — пробел выражен только зазором между координатами.
    raw_line = {
        "spans": [
            {"text": "18.", "bbox": [19.8, 0, 33.8, 10], "size": 11},
            {"text": "Дать", "bbox": [38.0, 0, 59.5, 10], "size": 11},
            {"text": "определение", "bbox": [63.2, 0, 122.5, 10], "size": 11},
        ]
    }

    assert _line_text(raw_line) == "18. Дать определение"


def test_line_text_keeps_kerned_letters_of_the_same_word_together() -> None:
    raw_line = {
        "spans": [
            {"text": "сло", "bbox": [10.0, 0, 25.0, 10], "size": 11},
            {"text": "во", "bbox": [25.2, 0, 33.0, 10], "size": 11},
        ]
    }

    assert _line_text(raw_line) == "слово"


def test_join_box_lines_strips_hyphen_at_line_wrap() -> None:
    assert _join_box_lines(["математиче-", "ские ожидания"]) == "математические ожидания"


def test_join_box_lines_keeps_space_when_not_hyphenated() -> None:
    assert _join_box_lines(["18. Дать определение.", "Доказать теорему."]) == (
        "18. Дать определение. Доказать теорему."
    )


def test_join_box_lines_ignores_dash_that_is_not_a_word_break() -> None:
    assert _join_box_lines(["Промежуток —", "монотонная функция."]) == (
        "Промежуток — монотонная функция."
    )
