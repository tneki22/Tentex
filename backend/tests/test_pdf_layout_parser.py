from pathlib import Path

import pymupdf as fitz

from app.materials.parsers.native import iter_pages
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
