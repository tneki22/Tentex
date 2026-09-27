"""Формулы, которых текстовый слой PDF не передаёт текстом.

Word пишет формулы шрифтом Cambria Math с таблицей Unicode, где каждый глиф —
пробел. Здесь то же воспроизводится подменой `ToUnicode` у встроенного шрифта:
глифы на странице видны, а слой отдаёт пробелы той же ширины.
"""

from pathlib import Path

import pymupdf as fitz
import pytest

from app.materials.parsers import native
from app.materials.parsers.base import IMAGE_PLACEHOLDER, ParsedElement, RecognizedRegion
from app.materials.parsers.formula_zones import find_zones, readable
from app.materials.parsers.text_layer import diagnose
from app.models import ParserMode
from app.ocr.engines import OcrRuntimeParams


def _blank_cmap() -> bytes:
    """CMap, в которой любой глиф с кодом до 1024 извлекается пробелом."""
    lines = [
        "/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Blank-UCS def", "/CMapType 2 def",
        "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange",
    ]
    for start in range(0, 1024, 100):
        codes = range(start, min(start + 100, 1024))
        lines.append(f"{len(codes)} beginbfchar")
        lines += [f"<{code:04X}> <0020>" for code in codes]
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode()


def _hide_font(document: fitz.Document, marker: str, name: str) -> None:
    """Шрифт, чьё имя содержит `marker`, — без текста и под новым именем."""
    for xref in range(1, document.xref_length()):
        if document.xref_get_key(xref, "Subtype")[1] != "/Type0":
            continue
        if marker not in document.xref_get_key(xref, "BaseFont")[1]:
            continue
        unicode_ref = int(document.xref_get_key(xref, "ToUnicode")[1].split()[0])
        document.update_stream(unicode_ref, _blank_cmap())
        document.xref_set_key(xref, "BaseFont", f"/{name}")
        descendant = int(
            document.xref_get_key(xref, "DescendantFonts")[1].strip("[]").split()[0]
        )
        document.xref_set_key(descendant, "BaseFont", f"/{name}")


def _pdf(
    tmp_path: Path, draw, *, hidden_name: str = "ABCDEE+CambriaMath", name: str = "hidden"
) -> fitz.Document:
    document = fitz.open()
    page = document.new_page(width=500, height=700)
    page.insert_font(fontname="T", fontbuffer=fitz.Font("tiro").buffer)
    page.insert_font(fontname="M", fontbuffer=fitz.Font("tibo").buffer)
    draw(page)
    _hide_font(document, "Bold", hidden_name)
    path = tmp_path / f"{name}.pdf"
    document.save(path)
    document.close()
    return fitz.open(path)


def _text(page: fitz.Page, point: tuple[float, float], text: str, font: str = "T") -> None:
    page.insert_text(point, text, fontname=font, fontsize=14)


def _methodical(page: fitz.Page) -> None:
    """Страница методички: строчная формула во фразе и выносная отдельно."""
    _text(page, (60, 100), "Пусть")
    _text(page, (105, 100), "A, B, C", "M")
    _text(page, (165, 100), "– произвольные формулы алгебры высказываний.")
    _text(page, (60, 140), "1) рефлексивность")
    _text(page, (200, 180), "F = F and G = G", "M")
    _text(page, (60, 220), "Отношение равносильности является эквивалентностью.")


def test_hidden_glyphs_become_inline_and_display_zones(tmp_path) -> None:
    document = _pdf(tmp_path, _methodical)
    page = document[0]
    assert "A, B, C" not in page.get_text()  # слой отдаёт пробелы

    zones = find_zones(page)

    assert len(zones) == 2
    inline, display = sorted(zones, key=lambda zone: zone.box[1])
    assert not inline.standalone and inline.hidden
    assert display.standalone and display.hidden
    # Рамка — по чернилам глифов, а не по пробелам вокруг них.
    assert inline.box[0] > 100 / 500 and inline.box[2] < 165 / 500
    assert display.box[1] < 180 / 700 < display.box[3]


def test_typed_spaces_and_underlined_blanks_are_not_formulas(tmp_path) -> None:
    def form(page: fitz.Page) -> None:
        _text(page, (60, 100), "Группа:" + " " * 30 + "Подпись")
        _text(page, (60, 140), "Фамилия:" + " " * 25 + ".")
        # Подчёркнутые пробелы бланка: чернила есть, но это линия, а не глиф.
        page.draw_line((130, 143), (300, 143), width=1)

    document = _pdf(tmp_path, form)

    assert find_zones(document[0]) == []


