"""Рамки ответа модели по целой странице — к настоящей геометрии PDF.

Прочитав страницу целиком, модель указывает место каждого элемента с ошибкой
до двух строк (на методичке «Теорема 3:» у неё на 0,808 высоты вместо 0,769).
По таким рамкам резались схемы, а проверка пропусков объявляла «пропущенным»
всё, что рамка не накрыла: в материал уходили обрывки строк и схемы по кускам.

У страницы с текстовым слоем точная геометрия уже есть: строки и слова слоя,
встроенные растры, векторные схемы и сетки таблиц, зоны формул. Здесь рамка
каждого элемента модели приводится к ней: абзац — к словам, которые он
содержит, схема — к рисунку страницы, таблица — к своей сетке, формула — к
своей зоне. Чего модель не вернула вовсе, добавляется из слоя: строка текста
как есть, рисунок и формула вырезом. Страница без слоя (скан) так не умеет —
для неё только склеиваются куски одного рисунка.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

import pymupdf as fitz

from app.materials.parsers.base import IMAGE_PLACEHOLDER, ImageMeta, ParsedElement, ParsedPage
from app.materials.parsers.formula_zones import FormulaZone, readable

type Box = tuple[float, float, float, float]

# Насколько модель ошибается в месте элемента, в долях страницы: по вертикали
# до двух строк, по горизонтали — меньше, колонка у неё обычно верная.
DRIFT_Y = 0.05
DRIFT_X = 0.03
# Меньше по любой стороне — значок, линейка или формула в строку, а не рисунок.
MIN_FIGURE_SIDE_PT = 24.0
# Абзац привязан к словам слоя, если нашлась хотя бы такая доля его слов.
MIN_WORD_MATCH = 0.4
# Строка слоя пропущена моделью, если в её ответе нет такой доли слов строки.
MISSED_WORD_SHARE = 0.6
MIN_MISSED_TOKENS = 3
# Кластер путей — рисунок, если кривых и косых линий в нём хотя бы столько.
FIGURE_PATH_SHARE = 0.3
# Куски одного рисунка у модели стоят вплотную или налезают друг на друга.
SPLIT_IMAGE_GAP = 0.02
TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
TEX_COMMAND_RE = re.compile(r"\\[a-zA-Z]+")


@dataclass(frozen=True, slots=True)
class _Word:
    box: Box
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _LayerLine:
    box: Box
    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PageGeometry:
    """Точная геометрия страницы с текстовым слоем, в долях её размера."""

    words: tuple[_Word, ...]
    lines: tuple[_LayerLine, ...]
    figures: tuple[Box, ...]
    grids: tuple[Box, ...]
    zones: tuple[FormulaZone, ...]


def _tokens(text: str) -> tuple[str, ...]:
    """Слова для сверки: без команд LaTeX, в нижнем регистре, от двух знаков."""
    plain = TEX_COMMAND_RE.sub(" ", text)
    return tuple(token for token in TOKEN_RE.findall(plain.casefold()) if len(token) >= 2)


def _normalized(rect: fitz.Rect, page: fitz.Page) -> Box:
    width, height = page.rect.width, page.rect.height
    return (
        max(0.0, rect.x0 / width),
        max(0.0, rect.y0 / height),
        min(1.0, rect.x1 / width),
        min(1.0, rect.y1 / height),
    )


def _area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(first: Box, second: Box) -> float:
    return _area(
        (
            max(first[0], second[0]),
            max(first[1], second[1]),
            min(first[2], second[2]),
            min(first[3], second[3]),
        )
    )


def _expanded(box: Box) -> Box:
    return (box[0] - DRIFT_X, box[1] - DRIFT_Y, box[2] + DRIFT_X, box[3] + DRIFT_Y)


def _union(boxes: Sequence[Box]) -> Box:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _inside(point: tuple[float, float], box: Box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _x_overlap(first: Box, second: Box) -> float:
    width = min(first[2] - first[0], second[2] - second[0])
    overlap = min(first[2], second[2]) - max(first[0], second[0])
    return overlap / width if width > 0 else 0.0


def _figure_share(drawings: Sequence[dict]) -> float:
    """Доля элементов рисунка среди путей кластера: кривые и косые линии.

    Сетка таблицы — прямые по осям, но в таблице истинности бывают перечёркнутые
    крестом ячейки: пара косых линий на полсотни прямых таблицу рисунком не делает.
    """
    total = figure = 0
    for drawing in drawings:
        for item in drawing.get("items", ()):
            total += 1
            if item[0] == "c":
                figure += 1
            elif item[0] == "l":
                start, end = item[1], item[2]
                figure += abs(start.x - end.x) > 1 and abs(start.y - end.y) > 1
    return figure / total if total else 0.0


def _drawing_clusters(page: fitz.Page) -> tuple[list[Box], list[Box]]:
    """Векторные рисунки и сетки таблиц страницы."""
    try:
        drawings = page.get_drawings()
        clusters = page.cluster_drawings(drawings=drawings) if drawings else []
    except (RuntimeError, ValueError, AttributeError):
        return [], []
    figures: list[Box] = []
    grids: list[Box] = []
    for cluster in clusters:
        rect = fitz.Rect(cluster) & page.rect
        if rect.width < MIN_FIGURE_SIDE_PT or rect.height < MIN_FIGURE_SIDE_PT:
            continue
        inside = [drawing for drawing in drawings if fitz.Rect(drawing["rect"]).intersects(rect)]
        target = figures if _figure_share(inside) >= FIGURE_PATH_SHARE else grids
        target.append(_normalized(rect, page))
    return figures, grids


def _embedded_figures(page: fitz.Page) -> list[Box]:
    try:
        infos = page.get_image_info()
    except (RuntimeError, ValueError):
        return []
    boxes: list[Box] = []
    for info in infos:
        rect = fitz.Rect(info.get("bbox", (0, 0, 0, 0))) & page.rect
        if rect.width >= MIN_FIGURE_SIDE_PT and rect.height >= MIN_FIGURE_SIDE_PT:
            boxes.append(_normalized(rect, page))
    return boxes


def _distinct(boxes: Sequence[Box]) -> list[Box]:
    """Без вложенных дублей: растр внутри векторной рамки — один рисунок."""
    result: list[Box] = []
    for box in sorted(boxes, key=_area, reverse=True):
        if any(_intersection(box, kept) >= 0.8 * _area(box) for kept in result):
            continue
        result.append(box)
    return result


def _layer_lines(page: fitz.Page) -> tuple[list[_Word], list[_LayerLine]]:
    words: list[_Word] = []
    lines: list[_LayerLine] = []
    width, height = page.rect.width, page.rect.height
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        tokens = _tokens(readable(word))
        if tokens:
            words.append(_Word((x0 / width, y0 / height, x1 / width, y1 / height), tokens))
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(
                readable(str(span.get("text", "")), str(span.get("font", "")))
                for span in line.get("spans", [])
            )
            text = " ".join(text.split())
            if text:
                lines.append(
                    _LayerLine(_normalized(fitz.Rect(line["bbox"]), page), text, _tokens(text))
                )
    return words, lines


def page_geometry(page: fitz.Page, zones: Sequence[FormulaZone]) -> PageGeometry:
    words, lines = _layer_lines(page)
    vector, grids = _drawing_clusters(page)
    return PageGeometry(
        tuple(words),
        tuple(lines),
        tuple(_distinct([*_embedded_figures(page), *vector])),
        tuple(grids),
        tuple(zones),
    )


def _similar(first: Box, second: Box) -> bool:
    """Рамки одного размера с точностью до ошибки модели."""
    widths = sorted((first[2] - first[0], second[2] - second[0]))
    heights = sorted((first[3] - first[1], second[3] - second[1]))
    return widths[0] >= 0.4 * widths[1] and heights[0] >= 0.4 * heights[1]


def _best(
    box: Box,
    candidates: Sequence[Box],
    used: set[int] | None = None,
    *,
    pieces: bool = False,
) -> int | None:
    """Кандидат, лучше всех совпадающий с рамкой модели с поправкой на её ошибку.

    :param pieces: рамка модели может быть куском кандидата (модель разрезала
        схему на части); иначе размеры должны совпадать — формула из двух
        знаков не привязывается к зоне целой строки и наоборот.
    """
    wide = _expanded(box)
    best: tuple[float, int] | None = None
    for index, candidate in enumerate(candidates):
        if used is not None and index in used:
            continue
        shared = _intersection(wide, candidate)
        smaller = min(_area(candidate), _area(box)) or 1e-9
        if shared < 0.5 * smaller:
            continue
        inside = _intersection(_expanded(candidate), box) >= 0.6 * (_area(box) or 1e-9)
        if not _similar(box, candidate) and not (pieces and inside):
            continue
        score = _intersection(box, candidate) / (_area(candidate) or 1e-9) + shared / smaller
        if best is None or score > best[0]:
            best = (score, index)
    return best[1] if best else None


def _word_box(element: ParsedElement, words: Sequence[_Word]) -> Box | None:
    """Рамка слов слоя, из которых состоит текст элемента.

    Слова ищутся не по одному, а выравниванием последовательностей: у соседних
    абзацев общие слова («формулы», «алгебры»), и совпадение по отдельным словам
    растягивало рамку на оба абзаца. Совпавший подряд кусок из одного слова не
    считается, если слов у элемента больше двух.
    """
    wanted = list(_tokens(element.text))
    # Одно короткое слово («15», «Да») найдётся где угодно; одно длинное
    # («Доказательство:») — годится.
    if not wanted or (len(wanted) == 1 and len(wanted[0]) < 5):
        return None
    wide = _expanded(element.bbox)
    window = [word for word in words if _inside(_center(word.box), wide)]
    flat = [(index, token) for index, word in enumerate(window) for token in word.tokens]
    if not flat:
        return None
    matcher = SequenceMatcher(None, [token for _, token in flat], wanted, autojunk=False)
    shortest = 1 if len(wanted) <= 2 else 2
    blocks = [block for block in matcher.get_matching_blocks() if block.size >= shortest]
    found = sum(block.size for block in blocks)
    if not blocks or found < max(min(2, len(wanted)), MIN_WORD_MATCH * len(wanted)):
        return None
    first = flat[blocks[0].a][0]
    last = flat[blocks[-1].a + blocks[-1].size - 1][0]
    words_box = _union([word.box for word in window[first : last + 1]])
    # По вертикали модель ошибается на строки, по горизонтали почти нет, а
    # слова абзаца с формулами внутри находятся не все: ширина — от модели.
    return (
        min(element.bbox[0], words_box[0]),
        words_box[1],
        max(element.bbox[2], words_box[2]),
        words_box[3],
    )


def _snapped_image(element: ParsedElement, box: Box) -> ParsedElement:
    labels = element.text if element.text != IMAGE_PLACEHOLDER else ""
    return replace(
        element,
        bbox=box,
        image=ImageMeta(
            processing="legacy" if labels.strip() else "unprocessed",
            detection="cloud_page",
            signals=("layer_geometry",),
        ),
    )


def _insert(elements: list[ParsedElement], added: ParsedElement) -> None:
    """Вставить элемент перед первым, что стоит ниже него в той же колонке."""
    middle = _center(added.bbox)[1]
    for index, element in enumerate(elements):
        if _center(element.bbox)[1] > middle and _x_overlap(element.bbox, added.bbox) > 0:
            elements.insert(index, added)
            return
    elements.append(added)


def _merge_images(elements: list[ParsedElement], owners: dict[int, int]) -> list[ParsedElement]:
    """Элементы-картинки, привязанные к одному рисунку, — один элемент."""
    first: dict[int, int] = {}
    result: list[ParsedElement] = []
    positions: dict[int, int] = {}
    for index, element in enumerate(elements):
        figure = owners.get(index)
        if figure is None or figure not in first:
            if figure is not None:
                first[figure] = index
                positions[figure] = len(result)
            result.append(element)
            continue
        kept = result[positions[figure]]
        texts = [text for text in (kept.text, element.text) if text != IMAGE_PLACEHOLDER]
        merged = "\n".join(texts) if texts else IMAGE_PLACEHOLDER
        result[positions[figure]] = _snapped_image(replace(kept, text=merged), kept.bbox)
    return result


def snap_to_layer(parsed: ParsedPage, geometry: PageGeometry) -> ParsedPage:
    """Рамки элементов модели — по слою; пропущенное моделью — из слоя."""
    elements = list(parsed.elements)
    figures = list(geometry.figures)
    # Выносная формула модели — отдельно стоящая зона; строчные живут в абзацах.
    zone_boxes = [zone.box if zone.standalone else (0.0, 0.0, 0.0, 0.0) for zone in geometry.zones]
    used_figures: set[int] = set()
    used_grids: set[int] = set()
    used_zones: set[int] = set()
    owners: dict[int, int] = {}
    snapped = 0
    for index, element in enumerate(elements):
        if not element.bbox_reliable:
            continue
        box: Box | None = None
        if element.kind == "image":
            found = _best(element.bbox, figures, pieces=True)
            if found is not None:
                owners[index] = found
                used_figures.add(found)
                elements[index] = _snapped_image(element, figures[found])
                snapped += 1
            continue
        if element.kind == "table":
            found = _best(element.bbox, geometry.grids, used_grids)
            if found is not None:
                used_grids.add(found)
                box = geometry.grids[found]
        elif element.kind == "formula":
            found = _best(element.bbox, zone_boxes, used_zones)
            if found is not None:
                used_zones.add(found)
                box = zone_boxes[found]
        box = box or _word_box(element, geometry.words)
        if box is not None:
            elements[index] = replace(element, bbox=box)
            snapped += 1
    elements = _merge_images(elements, owners)
    added = _missed_from_layer(elements, geometry, used_figures, used_zones)
    for element in added:
        _insert(elements, element)
    diagnostics = [f"layer_snapped:{snapped}"]
    if added:
        diagnostics.append(f"layer_added:{len(added)}")
    return replace(
        parsed,
        elements=tuple(elements),
        diagnostics=(*parsed.diagnostics, *diagnostics),
    )


def _missed_from_layer(
    elements: Sequence[ParsedElement],
    geometry: PageGeometry,
    used_figures: set[int],
    used_zones: set[int],
) -> list[ParsedElement]:
    """Что модель не вернула: рисунки и формулы вырезами, строки — текстом слоя.

    Строка считается пропущенной, только если её слов нет в ответе модели:
    модель, указавшая абзац не там, его всё-таки прочитала.
    """
    added: list[ParsedElement] = []
    boxes = [element.bbox for element in elements]
    for index, figure in enumerate(geometry.figures):
        if index in used_figures:
            continue
        if any(_intersection(figure, box) >= 0.5 * _area(figure) for box in boxes):
            continue  # модель прочитала его таблицей или формулой
        added.append(
            ParsedElement(
                "image",
                IMAGE_PLACEHOLDER,
                figure,
                image=ImageMeta(detection="layer_figure", signals=("missed_by_model",)),
            )
        )
    # Вокруг любого элемента модели — полоса её ошибки: формула, которую модель
    # прочитала в абзаце, таблице или со сдвигом на строку, уже в ответе, и её
    # вырез рядом был бы дублем. Ячейки таблицы и надписи схемы — забота их самих.
    nearby = [_expanded(box) for box in boxes]
    for index, zone in enumerate(geometry.zones):
        if index in used_zones or not zone.standalone:
            continue
        center = _center(zone.box)
        if any(_inside(center, box) for box in (*nearby, *geometry.grids, *geometry.figures)):
            continue
        added.append(ParsedElement("formula", IMAGE_PLACEHOLDER, zone.box))
    spoken = Counter(token for element in elements for token in _tokens(element.text))
    blocked = [*boxes, *geometry.figures]
    missed: list[_LayerLine] = []
    for line in geometry.lines:
        if len(line.tokens) < MIN_MISSED_TOKENS:
            continue
        if any(_inside(_center(line.box), box) for box in blocked):
            continue
        absent = sum(1 for token in line.tokens if spoken[token] == 0)
        if absent >= MISSED_WORD_SHARE * len(line.tokens):
            missed.append(line)
    for group in _paragraphs(missed):
        text = group[0].text
        for line in group[1:]:
            text = (
                text[:-1] + line.text
                if text.endswith("-") and line.text[:1].islower()
                else f"{text} {line.text}"
            )
        added.append(ParsedElement("paragraph", text, _union([line.box for line in group])))
    return added


def _paragraphs(lines: Sequence[_LayerLine]) -> list[list[_LayerLine]]:
    groups: list[list[_LayerLine]] = []
    for line in sorted(lines, key=lambda item: (item.box[1], item.box[0])):
        if groups:
            last = groups[-1][-1]
            height = last.box[3] - last.box[1]
            if (
                line.box[1] - last.box[3] <= height
                and _x_overlap(line.box, last.box) > 0
            ):
                groups[-1].append(line)
                continue
        groups.append([line])
    return groups


def merge_split_images(parsed: ParsedPage) -> ParsedPage:
    """Куски одного рисунка у модели — один элемент (скан без слоя)."""
    elements = list(parsed.elements)
    merged = 0
    index = 0
    while index < len(elements):
        element = elements[index]
        if element.kind != "image" or not element.bbox_reliable:
            index += 1
            continue
        partner = next(
            (
                other
                for other in range(index + 1, len(elements))
                if elements[other].kind == "image"
                and elements[other].bbox_reliable
                and _x_overlap(element.bbox, elements[other].bbox) >= 0.3
                and max(element.bbox[1], elements[other].bbox[1])
                - min(element.bbox[3], elements[other].bbox[3])
                <= SPLIT_IMAGE_GAP
            ),
            None,
        )
        if partner is None:
            index += 1
            continue
        other = elements.pop(partner)
        texts = [text for text in (element.text, other.text) if text != IMAGE_PLACEHOLDER]
        elements[index] = replace(
            element,
            bbox=_union([element.bbox, other.bbox]),
            text="\n".join(texts) if texts else IMAGE_PLACEHOLDER,
        )
        merged += 1
    if not merged:
        return parsed
    return replace(
        parsed,
        elements=tuple(elements),
        diagnostics=(*parsed.diagnostics, f"images_merged:{merged}"),
    )


# Непрочитанные куски скана ближе этого — один рисунок, разрезанный белыми
# промежутками сетки чернил.
REGION_MERGE_GAP = 0.015
# Кусок ниже этого (доля страницы) рядом с абзацем модели — это строка абзаца,
# который модель прочитала, но указала на строку-две выше или ниже.
ECHO_MAX_HEIGHT = 0.04


def unread_candidates(regions: Sequence[Box], elements: Sequence[ParsedElement]) -> list[Box]:
    """Непрочитанные куски скана без эха сдвинутых рамок, рисунки — целиком."""
    boxes = [tuple(box) for box in regions]
    merged = True
    while merged:
        merged = False
        for first in range(len(boxes)):
            for second in range(first + 1, len(boxes)):
                a, b = boxes[first], boxes[second]
                horizontal = max(a[0], b[0]) - min(a[2], b[2])
                vertical = max(a[1], b[1]) - min(a[3], b[3])
                if horizontal <= REGION_MERGE_GAP and vertical <= REGION_MERGE_GAP:
                    boxes[first] = _union([a, b])
                    del boxes[second]
                    merged = True
                    break
            if merged:
                break
    text = [element.bbox for element in elements if element.kind != "image"]
    return [
        box
        for box in boxes
        if not (
            box[3] - box[1] <= ECHO_MAX_HEIGHT
            and any(
                _x_overlap(box, other) >= 0.5
                and max(box[1], other[1]) - min(box[3], other[3]) <= DRIFT_Y
                for other in text
            )
        )
    ]
