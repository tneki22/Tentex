"""Растр страницы под распознавание: разрешение и непрочитанные области.

Два вопроса, которые решаются до и после вызова OCR. До — с каким разрешением
рисовать страницу: слишком мелко, и распознаватель не видит букв; слишком
крупно, и разбор учебника растягивается на часы без выигрыша в качестве.
После — что на странице осталось нетронутым: распознаватель строк молча
пропускает всё, что на строку не похоже, и без отдельной проверки выносная
формула или график исчезают из материала бесследно.
"""

from __future__ import annotations

from collections.abc import Sequence

import pymupdf as fitz
from PIL import Image

# Прямоугольник (x0, y0, x1, y1), нормализованный по размеру страницы.
Box = tuple[float, float, float, float]

# Точек на дюйм в системе координат PDF: один пункт — 1/72 дюйма.
PDF_POINT_DPI = 72.0
# Разрешение при `raster_scale = 1.0`. Множитель из настроек тянет его вверх:
# 1.5 → 225 dpi (быстрее), 2.0 → 300 dpi (стандарт для печатного текста),
# 3.0 → 450 dpi (мелкий кегль и индексы в формулах).
BASE_RENDER_DPI = 150.0
# Ниже PP-OCRv5 теряет строчные буквы кегля 10 пунктов, выше — платим временем
# за пиксели, которых нет в исходнике.
MIN_RENDER_DPI = 150.0
MAX_RENDER_DPI = 450.0
# Насколько допустимо рисовать крупнее оригинала. Умеренное увеличение помогает
# детектору строк, всё что дальше — интерполяция без новой информации.
SUPERSAMPLE_LIMIT = 1.5

# Сетка поиска непрочитанных областей: сторона ячейки в пикселях уменьшённой
# копии страницы. Мельче — шум от зерна скана, крупнее — сливаются соседние
# формулы.
INK_CELL_PX = 6
# Ширина уменьшенной копии. Разрешения хватает, чтобы отличить формулу от
# пробела, а работы остаётся на сотые доли секунды.
INK_PREVIEW_WIDTH = 480
# Порог средней яркости ячейки, с которого она считается непустой. Ячейка
# усредняется целиком, поэтому порог близок к белому: восьмая часть чёрных
# пикселей опускает среднее примерно до 230.
INK_CELL_LEVEL = 240
# Запас вокруг рамок распознанных строк: детектор режет по глифам вплотную,
# и без запаса выносные элементы строки дают ложную область.
COVER_PADDING = 0.004
# Мельче этого — пылинка скана, линейка или точка над строкой, а не пропущенный
# кусок содержания. Доля от площади страницы.
MIN_REGION_AREA = 0.0015
# Поле страницы, внутри которого содержания не бывает. У скана здесь живёт
# тёмная полоса от края бумаги: она проходит по площади (длинная), но
# содержанием не является.
EDGE_MARGIN = 0.015

# Разрешение выреза одной области страницы. Формулу надо читать крупно, а во
# внешней модели платят за плитки 768×768 — 300 dpi ровно на этой границе.
REGION_DPI = 300.0
# Вырез берётся с полем: у формулы верхние индексы часто выходят за рамку блока.
REGION_PADDING_PT = 4.0


def region_image(page: fitz.Page, box: Box) -> bytes:
    """Вырез области страницы в PNG, крупнее исходной вёрстки и с полем.

    Одна вырезка на два потребителя: её отправляют во внешнюю модель (режим
    «Облако») и её же сохраняют рядом с формулой или схемой, чтобы просмотрщик
    показал оригинал, когда распознанному тексту верить нельзя.
    """
    rect = (
        fitz.Rect(
            box[0] * page.rect.width - REGION_PADDING_PT,
            box[1] * page.rect.height - REGION_PADDING_PT,
            box[2] * page.rect.width + REGION_PADDING_PT,
            box[3] * page.rect.height + REGION_PADDING_PT,
        )
        & page.rect
    )
    scale = REGION_DPI / PDF_POINT_DPI
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    return pixmap.tobytes("png")


def source_dpi(page: fitz.Page) -> float | None:
    """Разрешение исходного скана, если страница нарисована растром.

    У сканированного PDF страница — это одна большая картинка. Её разрешение
    считается из отношения пикселей к пунктам и говорит, сколько информации в
    файле есть на самом деле.

    :return: точек на дюйм либо `None`, если растровой основы нет (страница
        векторная) или её размеры не читаются.
    """
    page_width = page.rect.width
    if page_width <= 0:
        return None
    widest = 0.0
    for info in page.get_image_info():
        bbox = info.get("bbox")
        pixels = info.get("width")
        if not bbox or not pixels:
            continue
        covered = abs(bbox[2] - bbox[0])
        # Мелкие иллюстрации о разрешении страницы ничего не говорят.
        if covered < page_width * 0.5:
            continue
        widest = max(widest, float(pixels) * PDF_POINT_DPI / covered)
    return widest or None


