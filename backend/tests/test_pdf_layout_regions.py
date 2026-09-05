"""Область страницы не исчезает молча.

Разметчик `pymupdf4llm` отдаёт схему, выносную формулу и таблицу боксами без
единой текстовой строки: математику и векторную графику он в строки не
собирает. Прежде такой бокс выбрасывался, и на реальных лекциях по теории
вероятностей так пропадали и формулы, и все рисунки — привязать их было нечем,
а в просмотрщике на их месте не было даже рамки.
"""

import json
from pathlib import Path

import pymupdf as fitz
import pymupdf4llm
import pytest

from app.materials.parsers.pdf_layout import parse_layout_page


def _page(tmp_path: Path) -> fitz.Document:
    document = fitz.open()
    page = document.new_page(width=500, height=600)
    page.insert_text((50, 50), "Пример 1.8", fontsize=11)
    path = tmp_path / "regions.pdf"
    document.save(path)
    document.close()
    return fitz.open(path)


def _box(box_class: str, y0: float, y1: float, text: str | None = None) -> dict:
    box: dict[str, object] = {
        "boxclass": box_class,
        "x0": 50.0,
        "y0": y0,
        "x1": 450.0,
        "y1": y1,
    }
    if text is not None:
        box["textlines"] = [{"spans": [{"text": text, "bbox": [50.0, y0, 450.0, y1]}]}]
    else:
        box["textlines"] = []
    return box


@pytest.fixture
def layout(monkeypatch):
    """Подменяет разметчик: классы боксов задаёт тест, а не модель разметки."""

    def install(boxes: list[dict]) -> None:
        monkeypatch.setattr(
            pymupdf4llm,
            "to_json",
            lambda *_args, **_kwargs: json.dumps({"pages": [{"boxes": boxes}]}),
        )

    return install


def test_picture_becomes_a_bindable_fragment_with_a_crop(tmp_path, layout) -> None:
    layout([_box("text", 40, 60, "Пример 1.8"), _box("picture", 100, 300)])
    document = _page(tmp_path)

    parsed = parse_layout_page(document, 0, owner="probe")

    kinds = [element.kind for element in parsed.elements]
    assert kinds == ["paragraph", "image"]
    picture = parsed.elements[1]
    assert picture.text == "[Изображение]"
    assert picture.asset_path, "у схемы должен остаться вырез оригинала"
    assert "pictures:1" in parsed.diagnostics


def test_display_formula_keeps_its_place_and_original_crop(tmp_path, layout) -> None:
    layout([_box("text", 40, 60, "Поскольку"), _box("formula", 100, 160)])
    document = _page(tmp_path)

    parsed = parse_layout_page(document, 0, owner="probe")

    formula = parsed.elements[1]
    assert formula.kind == "formula"
    assert formula.asset_path
    assert "formulas:1" in parsed.diagnostics


def test_textless_box_of_a_text_class_is_kept_and_counted(tmp_path, layout) -> None:
    """Класс обещал текст, строк нет — это потеря содержания, а не пустое место."""
    layout([_box("text", 40, 60, "Абзац"), _box("text", 100, 300)])
    document = _page(tmp_path)

    parsed = parse_layout_page(document, 0, owner="probe")

    assert [element.kind for element in parsed.elements] == ["paragraph", "image"]
    assert "textless_boxes:1" in parsed.diagnostics


def test_empty_running_title_and_hairline_are_dropped_without_a_trace(
    tmp_path, layout
) -> None:
    """Пустой колонтитул — это пустота, а узкая полоска — линейка, а не рисунок."""
    layout(
        [
            _box("text", 40, 60, "Абзац"),
            _box("page-footer", 560, 580),
            _box("text", 200, 210),
        ]
    )
    document = _page(tmp_path)

    parsed = parse_layout_page(document, 0, owner="probe")

    assert [element.kind for element in parsed.elements] == ["paragraph"]
    assert not any(item.startswith("textless_boxes") for item in parsed.diagnostics)
