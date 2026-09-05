import json
import re
from collections.abc import Iterable, Sequence

import pymupdf as fitz

from app.materials.parsers import raster
from app.materials.parsers.base import (
    IMAGE_PLACEHOLDER,
    ElementKind,
    ParsedElement,
    ParsedPage,
)
from app.materials.storage import store_material_asset

INDENT_STEP = 18
MAX_LIST_LEVEL = 4
BULLET_RE = re.compile(r"^\s*[•▪◦‣·*+\-–—]\s+")

#: Классы разметчика, которые обозначают рисунок, а не текст. Строк у них нет
#: никогда: схема в LaTeX нарисована векторными путями, и в текстовом слое её
#: не существует.
PICTURE_CLASSES = frozenset({"picture", "figure", "image", "chart", "diagram"})

#: Колонтитулы: пустой бокс здесь означает пустой колонтитул, а не потерю.
SERVICE_CLASSES = frozenset({"page-header", "page-footer"})

#: Ниже этого по любой стороне область не содержание, а линейка или значок.
MIN_REGION_SIDE_PT = 24
# Мягкий и обычный дефис на конце строки — перенос слова, который PDF-вёрстка
# ломает на пробел при склейке строк обратно в абзац.
SOFT_HYPHEN_RE = re.compile(r"(\w)[-‐­]$")


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


def _span_bbox(span: dict[str, object]) -> tuple[float, float] | None:
    bbox = span.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 3:
        return None
    try:
        return float(bbox[0]), float(bbox[2])
    except (TypeError, ValueError):
        return None


def _line_text(raw_line: dict[str, object]) -> str:
    """Склеивает спаны строки, вставляя пробел там, где между ними есть просвет.

    PDF-вёрстка (особенно LaTeX с выключкой по ширине) часто отдаёт каждое слово
    отдельным спаном без символа пробела — пробел выражен только зазором между
    координатами соседних спанов.
    """
    spans = raw_line.get("spans")
    if not isinstance(spans, list):
        return ""
    parts: list[str] = []
    previous_x1: float | None = None
    previous_size = 10.0
    for span in spans:
        if not isinstance(span, dict):
            continue
        text = str(span.get("text", ""))
        if not text:
            continue
        span_bbox = _span_bbox(span)
        size = float(span.get("size") or previous_size)
        if parts and previous_x1 is not None and span_bbox is not None:
            gap = span_bbox[0] - previous_x1
            if (
                gap > 0.2 * max(size, previous_size)
                and not parts[-1].endswith(" ")
                and not text.startswith(" ")
            ):
                parts.append(" ")
        parts.append(text)
        if span_bbox is not None:
            previous_x1 = span_bbox[1]
            previous_size = size
    return "".join(parts).strip()


def _text_lines(box: dict[str, object]) -> list[str]:
    result: list[str] = []
    raw_lines = box.get("textlines")
    if not isinstance(raw_lines, list):
        return result
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue
        text = _line_text(raw_line)
        if text:
            result.append(text)
    return result


def _join_box_lines(lines: Sequence[str]) -> str:
    """Склеивает строки-обёртки абзаца в блоке, снимая перенос слова по дефису."""
    if not lines:
        return ""
    result = lines[0]
    for line in lines[1:]:
        match = SOFT_HYPHEN_RE.search(result)
        if match and line[:1].islower():
            result = result[: match.end(1)] + line
        else:
            result = f"{result} {line}"
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
    if box_class in PICTURE_CLASSES:
        return "image"
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


def _region_is_large_enough(box: dict[str, object]) -> bool:
    width = float(box.get("x1", 0)) - float(box.get("x0", 0))
    height = float(box.get("y1", 0)) - float(box.get("y0", 0))
    return width >= MIN_REGION_SIDE_PT and height >= MIN_REGION_SIDE_PT


