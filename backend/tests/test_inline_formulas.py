"""Формулы-картинки в строке, номера формул и таблицы с формулами.

Проверяется сборка страницы после ответа модели: куда встаёт формула, что
происходит с её отдельным элементом и сколько вырезов уходит наружу.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw

from app.materials.parsers import native
from app.materials.parsers.base import (
    IMAGE_PLACEHOLDER,
    DescribedImage,
    ImageRequest,
    PageImage,
    ParsedElement,
    ParsedPage,
    RecognizedRegion,
    RegionRequest,
)
from app.materials.parsers.inline_formulas import (
    Word,
    merge_equation_tags,
    splice_inline,
)
from app.models import ParserMode
from app.ocr.engines import OcrRuntimeParams


def _formula_png(width: int = 60, height: int = 24) -> bytes:
    image = Image.new("RGB", (width, height), color="white")
    ImageDraw.Draw(image).line((4, height // 2, width - 4, height // 2), fill="black", width=3)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class LatexRecognizer:
    """Модель, которая читает каждый вырез формулой `x_{index}`, а таблицу — таблицей."""

    concurrency = 1

    def __init__(self) -> None:
        self.regions: list[RegionRequest] = []

    def prefetch_pages(self, pages: Sequence[PageImage]) -> None:
        del pages

    def recognize_page(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        raise AssertionError("страница с текстовым слоем целиком в модель не уходит")

    def recognize_regions(
        self, regions: Sequence[RegionRequest], page_number: int
    ) -> list[RecognizedRegion]:
        del page_number
        self.regions.extend(regions)
        return [
            RecognizedRegion(region.index, "table", "| a | b |\n|---|---|\n| $x$ | $y$ |", 0.9)
            if region.kind == "table"
            else RecognizedRegion(region.index, "formula", f"x_{{{region.index}}}", 0.9)
            for region in regions
        ]

    def describe_images(self, images: Sequence[ImageRequest]) -> list[DescribedImage]:
        return []


def _word(x0: float, x1: float, text: str, top: float = 0.10) -> Word:
    return Word((x0, top, x1, top + 0.02), text)


def test_a_formula_between_two_words_goes_back_into_its_sentence() -> None:
    paragraph = ParsedElement(
        "paragraph", "Рассмотрим серию из   независимых испытаний.", (0.1, 0.09, 0.9, 0.13)
    )
    formula = ParsedElement("formula", "$$n$$", (0.40, 0.095, 0.43, 0.125))
    words = [
        _word(0.10, 0.25, "Рассмотрим"),
        _word(0.26, 0.33, "серию"),
        _word(0.34, 0.37, "из"),
        _word(0.45, 0.65, "независимых"),
        _word(0.66, 0.85, "испытаний."),
    ]

    elements, spliced = splice_inline([paragraph, formula], words, [1])

    assert spliced == {1}
    assert elements[0].text == "Рассмотрим серию из $n$ независимых испытаний."


def test_a_repeated_anchor_word_picks_the_right_occurrence() -> None:
    paragraph = ParsedElement(
        "paragraph", "с вероятностью   и не появляется с вероятностью  .", (0.1, 0.09, 0.9, 0.13)
    )
    first = ParsedElement("formula", "p", (0.30, 0.095, 0.32, 0.125))
    second = ParsedElement("formula", "q = 1 - p", (0.80, 0.095, 0.88, 0.125))
    words = [
        _word(0.10, 0.12, "с"),
        _word(0.13, 0.29, "вероятностью"),
        _word(0.33, 0.34, "и"),
        _word(0.35, 0.37, "не"),
        _word(0.38, 0.55, "появляется"),
        _word(0.56, 0.58, "с"),
        _word(0.59, 0.79, "вероятностью"),
        _word(0.89, 0.90, "."),
    ]

    elements, spliced = splice_inline([paragraph, first, second], words, [1, 2])

    assert spliced == {1, 2}
    assert elements[0].text == "с вероятностью $p$ и не появляется с вероятностью $q = 1 - p$."


def test_a_formula_on_its_own_line_stays_a_block() -> None:
    paragraph = ParsedElement("paragraph", "Текст до формулы.", (0.1, 0.05, 0.9, 0.08))
    formula = ParsedElement("formula", "$$M(X) = np$$", (0.3, 0.10, 0.7, 0.13))

    elements, spliced = splice_inline([paragraph, formula], [_word(0.1, 0.4, "Текст", 0.05)], [1])

    assert spliced == set()
    assert elements[0].text == "Текст до формулы."


def test_an_equation_number_cut_off_by_the_layout_becomes_its_tag() -> None:
    formula = ParsedElement("formula", r"$$\sum_k p_k = 1$$", (0.3, 0.40, 0.7, 0.44))
    number = ParsedElement("formula", r"$$\tag{3.2}$$", (0.85, 0.405, 0.9, 0.435))
    text_number = ParsedElement("paragraph", "(3.3)", (0.85, 0.505, 0.9, 0.535))
    second = ParsedElement("formula", "$$M(X) = np$$", (0.3, 0.50, 0.7, 0.54))

    elements, merged = merge_equation_tags([formula, number, second, text_number])

    assert merged == {1, 3}
    assert elements[0].text == r"$$\sum_k p_k = 1 \tag{3.2}$$"
    assert elements[2].text == r"$$M(X) = np \tag{3.3}$$"


def _pdf_with_inline_formulas(path: Path, table: bool = False) -> Path:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((60, 100), "Рассмотрим серию из", fontsize=11)
    page.insert_image(fitz.Rect(172, 88, 190, 104), stream=_formula_png(36, 32))
    page.insert_text((196, 100), "независимых испытаний Бернулли.", fontsize=11)
    page.insert_text((60, 130), "Вероятность события равна", fontsize=11)
    page.insert_image(fitz.Rect(210, 118, 260, 134), stream=_formula_png(100, 32))
    page.insert_text((266, 130), "по формуле Бернулли.", fontsize=11)
    document.save(path)
    document.close()
    return path


def test_cloud_parse_puts_inline_raster_formulas_into_the_paragraph(tmp_path: Path) -> None:
    recognizer = LatexRecognizer()
    path = _pdf_with_inline_formulas(tmp_path / "inline.pdf")

    page = next(
        native.iter_pages(path, ParserMode.CLOUD, params=OcrRuntimeParams(), recognizer=recognizer)
    )

    assert len(recognizer.regions) == 2
    assert not [item for item in page.elements if item.kind == "formula"]
    assert "$x_{" in page.plain_text
    assert IMAGE_PLACEHOLDER not in page.markdown
    assert any(item.startswith("inline_formulas:") for item in page.diagnostics)
