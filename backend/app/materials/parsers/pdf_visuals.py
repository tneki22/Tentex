"""Видимые области PDF вместо списка ресурсов, из которых он нарисован.

Растр может быть подложкой, обрезанной фотографией или одним из наложений
рисунка. Текстовые контуры Type3 тоже не являются отдельными схемами.
Этот модуль задаёт общую геометрию для native, облака и оценки запуска;
содержимое области всегда берётся рендером оригинала, с масками и clipping.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf as fitz
from pypdf.errors import PdfReadError
from pypdf.generic import ContentStream, DecodedStreamObject

log = logging.getLogger("tentex.materials")

# Несколько полноценных строк прозы поверх растра означают текстовую подложку.
# Одна подпись или короткие названия узлов схемы этого сигнала не дают.
MIN_PROSE_WORDS = 4
MIN_OVERLAID_LINES = 3
# Наложения одного объекта почти полностью совпадают; одинаковые картинки
# в разных местах страницы остаются разными областями.
SAME_REGION_SHARE = 0.8
# Контурный текст занимает большую часть рамки своих строк. Рамки таблиц
# и стрелки с подписями не проходят эту проверку.
TEXT_PATH_COVERAGE = 0.5
MIN_GRAPHIC_SIDE = 24.0
MIN_GRAPHIC_WIDTH = 72.0
# Половина площади кластера должна быть уже объяснена растром. Малый значок
# внутри большой векторной схемы не делает всю схему прочитанной.
REPRESENTED_SHARE = 0.5
# Ограничение обхода рекурсивных Form XObject, как защита от циклических PDF.
MAX_FORM_DEPTH = 32


@dataclass(frozen=True, slots=True)
class RasterRegion:
    """Одна видимая область, независимо от числа вложенных растров."""

    rect: fitz.Rect
    xrefs: frozenset[int] = frozenset()
    digest: bytes = b""
    seqno: int = -1
    artifact: bool = False


def text_lines(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    """Строки без декодирования картинок; используются как опоры геометрии."""
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    return [
        (fitz.Rect(line["bbox"]), "".join(span["text"] for span in line["spans"]))
        for block in page.get_text("dict", flags=flags).get("blocks", [])
        for line in block.get("lines", [])
    ]


def is_backdrop(
    rect: fitz.Rect, lines: Sequence[tuple[fitz.Rect, str]],
    traces: Sequence[dict] = (), seqno: int = -1,
) -> bool:
    """Текстовая подложка определяется отношением к содержимому, а не размером листа.

Проверяем строки внутри самой области: фон может быть плиточным или занимать
лишь панель. Скан с тонким слоем не исключается — его содержимое ещё не прочитано.
    """
    return sum(
        len(text.split()) >= MIN_PROSE_WORDS and rect.contains(line)
        and (
            seqno < 0
            or any(trace["seqno"] > seqno and line.intersects(trace["bbox"]) for trace in traces)
        )
        for line, text in lines
    ) >= MIN_OVERLAID_LINES


def _same_region(first: fitz.Rect, second: fitz.Rect) -> bool:
    smaller = min(first.get_area(), second.get_area())
    larger = max(first.get_area(), second.get_area())
    return (
        smaller > 0
        and smaller >= SAME_REGION_SHARE * larger
        and (first & second).get_area() >= SAME_REGION_SHARE * smaller
    )


def _adjacent_tiles(first: RasterRegion, second: RasterRegion) -> bool:
    """Один ресурс может рисовать подложку плитками, вместо одного большого растра."""
    if not first.digest or first.digest != second.digest:
        return False
    a, b = first.rect, second.rect
    return (
        a.x0 == b.x0 and a.x1 == b.x1 and (a.y1 == b.y0 or b.y1 == a.y0)
    ) or (
        a.y0 == b.y0 and a.y1 == b.y1 and (a.x1 == b.x0 or b.x1 == a.x0)
    )


def _artifact_occurrences(page: fitz.Page) -> list[bool]:
    """Порядок изображений и их marked-content /Artifact, включая Form XObject.

