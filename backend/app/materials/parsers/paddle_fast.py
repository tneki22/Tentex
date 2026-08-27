import re
from pathlib import Path
from typing import Any

from PIL import Image

from app.materials.parsers.base import ParsedElement, ParsedPage

NUMBERED_RE = re.compile(r"^\s*\d{1,3}[.)]\s*")
NUMBER_MARKER_RE = re.compile(r"(?<!\S)\d{1,3}[.)]\s*")
ENDS_SENTENCE_RE = re.compile(r"[.!?:;][\"»)\]]?$")
DEFAULT_LANGUAGE = "ru"
DEFAULT_OCR_VERSION = "PP-OCRv5"
DEFAULT_QUALITY_THRESHOLD = 0.75
_engine: Any = None
_engine_key: tuple[str, str] | None = None


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


def parse_image(
    path: Path,
    page_number: int,
    *,
    language: str = DEFAULT_LANGUAGE,
    ocr_version: str = DEFAULT_OCR_VERSION,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
) -> ParsedPage:
    width, height = Image.open(path).size
    results = list(_get_engine(language, ocr_version).predict(str(path)))
    if not results:
        return ParsedPage(page_number, width, height, "", "", "ocr_low", (), ("empty_ocr",), 0.0)
    data = _payload(results[0])
    texts = [str(text).strip() for text in data.get("rec_texts", [])]
    scores = [float(score) for score in data.get("rec_scores", [])]
    boxes = data.get("rec_boxes", [])
    lines: list[tuple[str, float, tuple[float, float, float, float]]] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        score = scores[index] if index < len(scores) else 0.0
        box = boxes[index] if index < len(boxes) else (0, 0, width, height)
        x0, y0, x1, y1 = (float(value) for value in box)
        lines.extend(
            split_numbered_line(
                text,
                score,
                (x0 / width, y0 / height, x1 / width, y1 / height),
            )
        )
    lines.sort(key=lambda item: (item[2][1], item[2][0]))

    # OCR returns visual lines. Keep real paragraph boundaries, but join a
    # wrapped line (including a numbered question) when geometry says it is a
    # continuation. A number is only a structural signal, never a heading by itself.
    merged: list[tuple[str, float, tuple[float, float, float, float]]] = []
    for text, score, bbox in lines:
        previous = merged[-1] if merged else None
        if previous is not None:
            previous, previous_score, previous_bbox = merged[-1]
            previous_height = max(0.0001, previous_bbox[3] - previous_bbox[1])
            gap = bbox[1] - previous_bbox[3]
            aligned = abs(bbox[0] - previous_bbox[0]) <= 0.08
            continuation = (
                not NUMBERED_RE.match(text)
                and aligned
                and gap <= previous_height * 0.9
                and (
                    NUMBERED_RE.match(previous) is not None
                    or ENDS_SENTENCE_RE.search(previous) is None
                )
            )
            if continuation:
                merged[-1] = (
                    f"{previous} {text}",
                    min(previous_score, score),
                    (
                        min(previous_bbox[0], bbox[0]),
                        min(previous_bbox[1], bbox[1]),
                        max(previous_bbox[2], bbox[2]),
                        max(previous_bbox[3], bbox[3]),
                    ),
                )
                continue
        merged.append((text, score, bbox))

    elements = tuple(
        ParsedElement(
            "list" if NUMBERED_RE.match(text) else "paragraph",
            text,
            bbox,
            1 if NUMBERED_RE.match(text) else None,
            score,
            recognition_source="ocr",
        )
        for text, score, bbox in merged
    )
    confidence = sum(score for _, score, _ in merged) / len(merged) if merged else 0.0
    quality = "ocr" if confidence >= quality_threshold else "ocr_low"
    diagnostics = ("low_confidence",) if quality == "ocr_low" else ()
    plain_text = "\n".join(element.text for element in elements)
    markdown = "\n\n".join(
        element.text for element in elements
    )
    return ParsedPage(
        page_number,
        width,
        height,
        markdown,
        plain_text,
        quality,
        elements,
        diagnostics,
        confidence,
    )
