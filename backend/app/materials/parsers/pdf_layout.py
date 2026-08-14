import json
import re
from collections.abc import Iterable

import pymupdf as fitz

from app.materials.parsers.base import ElementKind, ParsedElement, ParsedPage

INDENT_STEP = 18
MAX_LIST_LEVEL = 4
BULLET_RE = re.compile(r"^\s*[•▪◦‣·*+\-–—]\s+")


def _normalized_bbox(
    box: dict[str, object], width: float, height: float
) -> tuple[float, float, float, float]:
    x0 = float(box.get("x0", 0))
    y0 = float(box.get("y0", 0))
    x1 = float(box.get("x1", width))
    y1 = float(box.get("y1", height))
    return (
        max(0, x0 / width),
        max(0, y0 / height),
        min(1, x1 / width),
        min(1, y1 / height),
    )


def _text_lines(box: dict[str, object]) -> list[str]:
    result: list[str] = []
    raw_lines = box.get("textlines")
    if not isinstance(raw_lines, list):
        return result
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue
        spans = raw_line.get("spans")
        if not isinstance(spans, list):
            continue
        text = "".join(
            str(span.get("text", "")) for span in spans if isinstance(span, dict)
        ).strip()
        if text:
            result.append(text)
    return result


def _table_markdown(box: dict[str, object]) -> str:
    table = box.get("table")
    if not isinstance(table, dict):
        return ""
    return str(table.get("markdown") or "").strip()


def _table_plain(box: dict[str, object], markdown: str) -> str:
    table = box.get("table")
    extracted = table.get("extract") if isinstance(table, dict) else None
    if not isinstance(extracted, list):
        return markdown
    lines = []
    for row in extracted:
        if isinstance(row, list):
            lines.append(" | ".join(str(cell or "").strip() for cell in row))
    return "\n".join(lines).strip() or markdown


def _box_kind(box_class: str, text: str) -> ElementKind:
    if BULLET_RE.match(text):
        return "list"
    if box_class == "section-header":
        return "heading"
    if box_class == "list-item":
        return "list"
    if box_class == "table":
        return "table"
    if "formula" in box_class:
        return "formula"
    return "paragraph"


def _list_levels(boxes: Iterable[dict[str, object]]) -> dict[int, int]:
    list_boxes = [
        box
        for box in boxes
        if box.get("boxclass") == "list-item" or BULLET_RE.match(" ".join(_text_lines(box)))
    ]
    if not list_boxes:
        return {}
    base_x = min(float(box.get("x0", 0)) for box in list_boxes)
    return {
        id(box): 1
        + min(
            MAX_LIST_LEVEL - 1,
            max(0, int((float(box.get("x0", 0)) - base_x) / INDENT_STEP)),
        )
        for box in list_boxes
    }


def _markdown(elements: Iterable[ParsedElement]) -> str:
    lines: list[str] = []
    for element in elements:
        if element.kind == "heading":
            lines.append(f"{'#' * (element.level or 1)} {element.text}")
        elif element.kind == "list":
            lines.append(f"{'    ' * ((element.level or 1) - 1)}{element.text}")
        else:
            lines.append(element.text)
    return "\n\n".join(lines)


def parse_layout_page(document: fitz.Document, page_index: int) -> ParsedPage:
    """Преобразует один текстовый PDF-лист в Markdown и элементы с координатами."""
    import pymupdf4llm

    payload = pymupdf4llm.to_json(
        document,
        pages=[page_index],
        use_ocr=False,
        write_images=False,
        force_text=True,
    )
    data = json.loads(payload) if isinstance(payload, str) else payload
    raw_pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(raw_pages, list) or len(raw_pages) != 1:
        raise ValueError("Разметчик PDF не вернул запрошенную страницу")
    raw_page = raw_pages[0]
    if not isinstance(raw_page, dict):
        raise ValueError("Разметчик PDF вернул страницу неизвестного формата")

    page = document[page_index]
    raw_boxes = raw_page.get("boxes")
    boxes = (
        [box for box in raw_boxes if isinstance(box, dict)]
        if isinstance(raw_boxes, list)
        else []
    )
    levels = _list_levels(boxes)
    elements: list[ParsedElement] = []
    plain_parts: list[str] = []
    table_count = 0
    for box in boxes:
        box_class = str(box.get("boxclass") or "text")
        if box_class == "table":
            text = _table_markdown(box)
            if not text:
                continue
            kind: ElementKind = "table"
            plain_parts.append(_table_plain(box, text))
            table_count += 1
            level = None
        else:
            text = " ".join(_text_lines(box)).strip()
            if not text:
                continue
            kind = _box_kind(box_class, text)
            plain_parts.append(text)
            if kind == "heading":
                level = max(1, min(6, int(box.get("header_level") or 1)))
            elif kind == "list":
                level = levels.get(id(box), 1)
            else:
                level = None
        elements.append(
            ParsedElement(
                kind=kind,
                text=text,
                bbox=_normalized_bbox(box, page.rect.width, page.rect.height),
                level=level,
            )
        )

    if not elements:
        raise ValueError("Разметчик PDF не нашёл текстовых элементов")
    plain = "\n".join(plain_parts)
    diagnostics = [
        "layout_markdown",
        f"tables:{table_count}",
        f"structure_elements:{len(elements)}",
    ]
    if re.search(r"[∑∫√≈≤≥]", plain):
        diagnostics.append("formula_possible")
    return ParsedPage(
        page_number=page_index + 1,
        width=page.rect.width,
        height=page.rect.height,
        markdown=_markdown(elements),
        plain_text=plain,
        quality="native",
        elements=tuple(elements),
        diagnostics=tuple(diagnostics),
    )