def test_visible_math_line_is_a_zone_but_greek_in_prose_is_not(tmp_path) -> None:
    def page_with_symbols(page: fitz.Page) -> None:
        page.insert_text((60, 100), "где ", fontname="T", fontsize=14)
        page.insert_text((90, 100), "h", fontname="symb", fontsize=14)
        page.insert_text((100, 100), " – коэффициент обучения сети", fontname="T", fontsize=14)
        page.insert_text((200, 160), "a + b = g", fontname="symb", fontsize=14)

    document = _pdf(tmp_path, page_with_symbols)

    zones = find_zones(document[0])

    assert len(zones) == 1
    assert zones[0].standalone and not zones[0].hidden
    assert zones[0].box[1] < 160 / 700 < zones[0].box[3]


def test_symbol_private_use_glyphs_read_as_unicode() -> None:
    assert readable("x1x2x3", "Symbol") == "x1∧x2≡x3"
    assert readable(" пункт", "SymbolMT") == "• пункт"
    # Wingdings кладёт в ту же область свои значки — их не трогаем.
    assert readable("", "Wingdings") == ""
    assert readable("") == "→"


def test_math_only_page_is_not_blank_and_body_font_without_text_is_broken(tmp_path) -> None:
    formulas = _pdf(tmp_path, lambda page: _text(page, (200, 180), "F = F", "M"))
    assert diagnose(formulas[0]).route == "text"

    def body(page: fitz.Page) -> None:
        for row in range(6):
            _text(page, (60, 100 + 30 * row), "Основной текст главы без Unicode.", "M")
        _text(page, (60, 300), "Колонтитул")

    broken = _pdf(tmp_path, body, hidden_name="ABCDEE+TimesNewRoman", name="body")
    diagnosis = diagnose(broken[0])
    assert diagnosis.route == "broken"
    assert "text_layer_hidden_glyphs" in diagnosis.reasons


class _Recognizer:
    """Модель вырезов: строчная — «A, B, C», выносная — «F \\equiv F»."""

    concurrency = 1

    def __init__(self) -> None:
        self.requests = []

    def recognize_regions(self, requests, page_number):
        self.requests.extend(requests)
        first = min(request.index for request in requests)
        return [
            RecognizedRegion(
                request.index,
                "formula",
                "A, B, C" if request.index == first else r"F \equiv F,\; G \equiv G",
                0.95,
            )
            for request in requests
        ]

    def describe_images(self, requests):
        return []


def test_layer_page_reads_zones_and_splices_inline_formula(tmp_path) -> None:
    document = _pdf(tmp_path, _methodical)
    page = document[0]
    parsed = native._text_layer_page(document, page, 0, "", ParserMode.CLOUD, OcrRuntimeParams())

    formulas = [element for element in parsed.elements if element.kind == "formula"]
    assert len(formulas) == 2
    assert all(element.text == IMAGE_PLACEHOLDER for element in formulas)
    assert "formula_zones:2" in parsed.diagnostics

    recognizer = _Recognizer()
    result = native._recognized_regions(page, parsed, recognizer, OcrRuntimeParams())

    assert len(recognizer.requests) == 2
    texts = [element.text for element in result.elements]
    assert any(text.startswith("Пусть $A, B, C$ – произвольные") for text in texts)
    assert r"$$F \equiv F,\; G \equiv G$$" in texts
    assert IMAGE_PLACEHOLDER not in texts


def test_display_formula_lines_leave_the_paragraph_text(tmp_path) -> None:
    """Линейная строка формулы («a+b=g» знаками Symbol) не остаётся в абзаце."""

    def mathtype(page: fitz.Page) -> None:
        _text(page, (60, 100), "Значение ошибки выходного слоя:")
        page.insert_text((200, 125), "a + b = g", fontname="symb", fontsize=14)
        _text(page, (60, 150), "Новые весовые коэффициенты слоя.")

    document = _pdf(tmp_path, mathtype)
    parsed = native._text_layer_page(
        document, document[0], 0, "", ParserMode.CLOUD, OcrRuntimeParams()
    )

    texts = [element.text for element in parsed.elements]
    assert IMAGE_PLACEHOLDER in texts
    assert not any("α" in text or "β" in text for text in texts)
    assert any("Значение ошибки" in text for text in texts)
    assert any("Новые весовые" in text for text in texts)


@pytest.mark.parametrize("header_outside", [True])
def test_table_crop_covers_formula_header_above_its_frame(header_outside) -> None:
    from app.materials.parsers.inline_formulas import formulas_in_tables

    elements = [
        ParsedElement("table", "|0|0|\n|---|---|\n|1|1|", (0.1, 0.30, 0.9, 0.50)),
        ParsedElement("formula", IMAGE_PLACEHOLDER, (0.12, 0.25, 0.20, 0.45)),
    ]

    tables = formulas_in_tables(elements, [1])

    box, inner = tables[0]
    assert inner == [1]
    assert box[1] == pytest.approx(0.25)