def render_scale(page: fitz.Page, configured_scale: float) -> tuple[float, float]:
    """Множитель растеризации страницы и разрешение, которое он даёт.

    Настройка `raster_scale` — не зум, а требование к качеству: она задаёт
    желаемое разрешение, а модуль приводит его к тому, что реально есть в файле.
    Прежняя постоянная ×2 означала 144 dpi независимо от исходника — для скана
    в 300 dpi это выбрасывало больше половины пикселей ещё до распознавания.

    :param configured_scale: значение из настроек распознавания.
    :return: пара «множитель для :class:`fitz.Matrix`, итоговое разрешение».
    """
    target = BASE_RENDER_DPI * configured_scale
    source = source_dpi(page)
    if source is not None:
        target = min(target, source * SUPERSAMPLE_LIMIT)
    target = max(MIN_RENDER_DPI, min(MAX_RENDER_DPI, target))
    return target / PDF_POINT_DPI, target


def unread_regions(image: Image.Image, covered: Sequence[Box]) -> list[Box]:
    """Куски страницы с содержанием, которых не коснулся распознаватель строк.

    Страница уменьшается, бинаризуется и раскладывается на сетку; ячейки,
    попавшие внутрь рамок распознанных строк, гасятся, а из оставшихся связные
    группы собираются в прямоугольники. Всё, что осталось, — это выносные
    формулы, графики, схемы и печати: содержание, которое иначе пропадёт молча.

    Работает на чистом PIL, потому что модуль обязан быть доступен и там, где
    PaddleOCR не установлен: результат нужен и для пометки пропусков в режиме
    «Быстро», и для отправки вырезов в режиме «Облако».

    :param image: страница целиком.
    :param covered: рамки распознанных строк, нормализованные `0..1`.
    :return: нормализованные рамки непрочитанных областей сверху вниз.
    """
    preview = _preview(image)
    columns = max(1, preview.width // INK_CELL_PX)
    rows = max(1, preview.height // INK_CELL_PX)
    grid = _ink_grid(preview, columns, rows)
    _erase_covered(grid, covered, columns, rows)
    regions = [
        _region_box(cells, columns, rows) for cells in _components(grid, columns, rows)
    ]
    kept = [box for box in regions if _is_content(box)]
    return sorted(kept, key=lambda box: (box[1], box[0]))


def _is_content(box: Box) -> bool:
    """Область достаточно велика и не лежит целиком в поле страницы."""
    if (box[2] - box[0]) * (box[3] - box[1]) < MIN_REGION_AREA:
        return False
    return not (
        box[2] <= EDGE_MARGIN
        or box[0] >= 1 - EDGE_MARGIN
        or box[3] <= EDGE_MARGIN
        or box[1] >= 1 - EDGE_MARGIN
    )


def _preview(image: Image.Image) -> Image.Image:
    """Уменьшенная полутоновая копия: искать области по оригиналу незачем."""
    grey = image.convert("L")
    if grey.width <= INK_PREVIEW_WIDTH:
        return grey
    height = max(1, round(grey.height * INK_PREVIEW_WIDTH / grey.width))
    return grey.resize((INK_PREVIEW_WIDTH, height), Image.Resampling.BILINEAR)


def _ink_grid(preview: Image.Image, columns: int, rows: int) -> list[bool]:
    """Сетка «в ячейке есть содержание».

    Усреднение по ячейке делает сам PIL: `Image.Resampling.BOX` при уменьшении
    до размера сетки — это ровно среднее по прямоугольнику. Перебор пикселей на
    Python здесь стоил бы больше, чем всё остальное распознавание страницы.
    """
    cells = preview.resize((columns, rows), Image.Resampling.BOX)
    # `tobytes()` у полутонового изображения — это ровно по байту на ячейку.
    return [value < INK_CELL_LEVEL for value in cells.tobytes()]


def _erase_covered(grid: list[bool], covered: Sequence[Box], columns: int, rows: int) -> None:
    """Погасить ячейки под рамками распознанных строк — они уже прочитаны."""
    for x0, y0, x1, y1 in covered:
        left = max(0, int((x0 - COVER_PADDING) * columns))
        right = min(columns - 1, int((x1 + COVER_PADDING) * columns))
        top = max(0, int((y0 - COVER_PADDING) * rows))
        bottom = min(rows - 1, int((y1 + COVER_PADDING) * rows))
        for row in range(top, bottom + 1):
            for column in range(left, right + 1):
                grid[row * columns + column] = False


def _components(grid: list[bool], columns: int, rows: int) -> list[list[int]]:
    """Связные группы залитых ячеек. Обход в ширину по восьми соседям."""
    seen = [False] * len(grid)
    result: list[list[int]] = []
    for start in range(len(grid)):
        if not grid[start] or seen[start]:
            continue
        seen[start] = True
        queue = [start]
        group: list[int] = []
        while queue:
            cell = queue.pop()
            group.append(cell)
            row, column = divmod(cell, columns)
            for next_row in range(max(0, row - 1), min(rows, row + 2)):
                for next_column in range(max(0, column - 1), min(columns, column + 2)):
                    neighbour = next_row * columns + next_column
                    if grid[neighbour] and not seen[neighbour]:
                        seen[neighbour] = True
                        queue.append(neighbour)
        result.append(group)
    return result


def _region_box(cells: Sequence[int], columns: int, rows: int) -> Box:
    """Нормализованная рамка вокруг группы ячеек."""
    positions = [divmod(cell, columns) for cell in cells]
    top = min(row for row, _ in positions)
    bottom = max(row for row, _ in positions)
    left = min(column for _, column in positions)
    right = max(column for _, column in positions)
    return (left / columns, top / rows, (right + 1) / columns, (bottom + 1) / rows)