Токены PDF разбирает pypdf: строка с буквами «/Artifact» внутри текста не
меняет семантику. Служебность относится к вхождению, а не к xref ресурса.
    """
    images = {(item[9], "/" + item[7]): item[0] for item in page.get_images(full=True)}
    forms = {(item[2], "/" + item[1]): item[0] for item in page.get_xobjects()}
    document = page.parent
    result: list[bool] = []

    def visit(data: bytes, parent: int, inherited: bool, ancestors: tuple[int, ...]) -> None:
        """Область marked content наследуется вызванной формой, но не соседями."""
        stream = DecodedStreamObject()
        stream.set_data(data)
        stack = [inherited]
        for operands, operator in ContentStream(stream, None).operations:
            if operator in {b"BMC", b"BDC"}:
                stack.append(stack[-1] or str(operands[0]) == "/Artifact")
            elif operator == b"EMC" and len(stack) > 1:
                stack.pop()
            elif operator == b"INLINE IMAGE":
                result.append(stack[-1])
            elif operator == b"Do":
                key = (parent, str(operands[0]))
                if key in images:
                    result.append(stack[-1])
                elif key in forms:
                    xref = forms[key]
                    if xref not in ancestors and len(ancestors) < MAX_FORM_DEPTH:
                        visit(document.xref_stream(xref), xref, stack[-1], (*ancestors, xref))

    try:
        data = b"\n".join(document.xref_stream(xref) for xref in page.get_contents())
        # Большинство PDF не размечены. Не разбираем их команды повторно.
        if b"/Artifact" not in data and not any(
            b"/Artifact" in document.xref_stream(xref) for xref in forms.values()
        ):
            return []
        visit(data, 0, False, ())
    except (PdfReadError, ValueError, RuntimeError) as error:
        log.warning("Не прочитаны PDF-артефакты страницы %s: %s", page.number + 1,
                    type(error).__name__)
        return []
    return result


def raster_regions(page: fitz.Page) -> list[RasterRegion]:
    """Применённые к странице растры, с обрезкой, без фона и наложенных дублей.

`get_image_info` отдаёт рамку до clipping. Рамки `get_text` уже учитывают
обрезку; исходные байты из этих блоков намеренно не используются как вырез.
    """
    lines = text_lines(page)
    infos = page.get_image_info(xrefs=True)
    blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT).get("blocks", [])
    result: list[RasterRegion] = []
    by_number = {info["number"]: info for info in infos}
    image_seqnos = [index for index, (kind, _) in enumerate(page.get_bboxlog())
                    if kind == "fill-image"]
    sequences = {info["number"]: seqno for info, seqno in zip(infos, image_seqnos, strict=False)}
    traces = page.get_texttrace()
    artifacts = _artifact_occurrences(page)
    tagged = (
        {info["number"]: flag for info, flag in zip(infos, artifacts, strict=True)}
        if len(artifacts) == len(infos) else {}
    )
    for block in blocks:
        if block.get("type") != 1:
            continue
        rect = fitz.Rect(block["bbox"]) & page.rect
        # Номер блока связывает ресурс с его собственным вхождением. Сравнение
        # только по перекрытию выбирало вместо картинки полный фон страницы.
        info = by_number.get(block["number"], {})
        xref = int(info.get("xref") or 0)
        region = RasterRegion(rect, frozenset({xref}) if xref else frozenset(),
                              info.get("digest", b""), sequences.get(block["number"], -1),
                              tagged.get(block["number"], False))
        if rect.is_empty:
            continue
        partners = [
            i for i, kept in enumerate(result)
            if _same_region(rect, kept.rect) or _adjacent_tiles(region, kept)
        ]
        if not partners:
            result.append(region)
            continue
        for index in reversed(partners):
            kept = result.pop(index)
            region = RasterRegion(region.rect | kept.rect, region.xrefs | kept.xrefs,
                                  region.digest, max(region.seqno, kept.seqno),
                                  region.artifact and kept.artifact)
        result.append(region)
    return [region for region in result
            if not is_backdrop(region.rect, lines, traces,
                               -1 if region.artifact else region.seqno)]


def content_drawings(page: fitz.Page) -> list[dict]:
    """Пути содержимого без подложек и копий уже прочитанного текста Type3."""
    lines = text_lines(page)
    traces = page.get_texttrace()
    result: list[dict] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"]) & page.rect
        area = rect.get_area()
        if not area or is_backdrop(rect, lines, traces, drawing["seqno"]):
            continue
        covered = sum((rect & line).get_area() for line, _ in lines)
        if covered >= TEXT_PATH_COVERAGE * area:
            continue
        result.append(drawing)
    return result


def has_unmapped_graphics(page: fitz.Page) -> bool:
    """Есть значимая векторная область, которой нет в тексте и растровых рисунках.

Это сигнал неполноты слоя, а не классификатор формул: адаптивный режим
передаёт такой лист целиком модели, которая различает схему, формулу и таблицу.
Мелкие значки и линейки не переключают маршрут страницы.
    """
    drawings = content_drawings(page)
    rasters = raster_regions(page)
    for rect in page.cluster_drawings(drawings=drawings) if drawings else []:
        if rect.width < MIN_GRAPHIC_WIDTH or rect.height < MIN_GRAPHIC_SIDE:
            continue
        if any((rect & region.rect).get_area() >= REPRESENTED_SHARE * rect.get_area()
               for region in rasters):
            continue
        return True
    return False
