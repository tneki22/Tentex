"""Режим «Быстро»: распознавание страницы построчно локальным PP-OCRv5.

Движок отдаёт строки, а страницу из них надо собрать самим: расставить в
порядке чтения (`reading_order`), склеить перенесённые строки в абзацы и
отметить то, что распознаватель строк не увидел вовсе, — выносные формулы и
графики. Формулы в этом режиме не читаются: они сохраняются вырезом с
координатами, чтобы не исчезать из материала молча и чтобы режим «Облако» мог
дочитать их потом, не пересобирая страницу.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.materials.parsers import raster, reading_order
from app.materials.parsers.base import IMAGE_PLACEHOLDER, ParsedElement, ParsedPage
from app.materials.storage import store_material_asset

log = logging.getLogger("tentex.worker")

NUMBERED_RE = re.compile(r"^\s*\d{1,3}[.)]\s*")
NUMBER_MARKER_RE = re.compile(r"(?<!\S)\d{1,3}[.)]\s*")
ENDS_SENTENCE_RE = re.compile(r"[.!?:;][\"»)\]]?$")
DEFAULT_LANGUAGE = "ru"
DEFAULT_OCR_VERSION = "PP-OCRv5"
DEFAULT_QUALITY_THRESHOLD = 0.75

# Строка считается продолжением предыдущей, если её левый край совпадает с
# точностью до этой доли ширины страницы.
ALIGN_TOLERANCE = 0.08
# И если вертикальный зазор укладывается в такую долю высоты предыдущей строки.
# Нижняя граница отрицательная: у плотного набора соседние рамки перекрываются,
# а вот сильный «подъём» означает переход в следующую колонку — там склейки нет.
MAX_WRAP_GAP_RATIO = 0.9
MIN_WRAP_GAP_RATIO = -0.3

_engine: Any = None
_engine_key: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class _Line:
    """Одна распознанная строка: текст, уверенность и рамка в пикселях."""

    text: str
    score: float
    bbox: tuple[float, float, float, float]


def available() -> bool:
    try:
        import paddleocr  # noqa: F401
    except ImportError:
        return False
    return True


def _get_engine(language: str = DEFAULT_LANGUAGE, ocr_version: str = DEFAULT_OCR_VERSION) -> Any:
    global _engine, _engine_key
    key = (language, ocr_version)
    if _engine is None or _engine_key != key:
        from paddleocr import PaddleOCR

        _engine = PaddleOCR(
            lang=language,
            ocr_version=ocr_version,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        _engine_key = key
    return _engine


def _payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result.get("res", result)
    try:
        data = dict(result)
    except (TypeError, ValueError) as error:
        raise RuntimeError("PaddleOCR returned an unsupported result") from error
    return data.get("res", data)


def split_numbered_line(
    text: str,
    score: float,
    bbox: tuple[float, float, float, float],
) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """Разрезать строку, в которую слиплись два нумерованных пункта.

    Детектор часто ловит «12. Вопрос 13. Вопрос» одной строкой, когда пункты
    стоят в одну линию. Рамка делится пропорционально длине текста: точных
    координат у половинок нет, но порядок и принадлежность странице сохраняются.
    """
    markers = list(NUMBER_MARKER_RE.finditer(text))
    if len(markers) < 2:
        return [(text, score, bbox)]
    x0, y0, x1, y1 = bbox
    width = x1 - x0
    result: list[tuple[str, float, tuple[float, float, float, float]]] = []
    for index, marker in enumerate(markers):
        start = marker.start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        part = text[start:end].strip()
        if not part:
            continue
        part_x0 = x0 + width * start / max(1, len(text))
        part_x1 = x0 + width * end / max(1, len(text))
        result.append((part, score, (part_x0, y0, part_x1, y1)))
    return result


def _detected_lines(data: dict[str, Any], width: int, height: int) -> list[_Line]:
    """Строки из ответа PaddleOCR, с разрезанием слипшихся нумерованных пунктов."""
    texts = [str(text).strip() for text in data.get("rec_texts", [])]
    scores = [float(score) for score in data.get("rec_scores", [])]
    boxes = data.get("rec_boxes", [])
    lines: list[_Line] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        score = scores[index] if index < len(scores) else 0.0
        box = boxes[index] if index < len(boxes) else (0, 0, width, height)
        bbox = tuple(float(value) for value in box)
        lines.extend(
            _Line(part, part_score, part_box)
            for part, part_score, part_box in split_numbered_line(text, score, bbox)  # type: ignore[arg-type]
        )
    return lines


def _ordered(lines: list[_Line], width: int, height: int) -> tuple[list[_Line], float]:
    """Расставить строки в порядке чтения с поправкой на наклон скана.

    Наклон снимается только на время сортировки: рамки, которые уедут в базу,
    должны совпадать с картинкой, по которой пользователь ищет фрагмент глазами.
    """
    if not lines:
        return [], 0.0
    boxes = [line.bbox for line in lines]
    angle = reading_order.skew_angle(_quads(lines))
    keys = reading_order.correct_skew(boxes, angle, width, height)
    return [lines[index] for index in reading_order.reading_order(keys)], angle


def _quads(lines: list[_Line]) -> list[list[tuple[float, float]]]:
    """Верхнее ребро каждой рамки — этого достаточно для оценки наклона."""
    return [[(line.bbox[0], line.bbox[1]), (line.bbox[2], line.bbox[1])] for line in lines]


def _continues(previous: _Line, line: _Line) -> bool:
    """Продолжает ли строка предыдущую в пределах одной колонки.

    Номер в начале строки — структурный признак: он открывает новый пункт, а не
    продолжает старый. Всё остальное решает геометрия.
    """
    if NUMBERED_RE.match(line.text):
        return False
    previous_height = max(0.0001, previous.bbox[3] - previous.bbox[1])
    gap = (line.bbox[1] - previous.bbox[3]) / previous_height
    if not MIN_WRAP_GAP_RATIO <= gap <= MAX_WRAP_GAP_RATIO:
        return False
    if abs(line.bbox[0] - previous.bbox[0]) > ALIGN_TOLERANCE:
        return False
    return NUMBERED_RE.match(previous.text) is not None or not ENDS_SENTENCE_RE.search(
        previous.text
    )


def _merge_wrapped(lines: list[_Line]) -> list[_Line]:
    """Склеить перенесённые строки обратно в абзацы и пункты списка."""
    merged: list[_Line] = []
    for line in lines:
        previous = merged[-1] if merged else None
        if previous is not None and _continues(previous, line):
            merged[-1] = _Line(
                f"{previous.text} {line.text}",
                min(previous.score, line.score),
                (
                    min(previous.bbox[0], line.bbox[0]),
                    min(previous.bbox[1], line.bbox[1]),
                    max(previous.bbox[2], line.bbox[2]),
                    max(previous.bbox[3], line.bbox[3]),
                ),
            )
            continue
        merged.append(line)
    return merged


def _unread_elements(
    image: Image.Image,
    covered: list[raster.Box],
    page_number: int,
    owner: str,
) -> tuple[ParsedElement, ...]:
    """Вырезать то, что распознаватель строк пропустил, и сохранить картинками.

    Вид области не угадывается. Отличить выносную формулу от графика по одним
    пропорциям нельзя — на прогоне бенчмарка такая догадка уверенно записывала
    в формулы колонтитул, — а неверная подпись хуже честного «[Изображение]».
    Вид определит либо режим «Облако», либо пользователь глазами.

    Без владельца (материала, которому принадлежит страница) вырез сохранять
    некуда, поэтому области всё равно отмечаются — но без файла: пользователь
    увидит, что здесь что-то было, и сможет открыть оригинал.
    """
    elements: list[ParsedElement] = []
    for index, box in enumerate(raster.unread_regions(image, covered)):
        asset_path = None
        if owner:
            crop = image.crop(
                (
                    int(box[0] * image.width),
                    int(box[1] * image.height),
                    int(box[2] * image.width),
                    int(box[3] * image.height),
                )
            )
            asset_path = _store_crop(crop, owner, page_number, index)
        elements.append(
            ParsedElement(
                "image",
                IMAGE_PLACEHOLDER,
                box,
                asset_path=asset_path,
                recognition_source="ocr",
            )
        )
    return tuple(elements)


def _store_crop(crop: Image.Image, owner: str, page_number: int, index: int) -> str | None:
    """Сохранить вырез области в хранилище материала."""
    from io import BytesIO

    buffer = BytesIO()
    crop.save(buffer, format="PNG")
    try:
        return store_material_asset(owner, f"p{page_number}-region{index}.png", buffer.getvalue())
    except OSError as error:
        log.warning("не удалось сохранить вырез области page=%s: %s", page_number, error)
        return None


def _markdown(elements: tuple[ParsedElement, ...]) -> str:
    lines: list[str] = []
    for element in elements:
        if element.kind in {"image", "formula"} and element.asset_path:
            lines.append(f"![{element.text}]({element.asset_path})")
        else:
            lines.append(element.text)
    return "\n\n".join(lines)


def parse_image(
    path: Path,
    page_number: int,
    *,
    language: str = DEFAULT_LANGUAGE,
    ocr_version: str = DEFAULT_OCR_VERSION,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    owner: str = "",
) -> ParsedPage:
    """Распознать одну картинку страницы режимом «Быстро».

    :param owner: материал, которому принадлежит страница; нужен, чтобы
        сохранить вырезы непрочитанных областей рядом с остальными файлами.
    """
    image = Image.open(path)
    width, height = image.size
    results = list(_get_engine(language, ocr_version).predict(str(path)))
    if not results:
        return ParsedPage(page_number, width, height, "", "", "ocr_low", (), ("empty_ocr",), 0.0)
    data = _payload(results[0])
    ordered, angle = _ordered(_detected_lines(data, width, height), width, height)
    merged = _merge_wrapped(ordered)

    text_elements = tuple(
        ParsedElement(
            "list" if NUMBERED_RE.match(line.text) else "paragraph",
            line.text,
            _normalized(line.bbox, width, height),
            1 if NUMBERED_RE.match(line.text) else None,
            line.score,
            recognition_source="ocr",
        )
        for line in merged
    )
    unread = _unread_elements(
        image, [element.bbox for element in text_elements], page_number, owner
    )
    elements = _in_reading_order((*text_elements, *unread)) if unread else text_elements

    confidence = sum(line.score for line in merged) / len(merged) if merged else 0.0
    quality = "ocr" if confidence >= quality_threshold else "ocr_low"
    diagnostics = ["low_confidence"] if quality == "ocr_low" else []
    if angle:
        diagnostics.append(f"skew:{angle:.1f}")
    if unread:
        diagnostics.append(f"unread_regions:{len(unread)}")
    plain_text = "\n".join(
        element.text for element in elements if element.kind not in {"image", "formula"}
    )
    return ParsedPage(
        page_number,
        width,
        height,
        _markdown(elements),
        plain_text,
        quality,
        elements,
        tuple(diagnostics),
        confidence,
    )


def _normalized(
    bbox: tuple[float, float, float, float], width: int, height: int
) -> tuple[float, float, float, float]:
    return (bbox[0] / width, bbox[1] / height, bbox[2] / width, bbox[3] / height)


def _in_reading_order(elements: tuple[ParsedElement, ...]) -> tuple[ParsedElement, ...]:
    """Вернуть элементы в порядке чтения. Вырезы встают между абзацами, а не в конец."""
    order = reading_order.reading_order([element.bbox for element in elements])
    return tuple(elements[index] for index in order)
