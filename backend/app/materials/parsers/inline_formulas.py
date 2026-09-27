"""Формулы-картинки внутри строки и номера формул после распознавания вырезов.

Документ из Word с MathType (типичная методичка) хранит формулу картинкой
высотой в строку прямо посреди абзаца. Текстовый слой на её месте даёт пробелы,
поэтому без этого модуля абзац выходил с дырами («серию из   независимых
испытаний»), а сами формулы — отдельными блоками после него. Здесь прочитанная
формула возвращается в абзац как `$...$` на своё место в строке.

Место ищется по словам текстового слоя: сосед формулы слева (или справа, если
формула начинает строку) и номер его вхождения среди слов абзаца. Не нашли
соседа — формула остаётся отдельным элементом, как было: лучше блок рядом, чем
формула не в том месте фразы.

Функции возвращают список той же длины и множество индексов, которые
вызывающий убирает сам: так их можно применять друг за другом.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.materials.parsers.base import ParsedElement

# Кто может приютить формулу в строке: обычный текст, пункт списка, заголовок.
HOST_KINDS = frozenset({"paragraph", "list", "heading"})
# Доля высоты меньшего из двух, при которой слово и формула стоят на одной строке.
SAME_LINE_OVERLAP = 0.5
# Запас по вертикали к рамке абзаца: разметка даёт её тоньше строк текста
# (середина строки, а не высота букв), и без запаса слово у края в абзац не попадёт.
HOST_SLACK = 0.008
# Номер формулы, который разметка вырезала отдельно от самой формулы:
# `\tag{3.2}` от модели или «(3.2)» из текстового слоя.
TAG_ONLY_RE = re.compile(
    r"^\s*\$*\s*(?:\\tag\{([^{}]+)\}|\(([\dIVXivx]+(?:[.,]\d+)*[a-zа-я]?)\))\s*\$*\s*$"
)
# Строка формул прирастает к таблице, если стоит не дальше этого от её рамки
# (доля высоты страницы, около строки текста) и не выходит за таблицу вбок.
TABLE_ROW_GAP = 0.02
TABLE_SIDE_SLACK = 0.05
PUNCTUATION_AFTER_RE = re.compile(r"(\$) +([.,;:!?)»])")
SPACES_RE = re.compile(r" {2,}")

type Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Word:
    """Слово текстового слоя в долях страницы."""

    box: Box
    text: str


def _line_overlap(first: Box, second: Box) -> float:
    top = max(first[1], second[1])
    bottom = min(first[3], second[3])
    height = min(first[3] - first[1], second[3] - second[1])
    return max(0.0, bottom - top) / height if height > 0 else 0.0


def _inside(point: tuple[float, float], box: Box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def inline_markup(kind: str, text: str) -> str:
    """Ответ модели про вырез — вставка в строку: формула в `$...$`, текст как есть."""
    body = text.strip()
    if kind != "formula":
        return body
    body = body.strip("$").strip()
    return f"${body}$" if body else ""


def _within(box: Box, host: Box) -> bool:
    """Центр рамки внутри абзаца с запасом по вертикали."""
    x, y = _center(box)
    return host[0] <= x <= host[2] and host[1] - HOST_SLACK <= y <= host[3] + HOST_SLACK


def _host(elements: Sequence[ParsedElement], box: Box) -> int | None:
    for index, element in enumerate(elements):
        if element.kind in HOST_KINDS and _within(box, element.bbox):
            return index
    return None


def _insertion(host: ParsedElement, words: Sequence[Word], box: Box) -> tuple[int, bool] | None:
    """Позиция в тексте абзаца, куда встаёт формула, и сторона вставки.

    `True` — формула встаёт после найденного слова, `False` — перед ним.
    """
    own = [word for word in words if _within(word.box, host.bbox)]
    line = [word for word in own if _line_overlap(word.box, box) >= SAME_LINE_OVERLAP]
    if not line:
        return None
    slack = (box[2] - box[0]) * 0.25
    left = [word for word in line if word.box[2] <= box[0] + slack]
    right = [word for word in line if word.box[0] >= box[2] - slack]
    candidates: list[tuple[Word, bool]] = []
    if left:
        candidates.append((max(left, key=lambda word: word.box[2]), True))
    if right:
        candidates.append((min(right, key=lambda word: word.box[0]), False))
    for anchor, after in candidates:
        occurrence = sum(1 for word in own[: own.index(anchor)] if word.text == anchor.text)
        # Целым словом: «и» не должно найтись внутри «вершинами».
        pattern = re.compile(rf"(?<!\w){re.escape(anchor.text)}(?!\w)")
        matches = list(pattern.finditer(host.text))
        if occurrence < len(matches):
            match = matches[occurrence]
            return (match.end(), True) if after else (match.start(), False)
    return None


def splice_inline(
    elements: Sequence[ParsedElement], words: Sequence[Word], candidates: Sequence[int]
) -> tuple[list[ParsedElement], set[int]]:
    """Вставить прочитанные формулы-картинки в их абзацы.

    :param candidates: индексы формул-картинок, у которых уже есть ответ модели.
    :return: элементы с обновлёнными абзацами и индексы вставленных формул.
    """
    inserts: dict[int, list[tuple[int, bool, str]]] = {}
    spliced: set[int] = set()
    for index in candidates:
        element = elements[index]
        markup = inline_markup(element.kind, element.text)
        host = _host(elements, element.bbox)
        if not markup or host is None:
            continue
        found = _insertion(elements[host], words, element.bbox)
        if found is None:
            continue
        inserts.setdefault(host, []).append((*found, markup))
        spliced.add(index)
    result = list(elements)
    for host, items in inserts.items():
        text = result[host].text
        # С конца, чтобы позиции ещё не вставленных формул не сдвигались.
        for position, after, markup in sorted(items, key=lambda item: item[0], reverse=True):
            piece = f" {markup}" if after else f"{markup} "
            text = text[:position] + piece + text[position:]
        text = PUNCTUATION_AFTER_RE.sub(r"\1\2", SPACES_RE.sub(" ", text))
        result[host] = replace(result[host], text=text, recognition_source="vl")
    return result, spliced


def merge_equation_tags(
    elements: Sequence[ParsedElement], skip: set[int] | None = None
) -> tuple[list[ParsedElement], set[int]]:
    """Номер формулы отдельным куском — в `\\tag{}` соседней слева формулы.

    Разметка режет выносную формулу и её номер справа на два куска, и без
    склейки в материале оставался пустой блок `$$\\tag{3.2}$$`. Номер бывает
    и прочитанным вырезом, и строкой текстового слоя «(3.2)».

    :param skip: индексы, которые уже убраны и в поиске не участвуют.
    :return: элементы и индексы номеров, ушедших в формулы.
    """
    result = list(elements)
    gone = set(skip or ())
    merged: set[int] = set()
    for index, element in enumerate(result):
        if element.kind not in {"formula", "paragraph"} or index in gone | merged:
            continue
        match = TAG_ONLY_RE.match(element.text)
        if match is None:
            continue
        partners = [
            other
            for other, item in enumerate(result)
            if other != index
            and other not in gone | merged
            and item.kind == "formula"
            and not TAG_ONLY_RE.match(item.text)
            and item.bbox[2] <= element.bbox[0] + 0.01
            and _line_overlap(item.bbox, element.bbox) >= SAME_LINE_OVERLAP
        ]
        if not partners:
            continue
        partner = max(partners, key=lambda other: result[other].bbox[2])
        body = result[partner].text.strip().strip("$").strip()
        if not body or "\\tag{" in body:
            continue
        tag = match.group(1) or match.group(2)
        result[partner] = replace(result[partner], text=f"$${body} \\tag{{{tag}}}$$")
        merged.add(index)
    return result, merged


def formulas_in_tables(
    elements: Sequence[ParsedElement], formulas: Sequence[int]
) -> dict[int, tuple[Box, list[int]]]:
    """Таблицы текстового слоя с формулами-картинками в ячейках и их полная рамка.

    Такая таблица в слое разваливается: строка, где все ячейки — картинки,
    в неё не попадает вовсе, и разметка отдаёт рамку одной строки заголовка.
    Поэтому к таблице прирастают соседние строки формул без своего абзаца (две и
    больше формулы на одной линии), а читается она одним вырезом целиком — это
    и дешевле, и даёт настоящую таблицу вместо россыпи формул.
    """
    free = [item for item in formulas if _host(elements, elements[item].bbox) is None]
    rows: list[list[int]] = []
    for item in sorted(free, key=lambda other: elements[other].bbox[1]):
        row = next(
            (
                row
                for row in rows
                if _line_overlap(elements[row[0]].bbox, elements[item].bbox) >= SAME_LINE_OVERLAP
            ),
            None,
        )
        if row is None:
            rows.append([item])
        else:
            row.append(item)
    tables: dict[int, tuple[Box, list[int]]] = {}
    for index, element in enumerate(elements):
        if element.kind != "table":
            continue
        box = element.bbox
        inner = [item for item in free if _inside(_center(elements[item].bbox), box)]
        pending = [row for row in rows if len(row) >= 2]
        grew = True
        while grew:
            grew = False
            for row in list(pending):
                row_box = _union([elements[item].bbox for item in row])
                middle = _center(row_box)[0]
                beside = box[0] - TABLE_SIDE_SLACK <= middle <= box[2] + TABLE_SIDE_SLACK
                near = row_box[1] <= box[3] + TABLE_ROW_GAP and row_box[3] >= box[1] - TABLE_ROW_GAP
                if beside and near:
                    inner.extend(item for item in row if item not in inner)
                    box = _union([box, row_box])
                    pending.remove(row)
                    grew = True
        if inner:
            tables[index] = (box, inner)
    return tables


def _union(boxes: Sequence[Box]) -> Box:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
