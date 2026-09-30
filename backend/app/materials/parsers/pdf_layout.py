import hashlib
import json
import re
import struct
from collections.abc import Iterable, Sequence

import pymupdf as fitz

from app.materials.parsers import raster
from app.materials.parsers.base import (
    IMAGE_PLACEHOLDER,
    ElementKind,
    ImageMeta,
    ParsedElement,
    ParsedPage,
)
from app.materials.parsers.formula_zones import readable
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


def _png_size(data: bytes) -> tuple[int, int] | None:
    """Размер PNG из заголовка IHDR — без декодирования всего выреза."""
    if len(data) < 24 or data[1:4] != b"PNG":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


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


type Rect = tuple[float, float, float, float]


def _span_center(span: dict[str, object]) -> tuple[float, float] | None:
    bbox = span.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        return (float(bbox[0]) + float(bbox[2])) / 2, (float(bbox[1]) + float(bbox[3])) / 2
    except (TypeError, ValueError):
        return None


def _excluded(span: dict[str, object], exclude: Sequence[Rect]) -> bool:
    center = _span_center(span)
    if center is None:
        return False
    x, y = center
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in exclude)


def _line_text(raw_line: dict[str, object], exclude: Sequence[Rect] = ()) -> str:
    """Склеивает спаны строки, вставляя пробел там, где между ними есть просвет.

    PDF-вёрстка (особенно LaTeX с выключкой по ширине) часто отдаёт каждое слово
    отдельным спаном без символа пробела — пробел выражен только зазором между
    координатами соседних спанов.

    :param exclude: зоны отдельно стоящих формул в пунктах. Их спаны — линейная
        строка формулы («EQ=(f9−f(z))⋅η») или пустота вместо невидимых глифов;
        формула придёт вырезом, а в абзаце её обломки только мешают.
    """
    spans = raw_line.get("spans")
    if not isinstance(spans, list):
        return ""
    parts: list[str] = []
    previous_x1: float | None = None
    previous_size = 10.0
    for span in spans:
        if not isinstance(span, dict) or (exclude and _excluded(span, exclude)):
            continue
        text = readable(str(span.get("text", "")), str(span.get("font", "")))
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
    return [text for group in _line_groups(box) for text, _ in group]


def _line_bbox(raw_line: dict[str, object]) -> Rect | None:
    bbox = raw_line.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        return float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError):
        return None


def _line_groups(
    box: dict[str, object], exclude: Sequence[Rect] = ()
) -> list[list[tuple[str, Rect | None]]]:
    """Строки бокса, разбитые на группы там, где между ними стояла формула.

    Разметчик кладёт выносную формулу в один бокс с абзацами над и под ней.
    Когда её строки уходят в вырез, абзац над формулой и абзац под ней —
    разные элементы: иначе формула встала бы до или после склеенного целого.
    """
    groups: list[list[tuple[str, Rect | None]]] = [[]]
    raw_lines = box.get("textlines")
    if not isinstance(raw_lines, list):
        return []
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue
        text = _line_text(raw_line, exclude)
        if text:
            groups[-1].append((text, _line_bbox(raw_line)))
        elif exclude and groups[-1] and _line_text(raw_line):
            groups.append([])
    return [group for group in groups if group]


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
    return readable(str(table.get("markdown") or "")).strip()


def _table_plain(box: dict[str, object], markdown: str) -> str:
    table = box.get("table")
    extracted = table.get("extract") if isinstance(table, dict) else None
    if not isinstance(extracted, list):
        return markdown
    lines = []
    for row in extracted:
        if isinstance(row, list):
            lines.append(" | ".join(readable(str(cell or "")).strip() for cell in row))
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
    return " ".join(readable(text).split())


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


def _group_bbox(
    group: Sequence[tuple[str, Rect | None]], box: dict[str, object], page: fitz.Page
) -> tuple[float, float, float, float]:
    rects = [rect for _, rect in group if rect is not None]
    if not rects:
        return _normalized_bbox(box, page.rect.width, page.rect.height)
    return _normalized_bbox(
        {
            "x0": min(rect[0] for rect in rects),
            "y0": min(rect[1] for rect in rects),
            "x1": max(rect[2] for rect in rects),
            "y1": max(rect[3] for rect in rects),
        },
        page.rect.width,
        page.rect.height,
    )


def parse_layout_page(
    document: fitz.Document,
    page_index: int,
    owner: str = "",
    formula_zones: Sequence[tuple[float, float, float, float]] = (),
) -> ParsedPage:
    """Преобразует один текстовый PDF-лист в Markdown и элементы с координатами.

    :param owner: папка материала для вырезок формул; пустая строка — не резать.
    :param formula_zones: рамки отдельно стоящих формул в долях страницы
        (`formula_zones.find_zones`). Их строки выбрасываются из текстовых
        боксов: формулы придут своими элементами-вырезами.
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
    width, height = page.rect.width, page.rect.height
    exclude = [
        (x0 * width, y0 * height, x1 * width, y1 * height) for x0, y0, x1, y1 in formula_zones
    ]
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
        if box_class == "table":
            text = _table_markdown(box)
            if text:
                plain_parts.append(_table_plain(box, text))
                table_count += 1
            pieces = [(text, _normalized_bbox(box, width, height), "table")]
        else:
            groups = _line_groups(box, exclude)
            if exclude and not groups and _text_lines(box):
                continue  # бокс целиком из строк формул: они придут вырезами
            if len(groups) > 1:
                pieces = []
                for group in groups:
                    text = _join_box_lines([line for line, _ in group]).strip()
                    pieces.append((text, _group_bbox(group, box, page), _box_kind(box_class, text)))
            else:
                text = _join_box_lines([line for group in groups for line, _ in group]).strip()
                kind: ElementKind = _box_kind(box_class, text)
                if not text and kind == "formula":
                    text = _formula_fallback(box, page)
                bbox = (
                    _group_bbox(groups[0], box, page)
                    if groups and exclude and kind not in {"image", "formula"}
                    else _normalized_bbox(box, width, height)
                )
                pieces = [(text, bbox, kind)]
        for part, (text, bbox, kind) in enumerate(pieces):
            level: int | None = None
            if kind == "heading":
                level = max(1, min(6, int(box.get("header_level") or 1)))
            elif kind == "list":
                level = levels.get(id(box), 1)
            if text and kind != "table":
                plain_parts.append(text)
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
            asset_path: str | None = None
            image_meta: ImageMeta | None = None
            if owner and kind in {"image", "formula", "table"}:
                crop = raster.region_image(page, bbox)
                suffix = f"-{part}" if part else ""
                asset_path = store_material_asset(
                    owner, f"p{page_index + 1}-{kind}{index}{suffix}.png", crop
                )
                if kind == "image":
                    image_meta = ImageMeta(
                        detection="layout",
                        crop_hash=hashlib.sha256(crop).hexdigest(),
                        pixel_size=_png_size(crop),
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
                    image=image_meta,
                )
            )

    if not elements and not formula_zones:
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
