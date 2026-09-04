"""Порядок чтения страницы: XY-Cut, поправка на наклон и разрешение растра.

Проверяется наблюдаемое поведение — какой порядок получается на характерных
раскладках, — а не устройство рекурсии: реализацию можно переписать, тесты
переписывать не придётся.
"""

from __future__ import annotations

import pymupdf as fitz
import pytest

from app.materials.parsers import raster, reading_order

# Строка на A4 в нормализованных координатах: примерно 1,4% высоты страницы.
LINE_HEIGHT = 0.014


def line(column: str, row: int) -> tuple[float, float, float, float]:
    """Строка текста в левой или правой колонке, `row`-я сверху."""
    left = 0.08 if column == "left" else 0.53
    top = 0.30 + row * (LINE_HEIGHT * 1.4)
    return (left, top, left + 0.39, top + LINE_HEIGHT)


def test_two_column_page_is_read_column_by_column() -> None:
    """Главный случай: научная статья. Построчное чередование колонок — брак."""
    boxes = [
        (0.08, 0.05, 0.92, 0.09),  # заголовок во всю ширину
        *(line("left", row) for row in range(4)),
        *(line("right", row) for row in range(4)),
    ]
    # На вход подаётся вперемешку, как их отдаёт детектор строк.
    shuffled = [
        boxes[0],
        boxes[1],
        boxes[5],
        boxes[2],
        boxes[6],
        boxes[3],
        boxes[7],
        boxes[4],
        boxes[8],
    ]

    order = reading_order.reading_order(shuffled)
    result = [shuffled[index] for index in order]

    assert result[0] == boxes[0]
    assert result[1:5] == boxes[1:5]
    assert result[5:] == boxes[5:]


def test_single_column_page_keeps_top_down_order() -> None:
    boxes = [(0.1, 0.1 + row * 0.05, 0.9, 0.13 + row * 0.05) for row in range(5)]

    assert reading_order.reading_order(list(reversed(boxes))) == [4, 3, 2, 1, 0]


@pytest.mark.parametrize("boxes", [[], [(0.1, 0.1, 0.9, 0.2)]])
def test_degenerate_input_is_returned_as_is(boxes: list[tuple[float, ...]]) -> None:
    assert reading_order.reading_order(boxes) == list(range(len(boxes)))  # type: ignore[arg-type]


def test_skew_angle_is_the_median_tilt_of_detected_lines() -> None:
    """Наклон в один градус даёт примерно 17 пикселей подъёма на тысяче."""
    quads = [[(0.0, 100.0), (1000.0, 100.0 + 17.45)] for _ in range(5)]

    assert reading_order.skew_angle(quads) == pytest.approx(1.0, abs=0.05)


def test_tiny_tilt_is_not_treated_as_skew() -> None:
    """Ниже порога поправка ошибается чаще, чем помогает."""
    quads = [[(0.0, 100.0), (1000.0, 100.5)] for _ in range(5)]

    assert reading_order.skew_angle(quads) == 0.0


def test_skew_correction_restores_the_column_order() -> None:
    """Наклонённая страница: без поправки правая колонка «уезжает» вверх."""
    angle = 1.2
    width, height = 1000.0, 1400.0
    straight = [
        (80.0, 400.0, 460.0, 420.0),  # последняя строка левой колонки
        (540.0, 380.0, 920.0, 400.0),  # первая строка правой колонки
    ]
    corrected = reading_order.correct_skew(straight, angle, width, height)

    # Поправка сдвигает рамки, но не переворачивает их и не выносит за страницу.
    assert len(corrected) == 2
    for (x0, y0, x1, y1) in corrected:
        assert x0 < x1 and y0 < y1


def test_correct_skew_without_tilt_changes_nothing() -> None:
    boxes = [(0.0, 0.0, 10.0, 10.0)]

    assert reading_order.correct_skew(boxes, 0.0, 100.0, 100.0) == boxes


def _blank_pdf_page(dpi: float | None) -> fitz.Page:
    """Страница A4: пустая векторная либо со сканом заданного разрешения."""
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    if dpi is not None:
        pixels = int(595 * dpi / 72)
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, pixels, int(pixels * 842 / 595)))
        pixmap.clear_with(255)
        page.insert_image(page.rect, pixmap=pixmap)
    return page


def test_render_scale_reaches_three_hundred_dpi_by_default() -> None:
    """Прежняя постоянная ×2 давала 144 dpi — вдвое меньше, чем нужно PP-OCRv5."""
    _, dpi = raster.render_scale(_blank_pdf_page(None), 2.0)

    assert dpi == pytest.approx(300.0)


def test_render_scale_does_not_invent_pixels_beyond_the_scan() -> None:
    """У скана в 150 dpi рисовать 300 нечего: информации в файле столько нет."""
    _, dpi = raster.render_scale(_blank_pdf_page(150.0), 2.0)

    assert dpi == pytest.approx(225.0, abs=1.0)


def test_render_scale_is_capped_from_below() -> None:
    """Даже на самом экономном значении текст должен оставаться читаемым."""
    _, dpi = raster.render_scale(_blank_pdf_page(60.0), 1.5)

    assert dpi == raster.MIN_RENDER_DPI


def test_unread_regions_finds_content_outside_recognised_lines() -> None:
    """Выносная формула, которую распознаватель строк не увидел, не должна пропасть."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (600, 800), color=255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 100, 540, 130), fill=0)  # строка, которую OCR прочитал
    draw.rectangle((200, 300, 400, 340), fill=0)  # формула, которую он пропустил

    regions = raster.unread_regions(image, [(0.1, 0.125, 0.9, 0.1625)])

    assert len(regions) == 1
    x0, y0, x1, y1 = regions[0]
    assert 0.25 <= x0 <= 0.35
    assert 0.35 <= y0 <= 0.39
    assert 0.65 <= x1 <= 0.72


def test_unread_regions_is_empty_when_everything_is_recognised() -> None:
    from PIL import Image, ImageDraw

    image = Image.new("L", (600, 800), color=255)
    ImageDraw.Draw(image).rectangle((60, 100, 540, 130), fill=0)

    assert raster.unread_regions(image, [(0.09, 0.12, 0.91, 0.17)]) == []
