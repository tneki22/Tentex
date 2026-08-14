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
