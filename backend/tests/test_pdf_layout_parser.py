from pathlib import Path

import pymupdf as fitz
from PIL import Image

from app.materials.parsers import paddle_fast, textbook
from app.materials.parsers.base import ParsedElement
from app.materials.parsers.native import _merge_native_and_images, _page_quality, iter_pages
from app.models import ParserMode


def _layout_fixture(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=500, height=600)
    page.insert_text((50, 45), "Synthetic layout", fontsize=18)
    page.insert_text((50, 80), "- Parent", fontsize=11)
    page.insert_text((75, 100), "- Child", fontsize=11)

    columns = [50, 180, 310]
    rows = [140, 170, 200]
    for x in columns:
        page.draw_line((x, rows[0]), (x, rows[-1]))
    for y in rows:
        page.draw_line((columns[0], y), (columns[-1], y))
    labels = (("Column A", "Column B"), ("Value A", "Value B"))
    for row_index, row in enumerate(labels):
        for column_index, value in enumerate(row):
            page.insert_text(
                (columns[column_index] + 5, rows[row_index] + 20), value, fontsize=10
            )

    page.insert_text((50, 245), "Left column first.", fontsize=11)
    page.insert_text((280, 245), "Right column second.", fontsize=11)
    document.save(path)
    document.close()
    return path


def test_native_pdf_preserves_table_nested_list_and_columns(tmp_path: Path) -> None:
    path = _layout_fixture(tmp_path / "layout.pdf")

    page = next(iter_pages(path, ParserMode.FAST))

    assert "|Column A|Column B|" in page.markdown
    assert "- Parent" in page.markdown
    assert "    - Child" in page.markdown
    assert [element.kind for element in page.elements].count("table") == 1
    assert "layout_markdown" in page.diagnostics
    assert page.plain_text.index("Left column first") < page.plain_text.index(
        "Right column second"
    )


def test_layout_failure_falls_back_per_page(tmp_path: Path, monkeypatch) -> None:
    path = _layout_fixture(tmp_path / "fallback.pdf")
    monkeypatch.setattr(
        "app.materials.parsers.native.parse_layout_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )

    page = next(iter_pages(path, ParserMode.FAST))

    assert page.plain_text
    assert "layout_fallback" in page.diagnostics


def test_iter_pages_skips_unselected_pdf_pages(tmp_path: Path) -> None:
    path = tmp_path / "selected-pages.pdf"
    document = fitz.open()
    for page_number in range(1, 4):
        page = document.new_page(width=500, height=600)
        page.insert_text((50, 50), f"Page {page_number}", fontsize=12)
    document.save(path)
    document.close()

    pages = list(
        iter_pages(path, ParserMode.FAST, page_numbers=(1, 3))
    )

    assert [page.page_number for page in pages] == [1, 3]


def test_mixed_page_keeps_native_text_and_image_without_duplicate_transcript() -> None:
    native = ParsedElement("paragraph", "Плотность распределения", (0.1, 0.1, 0.8, 0.2))
    image = ParsedElement(
        "image",
        "Плотность распределения",
        (0.05, 0.05, 0.9, 0.3),
        confidence=0.72,
        asset_path="assets/page.png",
        recognition_source="ocr",
    )

    merged = _merge_native_and_images((native,), (image,))

    assert [item.kind for item in merged].count("paragraph") == 1
    assert [item.kind for item in merged].count("image") == 1
    assert next(item for item in merged if item.kind == "paragraph").text == (
        "Плотность распределения"
    )
    image_result = next(item for item in merged if item.kind == "image")
    assert image_result.text == "[Изображение]"
    assert image_result.asset_path == "assets/page.png"


def test_fast_ocr_groups_wrapped_numbered_question_without_making_heading(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (1000, 1000), "white").save(image_path)

    class Engine:
        def predict(self, _path: str):
            return [
                {
                    "rec_texts": ["10. Дать определение плотности", "распределения вероятности"],
                    "rec_scores": [0.95, 0.93],
                    "rec_boxes": [[50, 50, 850, 90], [50, 95, 700, 135]],
                }
            ]

    monkeypatch.setattr(paddle_fast, "_get_engine", lambda *args, **kwargs: Engine())

    page = paddle_fast.parse_image(image_path, 1)

    assert len(page.elements) == 1
    assert page.elements[0].kind == "list"
    assert page.elements[0].text == (
        "10. Дать определение плотности распределения вероятности"
    )


def test_textbook_formula_preserves_latex_and_original_crop(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (1000, 500), "white").save(image_path)
    monkeypatch.setattr(
        textbook,
        "_json_request",
        lambda *_args, **_kwargs: {
            "width": 1000,
            "height": 500,
            "markdown": "$$P(A)=1$$",
            "elements": [
                {
                    "label": "formula",
                    "content": r"P(A)=1",
                    "bbox": [100, 100, 900, 300],
                    "confidence": 0.91,
                }
            ],
        },
    )
    monkeypatch.setattr(
        textbook,
        "store_material_asset",
        lambda owner, name, _data: f"assets/{owner}/{name}",
    )

    page = textbook.parse_image(image_path, 1, "document")

    assert page.elements[0].kind == "formula"
    assert page.elements[0].text == r"P(A)=1"
    assert page.elements[0].recognition_source == "vl"
    assert page.elements[0].asset_path == "assets/document/vl-p1-0.png"


def test_page_quality_threshold_is_configurable() -> None:
    elements = (
        ParsedElement(
            "paragraph", "распознанный текст", (0, 0, 1, 0.1), confidence=0.8,
            recognition_source="ocr",
        ),
    )

    assert _page_quality(elements, quality_threshold=0.75) == ("ocr", 0.8)
    assert _page_quality(elements, quality_threshold=0.9) == ("ocr_low", 0.8)
