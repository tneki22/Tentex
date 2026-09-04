"""Маршрут режима «Облако»: что уходит наружу, а что берётся из файла даром.

Внешняя модель подменена заглушкой — проверяется не она, а решение парсера:
на какие куски страницы он тратит вызов и куда кладёт ответ.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw

from app.materials.parsers.base import (
    ParsedPage,
    RecognizedRegion,
    RegionRequest,
)
from app.materials.parsers.native import iter_pages
from app.models import ParserMode
from app.ocr.engines import OcrRuntimeParams


class StubRecognizer:
    """Заглушка внешней модели: запоминает, о чём её спросили."""

    def __init__(self) -> None:
        self.pages: list[int] = []
        self.regions: list[RegionRequest] = []

    def recognize_page(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        self.pages.append(page_number)
        return ParsedPage(
            page_number,
            width,
            height,
            "# Страница целиком",
            "Страница целиком",
            "ocr",
            (),
            (),
            0.9,
        )

    def recognize_regions(
        self, regions: Sequence[RegionRequest], page_number: int
    ) -> list[RecognizedRegion]:
        del page_number
        self.regions.extend(regions)
        return [
            RecognizedRegion(
                index=region.index,
                kind="formula",
                text=r"$$\int_a^b f(x)\,dx = F(b) - F(a)$$",
                confidence=0.94,
            )
            for region in regions
        ]


def _formula_png() -> bytes:
    """Формула, вставленная в PDF картинкой, — так устроены сканы и старые вёрстки."""
    image = Image.new("RGB", (420, 90), color="white")
    ImageDraw.Draw(image).rectangle((20, 30, 400, 60), fill="black")
    path = Path(__file__).parent / "_formula.png"
    image.save(path)
    data = path.read_bytes()
    path.unlink()
    return data


@pytest.fixture
def mixed_pdf(tmp_path: Path) -> Path:
    """Страница с текстовым слоем и формулой-картинкой — типичный учебник."""
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 100), "Formula Newton-Leibniz theorem", fontsize=12)
    page.insert_image(fitz.Rect(120, 200, 470, 280), stream=_formula_png())
    path = tmp_path / "mixed.pdf"
    document.save(path)
    return path


@pytest.fixture
def scan_pdf(tmp_path: Path) -> Path:
    """Страница без текстового слоя — только картинка."""
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=_formula_png())
    path = tmp_path / "scan.pdf"
    document.save(path)
    return path


def _parse(path: Path, recognizer: StubRecognizer, strategy: str = "auto") -> list[ParsedPage]:
    return list(
        iter_pages(
            path,
            ParserMode.CLOUD,
            params=OcrRuntimeParams(cloud_strategy=strategy),  # type: ignore[arg-type]
            recognizer=recognizer,
        )
    )


def test_page_with_a_text_layer_sends_out_only_the_picture(
    mixed_pdf: Path,
) -> None:
    """Главная экономия режима: текст уже есть и точен, платить за него незачем."""
    recognizer = StubRecognizer()

    pages = _parse(mixed_pdf, recognizer)

    assert recognizer.pages == []
    assert len(recognizer.regions) == 1
    assert recognizer.regions[0].image.startswith(b"\x89PNG")
    recognised = [item for item in pages[0].elements if item.recognition_source == "vl"]
    assert len(recognised) == 1
    assert recognised[0].kind == "formula"
    assert r"\int_a^b" in recognised[0].text


def test_the_native_text_is_not_replaced_by_the_model(mixed_pdf: Path) -> None:
    page = _parse(mixed_pdf, StubRecognizer())[0]

    native = [item for item in page.elements if item.recognition_source == "native"]
    assert any("Newton" in item.text for item in native)


def test_a_page_without_a_text_layer_goes_to_the_model_whole(scan_pdf: Path) -> None:
    recognizer = StubRecognizer()

    pages = _parse(scan_pdf, recognizer)

    assert recognizer.pages == [1]
    assert recognizer.regions == []
    assert pages[0].plain_text == "Страница целиком"


def test_the_whole_page_strategy_ignores_the_text_layer(mixed_pdf: Path) -> None:
    """Явный выбор пользователя: пусть вёрстку разбирает модель, а не разметчик PDF."""
    recognizer = StubRecognizer()

    _parse(mixed_pdf, recognizer, strategy="page")

    assert recognizer.pages == [1]
    assert recognizer.regions == []


def test_local_modes_never_reach_the_model(mixed_pdf: Path) -> None:
    """Порт есть только у облачного разбора: «Быстро» обязан остаться офлайн."""
    recognizer = StubRecognizer()

    list(iter_pages(mixed_pdf, ParserMode.FAST, params=OcrRuntimeParams()))

    assert recognizer.pages == []
    assert recognizer.regions == []
