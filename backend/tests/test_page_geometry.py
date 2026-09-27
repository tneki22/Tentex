"""Страница целиком в модели: рамки — по геометрии PDF, а не по памяти модели.

Модель указывает место элемента с ошибкой до двух строк и режет схему на
части. На странице с текстовым слоем рамки приводятся к словам, рисункам и
зонам формул, а пропущенное добавляется из слоя.
"""

from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw

from app.materials.parsers import native, page_geometry
from app.materials.parsers.base import IMAGE_PLACEHOLDER, ParsedElement, ParsedPage
from app.materials.parsers.cloud_vlm import CloudElement, CloudPage, CloudRecognizer
from app.ocr.engines import OcrRuntimeParams

WIDTH, HEIGHT = 500.0, 700.0
FIGURE = fitz.Rect(150, 200, 350, 350)


def _figure_png() -> bytes:
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 180, 120), outline="black", width=4)
    draw.ellipse((220, 150, 380, 280), outline="black", width=4)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _document(tmp_path: Path) -> fitz.Document:
    document = fitz.open()
    page = document.new_page(width=WIDTH, height=HEIGHT)
    page.insert_font(fontname="T", fontbuffer=fitz.Font("tiro").buffer)
    lines = {
        100: "Данная схема проводит электрический ток тогда",
        120: "и только тогда, когда оба контакта замкнуты.",
        180: "Вторая схема состоит из двух контактов.",
        400: "Эта схема проводит ток в том случае, когда",
        420: "по меньшей мере один из контактов замкнут.",
        480: "Строка, которую модель не вернула вовсе.",
    }
    for y, text in lines.items():
        page.insert_text((60, y), text, fontname="T", fontsize=12)
    page.insert_image(FIGURE, stream=_figure_png())
    path = tmp_path / "geometry.pdf"
    document.save(path)
    document.close()
    return fitz.open(path)


def _box(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    return (x0 / WIDTH, y0 / HEIGHT, x1 / WIDTH, y1 / HEIGHT)


def _answer() -> ParsedPage:
    """Ответ модели: всё на две строки ниже, схема разрезана на две части."""
    shift = 28
    elements = (
        ParsedElement(
            "paragraph",
            "Данная схема проводит электрический ток тогда и только тогда, когда оба "
            "контакта замкнуты.",
            _box(60, 88 + shift, 450, 124 + shift),
            recognition_source="vl",
        ),
        ParsedElement(
            "paragraph",
            "Вторая схема состоит из двух контактов.",
            _box(60, 168 + shift, 400, 184 + shift),
            recognition_source="vl",
        ),
        ParsedElement("image", IMAGE_PLACEHOLDER, _box(150, 200 + shift, 350, 270 + shift)),
        ParsedElement("image", "x ∧ y", _box(150, 272 + shift, 350, 350 + shift)),
        ParsedElement(
            "paragraph",
            "Эта схема проводит ток в том случае, когда по меньшей мере один из "
            "контактов замкнут.",
            _box(60, 388 + shift, 450, 424 + shift),
            recognition_source="vl",
        ),
    )
    return ParsedPage(1, WIDTH, HEIGHT, "", "", "ocr", elements)


def test_model_boxes_snap_to_words_figures_and_missed_lines_come_from_layer(tmp_path) -> None:
    document = _document(tmp_path)
    page = document[0]
    geometry = page_geometry.page_geometry(page, [])

    snapped = page_geometry.snap_to_layer(_answer(), geometry)

    images = [element for element in snapped.elements if element.kind == "image"]
    assert len(images) == 1, "две части схемы — один элемент"
    assert images[0].bbox == _box(*FIGURE)
    assert images[0].text == "x ∧ y"
    assert images[0].image is not None and not images[0].image.reasons

    first = snapped.elements[0]
    assert abs(first.bbox[1] - 88 / HEIGHT) < 0.01, "абзац вернулся на свои строки"
    assert abs(first.bbox[3] - 124 / HEIGHT) < 0.01

    added = [
        element
        for element in snapped.elements
        if element.kind == "paragraph" and element.recognition_source == "native"
    ]
    assert [element.text for element in added] == ["Строка, которую модель не вернула вовсе."]
    assert snapped.elements[-1] is added[0]


def test_whole_page_route_uses_layer_geometry_instead_of_ink_guesses(tmp_path) -> None:
    document = _document(tmp_path)
    page = document[0]

    class Recognizer:
        concurrency = 1

        def recognize_page(self, image, page_number, width, height):
            return _answer()

        def describe_images(self, requests):
            return []

    parsed = native._scanned_page(
        page, 0, "", OcrRuntimeParams(), Recognizer(), (b"", 300.0), layer=True
    )

    assert not any("missed_regions" in item for item in parsed.diagnostics)
    assert any(item.startswith("layer_snapped:") for item in parsed.diagnostics)
    assert "Строка, которую модель не вернула вовсе." in parsed.plain_text


def test_scan_merges_split_figure_and_drops_echo_of_shifted_lines() -> None:
    parsed = ParsedPage(
        1,
        WIDTH,
        HEIGHT,
        "",
        "",
        "ocr",
        (
            ParsedElement("paragraph", "Абзац текста", (0.1, 0.10, 0.9, 0.14)),
            ParsedElement("image", IMAGE_PLACEHOLDER, (0.3, 0.30, 0.7, 0.40)),
            ParsedElement("image", IMAGE_PLACEHOLDER, (0.3, 0.41, 0.7, 0.50)),
        ),
    )

    merged = page_geometry.merge_split_images(parsed)

    images = [element for element in merged.elements if element.kind == "image"]
    assert len(images) == 1 and images[0].bbox == (0.3, 0.30, 0.7, 0.50)

    regions = [
        (0.1, 0.145, 0.8, 0.165),  # строка абзаца, указанного выше, — эхо
        (0.2, 0.60, 0.4, 0.70),  # половина схемы, которую модель не вернула
        (0.405, 0.60, 0.6, 0.70),  # вторая половина той же схемы
    ]
    assert page_geometry.unread_candidates(regions, merged.elements) == [(0.2, 0.60, 0.6, 0.70)]


def test_page_answer_keeps_figure_without_labels() -> None:
    answer = CloudPage(
        elements=[
            CloudElement(kind="paragraph", text="Текст", bbox=[0.1, 0.1, 0.9, 0.2],
                         level=None, confidence=0.9),
            CloudElement(kind="image", text="", bbox=[0.3, 0.3, 0.7, 0.6],
                         level=None, confidence=0.9),
        ],
        page_confidence=0.9,
    )

    parsed = CloudRecognizer(session=None)._page(answer, 1, WIDTH, HEIGHT)

    assert [element.kind for element in parsed.elements] == ["paragraph", "image"]
    assert parsed.elements[1].text == IMAGE_PLACEHOLDER
    assert parsed.plain_text == "Текст"


def test_cyrillic_after_backslash_becomes_text() -> None:
    from app.materials.parsers.cloud_vlm import repair_latex

    assert repair_latex(r"\ЭД(x_1) \equiv 1") == r"\text{ЭД}(x_1) \equiv 1"
