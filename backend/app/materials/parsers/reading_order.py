"""Порядок чтения страницы: рекурсивный XY-Cut и поправка на наклон скана.

Детектор строк отдаёт прямоугольники в том порядке, в котором их нашла сеть, а
не в том, в котором их читает человек. Сортировка «сверху вниз, слева направо»
верна только для одноколоночной страницы: на статье в две колонки она чередует
колонки построчно, и восстановить текст после этого уже нельзя — ни склейкой
абзацев, ни моделью.

XY-Cut (Nagy, Seth, 1984) режет множество прямоугольников полосой пустоты:
сначала горизонтальной, а когда горизонтальной нет — вертикальной, и так
рекурсивно. Порядок проб не случаен. Страница расслаивается горизонтально на
колонтитул, заголовок и тело; вертикальная граница между колонками существует
только внутри тела, то есть становится видна лишь после того, как
горизонтальные разрезы отделили общие для обеих колонок части.

Модуль работает с любыми прямоугольниками в любой одной системе координат
(нормализованной `0..1` или пиксельной) и ничего не знает ни про OCR, ни про
PDF: на вход последовательность рамок, на выход перестановка их индексов.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

# Прямоугольник (x0, y0, x1, y1) в системе координат вызывающего.
Box = tuple[float, float, float, float]

# Полоса пустоты между колонками. Реальный межколонник на A4 — 5–8% ширины
# полосы набора; 3% дают запас на узкий межколонник и одновременно не дают
# развалить одну колонку рваного текста на две.
MIN_COLUMN_GAP = 0.03
# Полоса пустоты между абзацами — доля от медианной высоты строки. Междустрочный
# интервал в наборе редко превышает половину высоты строки, межабзацный — больше.
MIN_ROW_GAP_RATIO = 0.6
# Нижняя граница на случай вырожденной страницы из одной-двух строк.
MIN_ROW_GAP = 0.004
# Глубина рекурсии. Реальная вложенность страницы — единицы уровней; предел
# нужен только чтобы патологический ввод не съел стек.
MAX_DEPTH = 12

# Дальше этого наклон уже не опечатка сканера, а перевёрнутая или снятая под
# углом страница: поправка координат её не спасёт, поворачивать нечего.
MAX_SKEW_DEG = 8.0
# Ниже этого поправка меняет порядок строк реже, чем ошибается сама.
MIN_SKEW_DEG = 0.15


def reading_order(boxes: Sequence[Box]) -> list[int]:
    """Расставить прямоугольники в порядке чтения и вернуть их индексы.

    Возвращает перестановку `range(len(boxes))`: сам список рамок не трогается,
    потому что вызывающий хранит рядом с ними текст и оценки уверенности.

    :param boxes: рамки в одной системе координат, порядок произвольный.
    :return: индексы `boxes` в порядке чтения.
    """
    if len(boxes) <= 1:
        return list(range(len(boxes)))
    heights = [box[3] - box[1] for box in boxes if box[3] > box[1]]
    row_gap = max(MIN_ROW_GAP, MIN_ROW_GAP_RATIO * median(heights)) if heights else MIN_ROW_GAP
    order: list[int] = []
    _cut(list(range(len(boxes))), boxes, row_gap, 0, order)
    return order


def _cut(
    indices: list[int],
    boxes: Sequence[Box],
    row_gap: float,
    depth: int,
    out: list[int],
) -> None:
    """Один шаг рекурсии: разрезать группу и обойти части в порядке чтения."""
    if len(indices) <= 1 or depth >= MAX_DEPTH:
        out.extend(_fallback_order(indices, boxes))
        return
    groups = _split(indices, boxes, axis=1, gap=row_gap)
    if groups is None:
        groups = _split(indices, boxes, axis=0, gap=MIN_COLUMN_GAP)
    if groups is None:
        out.extend(_fallback_order(indices, boxes))
        return
    for group in groups:
        _cut(group, boxes, row_gap, depth + 1, out)


def _fallback_order(indices: Sequence[int], boxes: Sequence[Box]) -> list[int]:
    """Неделимая группа: строки одной колонки, сверху вниз и слева направо."""
    return sorted(indices, key=lambda index: (boxes[index][1], boxes[index][0]))


def _split(
    indices: Sequence[int],
    boxes: Sequence[Box],
    *,
    axis: int,
    gap: float,
) -> list[list[int]] | None:
    """Разрезать группу по всем полосам пустоты вдоль оси.

    Заметающая прямая идёт по началам отрезков и держит `reach` — самый дальний
    достигнутый конец. Разрыв объявляется там, где следующий отрезок начинается
    дальше `reach` больше чем на `gap`; так одна высокая рамка (иллюстрация во
    всю колонку) не даёт разрезать группу поперёк себя.

    :param axis: 0 — резать по X (колонки), 1 — по Y (полосы сверху вниз).
    :return: две и более частей в порядке следования вдоль оси либо `None`,
        если полосы пустоты нет и группа неделима.
    """
    spans = sorted((boxes[index][axis], boxes[index][axis + 2], index) for index in indices)
    groups: list[list[int]] = []
    current: list[int] = [spans[0][2]]
    reach = spans[0][1]
    for start, end, index in spans[1:]:
        if start - reach > gap:
            groups.append(current)
            current = [index]
        else:
            current.append(index)
        reach = max(reach, end)
    groups.append(current)
    return groups if len(groups) > 1 else None


def skew_angle(quads: Sequence[Sequence[Sequence[float]]]) -> float:
    """Наклон страницы в градусах по четырёхугольникам детектора строк.

    Детектор PP-OCRv5 отдаёт не прямоугольники, а квады: у наклонённой строки
    верхнее ребро наклонено ровно на угол страницы. Медиана по всем строкам
    устойчива к отдельным косым подписям и к формулам.

    Положительный угол — страница повёрнута по часовой стрелке.

    :param quads: список квадов, каждый — четыре точки `(x, y)` по часовой
        стрелке начиная с левого верхнего угла.
    :return: угол в градусах; `0.0`, если наклон не определяется или слишком
        велик, чтобы его можно было исправить поправкой координат.
    """
    angles: list[float] = []
    for quad in quads:
        if len(quad) < 2:
            continue
        (x0, y0), (x1, y1) = quad[0][:2], quad[1][:2]
        width = x1 - x0
        if width <= 0:
            continue
        angle = math.degrees(math.atan2(y1 - y0, width))
        if abs(angle) <= MAX_SKEW_DEG:
            angles.append(angle)
    if not angles:
        return 0.0
    value = median(angles)
    return value if abs(value) >= MIN_SKEW_DEG else 0.0


def correct_skew(boxes: Sequence[Box], angle: float, width: float, height: float) -> list[Box]:
    """Повернуть рамки вокруг центра страницы на `-angle` — только для порядка.

    Наклон в один градус сдвигает низ страницы относительно верха примерно на
    высоту строки: на широкой странице правая колонка «уезжает» вверх, и XY-Cut
    режет её не там. Сохранять исправленные координаты нельзя — они больше не
    соответствуют картинке, по которой пользователь ищет фрагмент глазами,
    поэтому результат используется как ключ сортировки и выбрасывается.

    :param angle: наклон в градусах из :func:`skew_angle`.
    :param width: ширина страницы в той же системе координат, что и рамки.
    :param height: высота страницы там же.
    :return: рамки с исправленным наклоном, в том же порядке.
    """
    if angle == 0.0:
        return list(boxes)
    radians = math.radians(-angle)
    cos, sin = math.cos(radians), math.sin(radians)
    center_x, center_y = width / 2, height / 2

    def rotate(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - center_x, y - center_y
        return center_x + dx * cos - dy * sin, center_y + dx * sin + dy * cos

    corrected: list[Box] = []
    for x0, y0, x1, y1 in boxes:
        top_left = rotate(x0, y0)
        bottom_right = rotate(x1, y1)
        corrected.append(
            (
                min(top_left[0], bottom_right[0]),
                min(top_left[1], bottom_right[1]),
                max(top_left[0], bottom_right[0]),
                max(top_left[1], bottom_right[1]),
            )
        )
    return corrected