def _box_rect(box: dict[str, object], page: fitz.Page) -> fitz.Rect:
    return fitz.Rect(
        float(box.get("x0", 0)),
        float(box.get("y0", 0)),
        float(box.get("x1", page.rect.width)),
        float(box.get("y1", page.rect.height)),
    )


def _formula_fallback(box: dict[str, object], page: fitz.Page) -> str:
    """Текст выносной формулы, которую разметчик отдал без единой строки.

    `pymupdf4llm` помечает выносную формулу классом `formula`, но `textlines` у
    неё пустые: математику он в строки не собирает. Прежде такой бокс молча
    выбрасывался вместе с содержанием — на странице учебника по теории
    вероятностей так исчезали шесть формул из шести, и в просмотрщике на их
    месте не было даже рамки.

    Глифы из слоя всё-таки достаются, но приходят линейно: числитель, потом
    знаменатель, потом остаток. Как LaTeX это не годится — годится как
    указание, что здесь формула, и как строка для поиска. Настоящий вид
    сохраняет вырезка рядом.
    """
    text = page.get_text("text", clip=_box_rect(box, page))
    return " ".join(text.split())


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


def parse_layout_page(
    document: fitz.Document, page_index: int, owner: str = ""
) -> ParsedPage:
    """Преобразует один текстовый PDF-лист в Markdown и элементы с координатами.

    :param owner: папка материала для вырезок формул; пустая строка — не резать.
    """
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
    formula_count = 0
    picture_count = 0
    textless_count = 0
    for index, box in enumerate(boxes):
        box_class = str(box.get("boxclass") or "text")
        asset_path: str | None = None
        level: int | None = None
        if box_class == "table":
            text = _table_markdown(box)
            kind: ElementKind = "table"
            if text:
                plain_parts.append(_table_plain(box, text))
                table_count += 1
        else:
            text = _join_box_lines(_text_lines(box)).strip()
            kind = _box_kind(box_class, text)
            if not text and kind == "formula":
                text = _formula_fallback(box, page)
            if kind == "heading":
                level = max(1, min(6, int(box.get("header_level") or 1)))
            elif kind == "list":
                level = levels.get(id(box), 1)
            if text:
                plain_parts.append(text)

        bbox = _normalized_bbox(box, page.rect.width, page.rect.height)
        if not text:
            # Отбрасываем только то, где содержания и не было: пустой колонтитул
            # и полоску тоньше пальца — линейку, точку списка, обрезок рамки.
            if box_class in SERVICE_CLASSES or not _region_is_large_enough(box):
                continue
            if kind not in {"image", "formula", "table"}:
                # Класс обещал текст, а строк у бокса нет. Молча выбрасывать
                # такое нельзя: содержание страницы исчезает, и привязать его
                # нечем. Сохраняем областью-рисунком и считаем в диагностике.
                kind = "image"
                textless_count += 1
            text = IMAGE_PLACEHOLDER
        # Вырез оригинала нужен всему, что не показать текстом: схеме, выносной
        # формуле (её строки разметчик не собирает) и таблице.
        if owner and kind in {"image", "formula", "table"}:
            asset_path = store_material_asset(
                owner,
                f"p{page_index + 1}-{kind}{index}.png",
                raster.region_image(page, bbox),
            )
        if kind == "formula":
            formula_count += 1
        elif kind == "image":
            picture_count += 1
        elements.append(
            ParsedElement(
                kind=kind,
                text=text,
                bbox=bbox,
                level=level,
                asset_path=asset_path,
            )
        )

    if not elements:
        raise ValueError("Разметчик PDF не нашёл текстовых элементов")
    plain = "\n".join(plain_parts)
    diagnostics = [
        "layout_markdown",
        f"tables:{table_count}",
        f"formulas:{formula_count}",
        f"pictures:{picture_count}",
        f"structure_elements:{len(elements)}",
    ]
    if textless_count:
        diagnostics.append(f"textless_boxes:{textless_count}")
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
