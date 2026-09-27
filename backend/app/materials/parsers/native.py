import logging
import re
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import reduce
from io import BytesIO
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile
from typing import Literal

import pymupdf as fitz
from docx import Document
from docx.text.paragraph import Paragraph
from PIL import Image

from app.materials.image_candidates import TINY_SIDE_PX, XREF_REPEATED, auto_send, classify
from app.materials.image_meta import (
    crop_hash,
    element_meta,
    find_caption,
    needs_description,
    neighbor_context,
    pixel_size,
    with_description,
)
from app.materials.parsers import (
    docx_content,
    formula_zones,
    inline_formulas,
    paddle_fast,
    page_geometry,
    raster,
    reading_order,
)
from app.materials.parsers.audio import parse_audio
from app.materials.parsers.base import (
    IMAGE_PLACEHOLDER,
    ElementKind,
    ImageMeta,
    ImageProvenance,
    ImageRequest,
    PageImage,
    PageRecognizer,
    ParsedElement,
    ParsedPage,
    RecognitionSource,
    RegionRequest,
)
from app.materials.parsers.cloud_vlm import (
    IMAGE_PROMPT_VERSION,
    TABLE_SEPARATOR_RE,
)
from app.materials.parsers.pdf_layout import parse_layout_page
from app.materials.parsers.text_layer import TextLayerDiagnosis, diagnose
from app.materials.storage import material_path, store_material_asset
from app.models import ParserMode
from app.ocr.engines import DEFAULT_QUALITY_THRESHOLD, OcrRuntimeParams

NUMBERED_RE = re.compile(r"^\s*\d{1,3}[.)]\s+")
BULLET_RE = re.compile(r"^\s*[•▪◦‣·*+\-–—]\s+")
ORDERED_RE = re.compile(r"^\s*(?:\d{1,3}|[a-zа-я])[.)]\s+")
# Заголовок из одной строки: длиннее — это уже пункт списка, а не название вопроса.
HEADING_MAX_CHARS = 120
# Шаг отступа одного уровня вложенности, в пунктах PDF.
INDENT_STEP = 18
MAX_LIST_LEVEL = 4
# Насколько строка может не дотянуть до правого края и всё ещё считаться перенесённой.
WRAP_TOLERANCE = 60
ENDS_SENTENCE_RE = re.compile(r"[.!?:;][\"»)\]]?$")
# Кегль заголовка относительно основного текста.
HEADING_SIZE_RATIO = 1.15
# Меньше — линейки, точки и обрезки рамок. Маленький логотип и маленькая
# формула проходят: их различает отбор кандидатов по повтору, месту и подписи,
# а не размер (`image_candidates`).
MIN_IMAGE_SIDE = 8
# Растр высотой в строку текста — формула или слово, вставленные картинкой
# (методички, где LaTeX сохранён в PNG: 29 таких растров на странице). Порог
# 40pt раньше молча выбрасывал их вместе с формулами, а описание каждого как
# схемы стоило бы два десятка платных вызовов на страницу. Такой растр —
# формула: «Облако» читает их пачкой вырезов, «Быстро» хранит вырезом.
INLINE_RASTER_MAX_PT = 24
# Строчный растр уже порога выше — однобуквенная формула («k» в 7,7pt): его
# пропускает не ширина, а размер в пикселях (крошку всё равно отсеет `TINY_SIDE_PX`).
MIN_INLINE_WIDTH = 4
# Выносная формула картинкой: низкая и вытянутая, без подписи «Рис.». Её сначала
# читают вырезом формулы в общей пачке, и только если модель скажет «рисунок»,
# она уходит на отдельное (и в разы более дорогое) описание.
DISPLAY_FORMULA_MAX_PT = 60
DISPLAY_FORMULA_MIN_ASPECT = 3.0
# Качество JPEG страницы для модели: ниже на мелком кегле скана появляются
# ореолы вокруг букв, выше файл растёт без пользы для чтения.
MODEL_JPEG_QUALITY = 90
# Длинная сторона выреза, уходящего на описание. Больше — лишние плитки и
# деньги без новой информации для описания схемы.
DESCRIBE_MAX_SIDE_PX = 1536
# Форматы, которые провайдеры принимают как есть; остальное перекодируется в PNG.
SENDABLE_MEDIA = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
# Виды элементов, у которых оригинальная вырезка со страницы полезна сама по
# себе: распознанному тексту формулы или схемы верить нельзя, и просмотрщик
# показывает рядом исходник.
CROPPED_KINDS = {"image", "formula", "table"}

log = logging.getLogger("tentex.worker")


def extract_outline(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() != ".pdf":
        return []
    with fitz.open(path) as document:
        return [
            {"level": level, "title": title.strip(), "page": page}
            for level, title, page, *_ in document.get_toc(simple=False)
            if title.strip() and page > 0
        ]


def inspect(path: Path) -> tuple[int, int, int, list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            document = fitz.open(path)
        except Exception as error:
            raise ValueError("PDF повреждён или не читается") from error
        if document.needs_pass:
            raise PermissionError("PDF защищён паролем")
        scan_pages = sum(not page.get_text("text").strip() for page in document)
        return len(document), scan_pages, max(1, len(document) - scan_pages + scan_pages * 3), []
    if suffix in {".jpg", ".jpeg", ".png"}:
        with Image.open(path) as image:
            image.verify()
        return 1, 1, 3, []
    if suffix == ".docx":
        Document(path)
        return 1, 0, 1, []
    if suffix in {".txt", ".md"}:
        path.read_text(encoding="utf-8-sig")
        return 1, 0, 1, []
    if suffix in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}:
        return 1, 0, 60, ["audio_transcription_required"]
    raise ValueError("Неподдерживаемый формат")


def _normalized_bbox(
    bbox: tuple[float, float, float, float], width: float, height: float
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (max(0, x0 / width), max(0, y0 / height), min(1, x1 / width), min(1, y1 / height))


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float


def _block_lines(block: dict) -> list[_Line]:
    lines: list[_Line] = []
    for line in block.get("lines", []):
        spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
        if not spans:
            continue
        text = "".join(
            formula_zones.readable(str(span["text"]), str(span.get("font", ""))) for span in spans
        ).strip()
        if not text:
            continue
        x0, top, x1, bottom = line["bbox"]
        lines.append(
            _Line(text, x0, x1, top, bottom, max(float(s.get("size", 0)) for s in spans))
        )
    return lines


def _join_wrapped(previous: str, addition: str) -> str:
    """Строки PDF — это перенос, а не конец абзаца. Слово, разорванное дефисом, склеивается."""
    if previous.endswith("-") and addition[:1].islower():
        return previous[:-1] + addition
    return f"{previous} {addition}"


def _continues(previous: _Line, line: _Line, wrap_threshold: float, heading_size: float) -> bool:
    """Продолжает ли строка предыдущую.

    Одной геометрии мало: текст не выключен по формату, и правый край гуляет на
    полсотни пунктов. Одной пунктуации тоже мало: «…(INSERT, UPDATE, DELETE — при»
    обязана склеиться со следующей строкой. Поэтому три признака вместе.
    """
    if BULLET_RE.match(line.text) or ORDERED_RE.match(line.text):
        return False
    if previous.size >= heading_size and line.size >= heading_size:
        return True  # многострочный заголовок: «Вопрос 21» и его название
    if ENDS_SENTENCE_RE.search(previous.text):
        return False
    return previous.x1 >= wrap_threshold


def _group_lines(lines: list[_Line], heading_size: float) -> list[list[_Line]]:
    if not lines:
        return []
    wrap_threshold = max(line.x1 for line in lines) - WRAP_TOLERANCE
    groups: list[list[_Line]] = [[lines[0]]]
    for previous, line in zip(lines, lines[1:], strict=False):
        if _continues(previous, line, wrap_threshold, heading_size):
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def _indent_level(x0: float, base_x0: float) -> int:
    return 1 + min(MAX_LIST_LEVEL - 1, max(0, int((x0 - base_x0) / INDENT_STEP)))


def _classify(
    text: str, group: list[_Line], body_size: float, base_x0: float
) -> tuple[ElementKind, int | None]:
    max_size = max(line.size for line in group)
    bullet = BULLET_RE.match(text) is not None
    if not bullet:
        big = max_size >= body_size * HEADING_SIZE_RATIO
        short_numbered = (
            NUMBERED_RE.match(text) is not None
            and len(group) == 1
            and len(text) <= HEADING_MAX_CHARS
        )
        if big or short_numbered:
            return "heading", max(1, round(body_size * 2 / max_size))
    if bullet or ORDERED_RE.match(text) is not None:
        return "list", _indent_level(min(line.x0 for line in group), base_x0)
    return "paragraph", None


def _ocr_raster(
    data: bytes, extension: str, page_number: int, params: OcrRuntimeParams
) -> tuple[str, float | None] | None:
    """Надписи внутри картинки локальным OCR; `None` — прочитать нечего или нечем."""
    if not paddle_fast.available():
        return None
    with NamedTemporaryFile(suffix=f".{extension}", delete=False) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    try:
        recognized = paddle_fast.parse_image(
            temporary_path,
            page_number,
            language=params.fast_language,
            ocr_version=params.fast_model_id,
            quality_threshold=params.quality_threshold,
        )
    except (OSError, RuntimeError, ValueError) as error:
        # Исходный вырез остаётся полезным, даже если OCR этой области не
        # справился, — но молчать об этом нельзя: иначе пропажа текста
        # картинки выглядит как «так и было».
        log.warning("OCR картинки не удался page=%s: %s", page_number, error)
        return None
    finally:
        temporary_path.unlink(missing_ok=True)
    text = recognized.plain_text.strip()
    return (text, recognized.confidence) if text else None


def _text_only_meta(meta: ImageMeta, text: str | None, confidence: float | None,
                    threshold: float) -> ImageMeta:
    """Состояние после «только текст»: надписи прочитаны, пусты или сомнительны."""
    if text is None:
        return replace(meta, processing="text_only", reasons=(*meta.reasons, "no_text"))
    if confidence is not None and confidence < threshold:
        return replace(
            meta,
            processing="text_only",
            review="needs_review",
            reasons=(*meta.reasons, "ocr_low_confidence"),
        )
    return replace(meta, processing="text_only")


def _image_xref(bbox: Sequence[float], boxes: Sequence[tuple[fitz.Rect, int]]) -> int | None:
    """xref встроенного растра по его рамке на странице."""
    rect = fitz.Rect(bbox)
    best, best_overlap = None, 0.0
    for box, xref in boxes:
        overlap = (rect & box).get_area() / max(1e-6, rect.get_area())
        if overlap > best_overlap:
            best, best_overlap = xref, overlap
    return best if best_overlap >= 0.8 else None


def _image_element(
    block: dict,
    page: fitz.Page,
    page_number: int,
    owner: str,
    index: int,
    *,
    run_ocr: bool = False,
    params: OcrRuntimeParams | None = None,
    repeated: bool = False,
) -> ParsedElement | None:
    """Фотография или схема со страницы вместе с состоянием изображения.

    :param repeated: тот же растр (xref) стоит на нескольких страницах —
        вероятный логотип или колонтитул; его не распознают и не описывают сами.
    """
    data = block.get("image")
    if not data:
        return None
    params = params or OcrRuntimeParams()
    x0, top, x1, bottom = block["bbox"]
    size = pixel_size(data)
    if size is None and block.get("width") and block.get("height"):
        size = (int(block["width"]), int(block["height"]))
    # Крошка в пару пикселей — значок или точка, а не формула: её решает отбор
    # кандидатов (`tiny` → украшение).
    crumb = size is not None and min(size) < TINY_SIDE_PX
    inline = (bottom - top) <= INLINE_RASTER_MAX_PT and not crumb
    min_width = MIN_INLINE_WIDTH if inline else MIN_IMAGE_SIDE
    if (x1 - x0) < min_width or (bottom - top) < MIN_IMAGE_SIDE:
        return None
    extension = str(block.get("ext") or "png").lower()
    asset_path = store_material_asset(owner, f"p{page_number}-{index}.{extension}", data)
    bbox = _normalized_bbox((x0, top, x1, bottom), page.rect.width, page.rect.height)
    if inline:
        return ParsedElement(
            "formula", IMAGE_PLACEHOLDER, bbox, asset_path=asset_path, recognition_source="native"
        )
    meta = ImageMeta(
        signals=(XREF_REPEATED,) if repeated else (),
        detection="embedded",
        crop_hash=crop_hash(data),
        pixel_size=size,
    )
    text = IMAGE_PLACEHOLDER
    confidence = None
    recognition_source: RecognitionSource = "native"
    if run_ocr and not repeated:
        recognized = _ocr_raster(data, extension, page_number, params)
        if recognized is not None:
            text, confidence = recognized
            recognition_source = "ocr"
        meta = _text_only_meta(
            meta, recognized[0] if recognized else None, confidence, params.quality_threshold
        )
    return ParsedElement(
        "image",
        text,
        bbox,
        None,
        confidence,
        asset_path=asset_path,
        recognition_source=recognition_source,
        image=meta,
    )


def _native_pdf_page(
    page: fitz.Page,
    page_number: int,
    owner: str = "",
    *,
    ocr_images: bool = False,
    params: OcrRuntimeParams | None = None,
    repeated_xrefs: frozenset[int] = frozenset(),
) -> ParsedPage:
    raw = page.get_text("dict", sort=True)
    blocks = raw.get("blocks", [])
    xref_boxes = _xref_boxes(page) if repeated_xrefs else []
    text_blocks = [block for block in blocks if block.get("type") == 0]
    all_lines = [line for block in text_blocks for line in _block_lines(block)]
    if not all_lines:
        return ParsedPage(page_number, page.rect.width, page.rect.height, "", "", "native", ())
    body_size = median([line.size for line in all_lines])
    base_x0 = min(line.x0 for line in all_lines)
    heading_size = body_size * HEADING_SIZE_RATIO

    elements: list[ParsedElement] = []
    for index, block in enumerate(blocks):
        if block.get("type") == 1:
            if owner:
                image = _image_element(
                    block,
                    page,
                    page_number,
                    owner,
                    index,
                    run_ocr=ocr_images,
                    params=params,
                    repeated=_image_xref(block["bbox"], xref_boxes) in repeated_xrefs,
                )
                if image is not None:
                    elements.append(image)
            continue
        for group in _group_lines(_block_lines(block), heading_size):
            text = reduce(_join_wrapped, (line.text for line in group))
            if not text.strip():
                continue
            kind, level = _classify(text, group, body_size, base_x0)
            bbox = (
                min(line.x0 for line in group),
                min(line.top for line in group),
                max(line.x1 for line in group),
                max(line.bottom for line in group),
            )
            elements.append(
                ParsedElement(
                    kind,
                    text,
                    _normalized_bbox(bbox, page.rect.width, page.rect.height),
                    level,
                )
            )

    # Картинка в plain-тексте была бы шумом: она попадает и в поиск, и в эталон.
    plain = "\n".join(element.text for element in elements if element.kind != "image")
    markdown = _markdown(elements)
    diagnostics = ("formula_possible",) if re.search(r"[∑∫√≈≤≥]", plain) else ()
    return ParsedPage(
        page_number,
        page.rect.width,
        page.rect.height,
        markdown,
        plain,
        "native",
        tuple(elements),
        diagnostics,
    )


def _xref_boxes(page: fitz.Page) -> list[tuple[fitz.Rect, int]]:
    try:
        return [
            (fitz.Rect(info["bbox"]), int(info["xref"]))
            for info in page.get_image_info(xrefs=True)
            if info.get("xref")
        ]
    except (RuntimeError, ValueError):
        return []


def repeated_image_xrefs(document: fitz.Document) -> frozenset[int]:
    """Растры, стоящие на нескольких страницах: логотипы, колонтитулы, фон.

    Читает только словари ресурсов страниц, без извлечения картинок, поэтому
    годится и для книги в тысячу страниц. Повтор — сигнал для отбора, а не
    решение: подпись рядом всё равно делает изображение содержательным.
    """
    counts: Counter[int] = Counter()
    for page in document:
        try:
            counts.update({int(item[0]) for item in page.get_images(full=False)})
        except (RuntimeError, ValueError):
            continue
    return frozenset(xref for xref, pages in counts.items() if pages >= 2)


def text_layer_pages(path: Path, owner: str = "") -> Iterator[ParsedPage]:
    """Страницы PDF, у которого текстовый слой заведомо полный и точный.

    Так читается PDF, который Tentex собрал сам (Typst): распознавать в нём
    нечего, а разметчик стоит времени и модели. Разбор всё равно идёт через
    общий `_native_pdf_page`, поэтому заголовки, списки и вырезы иллюстраций
    получаются те же, что у обычного PDF, — а значит работают и блоки, и
    привязки, и автопривязка ответов.
    """
    with fitz.open(path) as document:
        for index, page in enumerate(document):
            yield _native_pdf_page(page, index + 1, owner, ocr_images=False)


def _bbox_overlap(
    inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]
) -> float:
    x0 = max(inner[0], outer[0])
    y0 = max(inner[1], outer[1])
    x1 = min(inner[2], outer[2])
    y1 = min(inner[3], outer[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = max(0.000001, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return intersection / area


def _normalized_text(text: str) -> str:
    return re.sub(r"[^0-9a-zа-я]+", "", text.casefold())


def _merge_native_and_images(
    native: tuple[ParsedElement, ...], images: tuple[ParsedElement, ...]
) -> tuple[ParsedElement, ...]:
    """Merge layout regions and raster regions, preferring a native text layer."""
    merged_images: list[ParsedElement] = []
    native_text = [item for item in native if item.kind != "image" and item.text.strip()]
    for image in images:
        if image.recognition_source != "ocr":
            merged_images.append(image)
            continue
        covered = " ".join(
            item.text for item in native_text if _bbox_overlap(item.bbox, image.bbox) >= 0.7
        )
        left = _normalized_text(covered)
        right = _normalized_text(image.text)
        duplicate = bool(left and right) and (
            left in right
            or right in left
            or SequenceMatcher(None, left, right).ratio() >= 0.72
        )
        merged_images.append(
            replace(
                image,
                text=IMAGE_PLACEHOLDER,
                confidence=None,
                recognition_source="native",
            )
            if duplicate
            else image
        )
    return _in_reading_order((*native, *merged_images))


def _in_reading_order(elements: tuple[ParsedElement, ...]) -> tuple[ParsedElement, ...]:
    """Расставить элементы страницы в порядке чтения.

    Сортировка «сверху вниз, слева направо» здесь была бы ошибкой: на статье в
    две колонки она перемешивает колонки, ради чего и заведён `reading_order`.
    """
    order = reading_order.reading_order([element.bbox for element in elements])
    return tuple(elements[index] for index in order)


def _page_quality(
    elements: tuple[ParsedElement, ...],
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
) -> tuple[str, float | None]:
    # Описание изображения проверяется по своей оси (`ImageMeta.review`): его
    # сомнительность не делает сомнительным текст страницы.
    recognized = [
        item
        for item in elements
        if item.recognition_source in {"ocr", "vl"}
        and item.text.strip()
        and not (item.image is not None and item.image.processing == "described")
    ]
    if not recognized:
        return "native", None
    scores = [item.confidence for item in recognized if item.confidence is not None]
    confidence = min(scores) if scores else None
    quality = "ocr_low" if confidence is not None and confidence < quality_threshold else "ocr"
    return quality, confidence


def _markdown(elements: list[ParsedElement]) -> str:
    """Разметка сохраняет уровни: заголовки решётками, пункты списка — отступом."""
    lines: list[str] = []
    for element in elements:
        if element.kind == "heading":
            lines.append(f"{'#' * (element.level or 2)} {element.text}")
        elif element.kind == "list":
            lines.append(f"{'    ' * ((element.level or 1) - 1)}{element.text}")
        elif element.kind == "image":
            lines.append(f"![Изображение]({element.asset_path or ''})")
        else:
            lines.append(element.text)
    return "\n\n".join(lines)


def parse_text_page(
    text: str,
    page_number: int = 1,
    recognition_source: RecognitionSource = "native",
) -> ParsedPage:
    elements: list[ParsedElement] = []
    raw_lines = [line for line in text.splitlines() if line.strip()]
    for index, raw in enumerate(raw_lines):
        line = raw.strip()
        markdown_heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        kind: ElementKind
        if markdown_heading:
            kind, content, level = (
                "heading",
                markdown_heading.group(2),
                len(markdown_heading.group(1)),
            )
        elif BULLET_RE.match(line):
            # Отступ в исходнике — это и есть уровень вложенности.
            indent = len(raw) - len(raw.lstrip())
            kind, content, level = "list", line, 1 + min(MAX_LIST_LEVEL - 1, indent // 2)
        elif NUMBERED_RE.match(line) and len(line) <= HEADING_MAX_CHARS:
            kind, content, level = "heading", line, 1
        elif ORDERED_RE.match(line):
            indent = len(raw) - len(raw.lstrip())
            kind, content, level = "list", line, 1 + min(MAX_LIST_LEVEL - 1, indent // 2)
        else:
            kind, content, level = "paragraph", line, None
        top = index / max(1, len(raw_lines))
        bottom = (index + 1) / max(1, len(raw_lines))
        elements.append(
            ParsedElement(
                kind,
                content,
                (0, top, 1, bottom),
                level,
                recognition_source=recognition_source,
            )
        )
    plain = "\n".join(element.text for element in elements)
    return ParsedPage(page_number, 1, 1, _markdown(elements), plain, "native", tuple(elements))


def _text_page(path: Path) -> ParsedPage:
    return parse_text_page(path.read_text(encoding="utf-8-sig"))


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
BULLET_FORMATS = {"bullet", "none"}
LETTER_FORMATS = {
    "lowerLetter": "абвгдежзиклмнопрстуфхцчшщэюя",
    "upperLetter": "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ",
}


def _docx_numbering(document: Document) -> dict[tuple[int, int], tuple[str, str]]:
    """(numId, ilvl) → (формат, шаблон) из numbering.xml.

    Word держит номера пунктов не в тексте абзаца, а в отдельной части документа.
    Без этой карты нумерованный список приезжает без номеров — а в списке
    вопросов номер и есть половина смысла.
    """
    try:
        element = document.part.numbering_part.element
    except (KeyError, AttributeError, NotImplementedError):
        return {}

    abstract: dict[str, dict[int, tuple[str, str]]] = {}
    for node in element.findall(f"{W_NS}abstractNum"):
        levels: dict[int, tuple[str, str]] = {}
        for level in node.findall(f"{W_NS}lvl"):
            fmt = level.find(f"{W_NS}numFmt")
            template = level.find(f"{W_NS}lvlText")
            levels[int(level.get(f"{W_NS}ilvl", "0"))] = (
                fmt.get(f"{W_NS}val", "decimal") if fmt is not None else "decimal",
                template.get(f"{W_NS}val", "%1.") if template is not None else "%1.",
            )
        abstract[node.get(f"{W_NS}abstractNumId", "")] = levels

    mapping: dict[tuple[int, int], tuple[str, str]] = {}
    for node in element.findall(f"{W_NS}num"):
        reference = node.find(f"{W_NS}abstractNumId")
        levels = abstract.get(reference.get(f"{W_NS}val", "")) if reference is not None else None
        if not levels:
            continue
        num_id = int(node.get(f"{W_NS}numId", "0"))
        for ilvl, spec in levels.items():
            mapping[(num_id, ilvl)] = spec
    return mapping


def _numeral(value: int, fmt: str) -> str:
    alphabet = LETTER_FORMATS.get(fmt)
    if alphabet:
        return alphabet[(value - 1) % len(alphabet)]
    return str(value)


def _list_marker(spec: tuple[str, str], ilvl: int, counters: dict[int, int]) -> str:
    fmt, template = spec
    if fmt in BULLET_FORMATS:
        return "—"
    marker = template
    for level, count in counters.items():
        numeral = _numeral(count, fmt if level == ilvl else "decimal")
        marker = marker.replace(f"%{level + 1}", numeral)
    return re.sub(r"%\d", "", marker)


def _docx_num_ref(paragraph: Paragraph) -> tuple[int, int] | None:
    properties = paragraph._p.pPr
    numbering = properties.numPr if properties is not None else None
    if numbering is None or numbering.numId is None:
        return None
    ilvl = numbering.ilvl.val if numbering.ilvl is not None else 0
    return int(numbering.numId.val), int(ilvl or 0)


def _docx_list_level(paragraph: Paragraph) -> int | None:
    """Уровень пункта списка: сначала настоящая нумерация Word, потом отступ слева."""
    properties = paragraph._p.pPr
    numbering = properties.numPr if properties is not None else None
    if numbering is not None:
        raw_level = numbering.ilvl.val if numbering.ilvl is not None else 0
        return 1 + min(MAX_LIST_LEVEL - 1, int(raw_level or 0))
    indent = paragraph.paragraph_format.left_indent
    if indent is None:
        return None
    return 1 + min(MAX_LIST_LEVEL - 1, int(indent.pt // INDENT_STEP))


def _docx_element(
    paragraph: Paragraph, bbox: tuple[float, float, float, float], marker: str, body: str
) -> ParsedElement:
    """Элемент абзаца DOCX; `body` — текст с формулами (`docx_content`)."""
    style = paragraph.style.name.lower() if paragraph.style else ""
    if not marker and docx_content.display_only(body):
        return ParsedElement("formula", body, bbox)
    text = f"{marker} {body}".strip() if marker else body
    list_level = _docx_list_level(paragraph)
    if marker or "list" in style or BULLET_RE.match(text):
        return ParsedElement("list", text, bbox, list_level or 1)
    if style.startswith("heading"):
        level_match = re.search(r"(\d+)$", style)
        return ParsedElement("heading", text, bbox, int(level_match.group(1)) if level_match else 1)
    if NUMBERED_RE.match(text) and len(text) <= HEADING_MAX_CHARS:
        return ParsedElement("heading", text, bbox, 1)
    if ORDERED_RE.match(text):
        return ParsedElement("list", text, bbox, list_level or 1)
    return ParsedElement("paragraph", text, bbox, None)


R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def _docx_images(
    document: Document, paragraph: Paragraph, index: int
) -> list[tuple[str, bytes]]:
    """Картинки абзаца: Word держит их отдельными частями, абзац ссылается по rId."""
    found: list[tuple[str, bytes]] = []
    for order, node in enumerate(paragraph._p.iter()):
        rel_id = node.get(R_EMBED)
        if not rel_id:
            continue
        part = document.part.related_parts.get(rel_id)
        if part is None:
            continue
        extension = Path(str(part.partname)).suffix.lstrip(".").lower() or "png"
        found.append((f"docx{index}-{order}.{extension}", part.blob))
    return found


def _docx_images_pass(
    parsed: ParsedPage,
    params: OcrRuntimeParams,
    recognizer: PageRecognizer | None,
) -> ParsedPage:
    """Изображения DOCX по режиму запуска.

    Координаты страницы DOCX условные (порядок абзацев), поэтому площадь и
    полоса колонтитула не считаются — только пиксельный размер, повтор и подпись.
    """
    parsed = finalize_images(parsed, conditional_geometry=True)
    if recognizer is not None:
        return _describe_page_images(parsed, recognizer, params)
    if params.images_for("fast") != "text_only":
        return parsed
    elements = list(parsed.elements)
    for index, element in enumerate(elements):
        meta = element_meta(element)
        if meta is None or not element.asset_path or not auto_send(meta):
            continue
        try:
            data = material_path(element.asset_path).read_bytes()
        except OSError:
            continue
        extension = Path(element.asset_path).suffix.lstrip(".") or "png"
        recognized = _ocr_raster(data, extension, 1, params)
        meta = _text_only_meta(
            meta,
            recognized[0] if recognized else None,
            recognized[1] if recognized else None,
            params.quality_threshold,
        )
        elements[index] = replace(
            element,
            text=recognized[0] if recognized else element.text,
            confidence=recognized[1] if recognized else None,
            recognition_source="ocr" if recognized else element.recognition_source,
            image=meta,
        )
    return replace(parsed, elements=tuple(elements))


def _docx_blocks(document: Document) -> Iterator[Paragraph | object]:
    """Абзацы и таблицы тела документа в их порядке (`document.paragraphs`
    таблиц не видит). Таблица отдаётся своим XML-узлом `w:tbl`."""
    body = document.element.body
    pending = list(body.iterchildren())
    while pending:
        node = pending.pop(0)
        if node.tag == f"{W_NS}p":
            yield Paragraph(node, document._body)
        elif node.tag == f"{W_NS}tbl":
            yield node
        elif node.tag == f"{W_NS}sdt":
            content = node.find(f"{W_NS}sdtContent")
            if content is not None:
                pending[:0] = list(content.iterchildren())


def _docx_image_elements(
    document: Document,
    paragraphs: Sequence[Paragraph],
    index: int,
    owner: str,
    bbox: tuple[float, float, float, float],
) -> list[ParsedElement]:
    elements: list[ParsedElement] = []
    for offset, paragraph in enumerate(paragraphs):
        # У абзаца имя выреза прежнее (`docx<абзац>-<n>`), у ячеек таблицы — своё.
        number = index if len(paragraphs) == 1 else index * 1000 + offset
        for name, data in _docx_images(document, paragraph, number):
            elements.append(
                ParsedElement(
                    "image",
                    IMAGE_PLACEHOLDER,
                    bbox,
                    None,
                    asset_path=store_material_asset(owner, name, data),
                    image=ImageMeta(
                        detection="docx",
                        crop_hash=crop_hash(data),
                        pixel_size=pixel_size(data),
                    ),
                )
            )
    return elements


def _docx_page(path: Path, owner: str = "") -> ParsedPage:
    """DOCX целиком одной страницей: абзацы, формулы Word, таблицы и картинки."""
    document = Document(path)
    numbering = _docx_numbering(document)
    blocks: list[tuple[Paragraph | object, str]] = []
    for block in _docx_blocks(document):
        if isinstance(block, Paragraph):
            text = docx_content.paragraph_text(block._p)
            if text or (owner and _docx_images(document, block, 0)):
                blocks.append((block, text))
        else:
            blocks.append((block, docx_content.table_markdown(block)))
    total = max(1, len(blocks))
    counters: dict[int, dict[int, int]] = {}

    elements: list[ParsedElement] = []
    for index, (block, text) in enumerate(blocks):
        bbox = (0.0, index / total, 1.0, (index + 1) / total)
        if not isinstance(block, Paragraph):
            if text:
                elements.append(ParsedElement("table", text, bbox))
            if owner:
                cells = [Paragraph(node, document._body) for node in block.iter(f"{W_NS}p")]
                elements.extend(_docx_image_elements(document, cells, index, owner, bbox))
            continue
        if owner:
            elements.extend(_docx_image_elements(document, [block], index, owner, bbox))
        if not text:
            continue
        marker = ""
        reference = _docx_num_ref(block)
        spec = numbering.get(reference) if reference is not None else None
        if reference is not None and spec is not None:
            num_id, ilvl = reference
            level_counts = counters.setdefault(num_id, {})
            level_counts[ilvl] = level_counts.get(ilvl, 0) + 1
            for deeper in [key for key in level_counts if key > ilvl]:
                del level_counts[deeper]
            marker = _list_marker(spec, ilvl, level_counts)
        elements.append(_docx_element(block, bbox, marker, text))

    plain = "\n".join(element.text for element in elements if element.kind != "image")
    return ParsedPage(1, 1, 1, _markdown(elements), plain, "native", tuple(elements))


def _page_indices(
    document: fitz.Document, start_page: int, page_numbers: Sequence[int] | None
) -> Iterator[int]:
    """Какие страницы разбирать: продолжение с чекпоинта или явный список."""
    if page_numbers is None:
        yield from range(start_page - 1, len(document))
        return
    for page_number in page_numbers:
        if start_page <= page_number <= len(document):
            yield page_number - 1


def _inherit_xref_repeats(
    parsed: ParsedPage, embedded: Sequence[ParsedElement]
) -> ParsedPage:
    """Повтор xref встроенного растра переходит на вырез разметчика поверх него.

    Разметчик рендерит свой вырез той же картинки, а встроенный растр с сигналом
    повтора отбрасывается как дубль. Без переноса логотип с каждой страницы
    становился бы «уникальным» содержанием и уходил бы на платное описание.
    """
    repeated = [
        element.bbox
        for element in embedded
        if element.kind == "image" and element.image and XREF_REPEATED in element.image.signals
    ]
    if not repeated:
        return parsed
    elements = list(parsed.elements)
    for index, element in enumerate(elements):
        meta = element_meta(element)
        if meta is None or XREF_REPEATED in meta.signals:
            continue
        if any(_bbox_overlap(box, element.bbox) >= 0.6 for box in repeated):
            elements[index] = replace(
                element, image=replace(meta, signals=(*meta.signals, XREF_REPEATED))
            )
    return replace(parsed, elements=tuple(elements))


def _text_layer_page(
    document: fitz.Document,
    page: fitz.Page,
    page_index: int,
    owner: str,
    mode: ParserMode,
    params: OcrRuntimeParams,
    repeated_xrefs: frozenset[int] = frozenset(),
) -> ParsedPage:
    """Страница с готовым текстовым слоем: разметка плюс картинки со страницы.

    Формулы, которых слой не передаёт текстом (`formula_zones`), приходят
    элементами-вырезами: отдельно стоящие вычёркиваются из абзацев разметки,
    строчные потом встают в свою фразу.
    """
    legacy = _native_pdf_page(
        page,
        page_index + 1,
        owner,
        ocr_images=mode == ParserMode.FAST and params.images_for("fast") == "text_only",
        params=params,
        repeated_xrefs=repeated_xrefs,
    )
    zones = _formula_zones(page)
    try:
        parsed = parse_layout_page(
            document, page_index, owner, tuple(zone.box for zone in zones if zone.standalone)
        )
    except (ValueError, KeyError, RuntimeError) as error:
        log.warning(
            "разметка страницы %s не удалась, откат на текстовый слой: %s",
            page_index + 1,
            error,
        )
        quality, confidence = _page_quality(legacy.elements, params.quality_threshold)
        return replace(
            legacy,
            quality=quality,
            confidence=confidence,
            diagnostics=(*legacy.diagnostics, "layout_fallback"),
        )
    # Схему разметчик теперь отдаёт сам (`picture`), а встроенный растр приходит
    # из текстового слоя. На одной и той же иллюстрации это два описания одного
    # объекта: без проверки перекрытия страница получала бы двойной фрагмент.
    layout_pictures = tuple(
        element.bbox for element in parsed.elements if element.kind in {"image", "formula"}
    )
    # Встроенные растры: картинки и формулы высотой в строку (у них есть вырез,
    # а у текстовых формул слоя — нет). Разметчик их строк не видит.
    images = tuple(
        element
        for element in legacy.elements
        if (element.kind == "image" or (element.kind == "formula" and element.asset_path))
        and not any(_bbox_overlap(element.bbox, box) >= 0.6 for box in layout_pictures)
    )
    found = _zone_elements(page, page_index, owner, zones, layout_pictures)
    images = (*images, *found)
    parsed = _inherit_xref_repeats(parsed, legacy.elements)
    if found:
        parsed = replace(
            parsed, diagnostics=(*parsed.diagnostics, f"formula_zones:{len(found)}")
        )
    if not images:
        return parsed
    elements = _merge_native_and_images(parsed.elements, images)
    quality, confidence = _page_quality(elements, params.quality_threshold)
    return replace(
        parsed,
        markdown=_markdown(list(elements)),
        quality=quality,
        elements=elements,
        confidence=confidence,
    )


def _formula_zones(page: fitz.Page) -> list[formula_zones.FormulaZone]:
    try:
        return formula_zones.find_zones(page)
    except (RuntimeError, ValueError) as error:
        log.warning("зоны формул страницы %s не найдены: %s", page.number + 1, error)
        return []


def _zone_elements(
    page: fitz.Page,
    page_index: int,
    owner: str,
    zones: Sequence[formula_zones.FormulaZone],
    taken: Sequence[tuple[float, float, float, float]],
) -> tuple[ParsedElement, ...]:
    """Зоны формул — элементы-вырезы, как формулы-картинки высотой в строку.

    Дальше их путь общий: «Облако» читает вырезы пачкой, строчные встают в
    свою фразу, формулы в ячейках уводят таблицу на чтение целиком; «Быстро»
    показывает вырез. Зона внутри формулы или рисунка разметчика — уже там.
    """
    elements: list[ParsedElement] = []
    for index, zone in enumerate(zones):
        if any(_bbox_overlap(zone.box, box) >= 0.6 for box in taken):
            continue
        box = zone.box if zone.standalone else _inline_crop_box(zone.box, page)
        asset_path = (
            store_material_asset(
                owner, f"p{page_index + 1}-zone{index}.png", raster.region_image(page, box)
            )
            if owner
            else None
        )
        elements.append(ParsedElement("formula", IMAGE_PLACEHOLDER, box, asset_path=asset_path))
    return tuple(elements)


def _inline_crop_box(
    box: tuple[float, float, float, float], page: fitz.Page
) -> tuple[float, float, float, float]:
    """Рамка строчной формулы, у которой вырез не заденет соседние буквы.

    Вырез берётся с полем в `REGION_PADDING_PT` со всех сторон, а у формулы
    внутри фразы соседнее слово стоит в паре пунктов: «Пусть A, B, C» уходило
    в модель с хвостом «ь» и возвращалось как «б A, B, C». Рамка заранее
    сужается по горизонтали на это поле: вырез идёт ровно по чернилам формулы.
    """
    inset = raster.REGION_PADDING_PT / page.rect.width
    if box[2] - box[0] <= 2 * inset:
        return box
    return (box[0] + inset, box[1], box[2] - inset, box[3])


def _render_page(
    page: fitz.Page, params: OcrRuntimeParams, *, for_model: bool = False
) -> tuple[bytes, float]:
    """Растр страницы под распознавание и разрешение, с которым он снят.

    Модели уходит JPEG: токены она считает по пикселям, а не по байтам, а PNG
    страницы в 300 dpi весит 3–5 МБ (в запросе ещё и base64) и кодируется почти
    две секунды. JPEG той же геометрии — около мегабайта и втрое быстрее, а на
    замере прочитан не хуже. Локальному OCR остаётся PNG без потерь.
    """
    scale, dpi = raster.render_scale(page, params.raster_scale)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    if for_model:
        return pixmap.tobytes("jpg", jpg_quality=MODEL_JPEG_QUALITY), dpi
    return pixmap.tobytes("png"), dpi


def _scanned_page(
    page: fitz.Page,
    page_index: int,
    owner: str,
    params: OcrRuntimeParams,
    recognizer: PageRecognizer | None,
    rendered: tuple[bytes, float] | None = None,
    *,
    layer: bool = False,
) -> ParsedPage:
    """Страница целиком во внешнюю модель или в локальный OCR.

    :param rendered: растр, уже снятый для чтения наперёд, — второй раз не рендерим.
    :param layer: у страницы пригодный текстовый слой. Тогда рамки модели
        приводятся к нему (`page_geometry`), и пропуски ищутся по словам слоя,
        а не по чернилам вокруг неточных рамок.
    """
    image, dpi = rendered or _render_page(page, params, for_model=recognizer is not None)
    if recognizer is not None:
        parsed = recognizer.recognize_page(
            image, page_index + 1, page.rect.width, page.rect.height
        )
        if layer:
            geometry = page_geometry.page_geometry(page, _formula_zones(page))
            parsed = _rebuilt(page_geometry.snap_to_layer(parsed, geometry))
        else:
            parsed = page_geometry.merge_split_images(parsed)
        parsed = _attach_region_assets(
            parsed, owner, lambda box: raster.region_image(page, box), "cloud_page"
        )
        if not layer:
            parsed = _missed_regions(parsed, image, owner)
        parsed = _describe_page_images(finalize_images(parsed), recognizer, params)
        return replace(parsed, diagnostics=(*parsed.diagnostics, f"render_dpi:{dpi:.0f}"))
    with NamedTemporaryFile(suffix=".png", delete=False) as temporary:
        temporary.write(image)
        temporary_path = Path(temporary.name)
    try:
        parsed = paddle_fast.parse_image(
            temporary_path,
            page_index + 1,
            language=params.fast_language,
            ocr_version=params.fast_model_id,
            quality_threshold=params.quality_threshold,
            owner=owner,
        )
    finally:
        temporary_path.unlink(missing_ok=True)
    parsed = finalize_images(_ocr_unread_regions(parsed, params))
    return replace(parsed, diagnostics=(*parsed.diagnostics, f"render_dpi:{dpi:.0f}"))


def _rebuilt(parsed: ParsedPage) -> ParsedPage:
    """Разметка и простой текст страницы после добавления элементов."""
    return replace(
        parsed,
        markdown=_markdown(list(parsed.elements)),
        plain_text="\n".join(item.text for item in parsed.elements if item.kind != "image"),
    )


def _attach_region_assets(
    parsed: ParsedPage,
    owner: str,
    crop: Callable[[tuple[float, float, float, float]], bytes],
    detection: str,
) -> ParsedPage:
    """Вырезать со страницы то, что модель прочитала, но показать не может.

    Прочитав страницу целиком, внешняя модель возвращает схему или график
    одной фразой: «блок-схема конечного автомата». Самой картинки в ответе нет
    и быть не может, поэтому в материале на её месте оставалась подпись без
    изображения. Координаты у модели при этом есть — по ним страница и режется
    локально. Формула и таблица режутся заодно: их LaTeX и Markdown просмотрщик
    показывает только тогда, когда они собираются, а оригинал нужен всегда.

    Ненадёжную рамку (подставленную полосой) не режем: получился бы кусок
    соседнего текста. Такое изображение остаётся без выреза и с причиной
    `bbox_unreliable` уходит в очередь проверки, а не на описание.
    """
    if not owner:
        return parsed
    elements = list(parsed.elements)
    cropped = 0
    for index, element in enumerate(elements):
        if element.kind == "image" and element.image is None:
            # Фраза модели про картинку — подпись неизвестного качества, не описание.
            meta = ImageMeta(
                processing=(
                    "legacy"
                    if element.text.strip() and element.text != IMAGE_PLACEHOLDER
                    else "unprocessed"
                ),
                review="needs_review",
                reasons=("page_model_caption",),
                detection=detection,
                provenance=ImageProvenance("parse"),
            )
            if not element.bbox_reliable:
                meta = replace(meta, reasons=(*meta.reasons, "bbox_unreliable"))
            element = elements[index] = replace(element, image=meta)
        if element.kind not in CROPPED_KINDS or element.asset_path or not element.bbox_reliable:
            continue
        name = f"p{parsed.page_number}-{element.kind}{index}.png"
        data = crop(element.bbox)
        asset_path = store_material_asset(owner, name, data)
        if element.kind == "image" and element.image is not None:
            element = replace(
                element,
                image=replace(
                    element.image, crop_hash=crop_hash(data), pixel_size=pixel_size(data)
                ),
            )
        elements[index] = replace(element, asset_path=asset_path)
        cropped += 1
    if not cropped:
        return replace(parsed, elements=tuple(elements))
    return replace(
        parsed,
        elements=tuple(elements),
        diagnostics=(*parsed.diagnostics, f"cloud_crops:{cropped}"),
    )


def _missed_regions(parsed: ParsedPage, image: bytes, owner: str) -> ParsedPage:
    """Найти на растре то, что модель пропустила, и сохранить кандидатами.

    Проверка честная только при надёжных рамках всех элементов: иначе «не
    покрыто» значит «модель не указала где», а не «модель не видела». Найденное
    не описывается само — это кандидат в очередь проверки (`missed_by_model`).
    """
    if not owner or not parsed.elements:
        return parsed
    if any(not element.bbox_reliable for element in parsed.elements):
        return replace(parsed, diagnostics=(*parsed.diagnostics, "missed_regions_unchecked"))
    try:
        with Image.open(BytesIO(image)) as opened:
            page_image = opened.convert("RGB")
    except (OSError, ValueError):
        return parsed
    regions = page_geometry.unread_candidates(
        raster.unread_regions(page_image, [element.bbox for element in parsed.elements]),
        parsed.elements,
    )
    if not regions:
        return parsed
    added: list[ParsedElement] = []
    for index, box in enumerate(regions):
        data = _crop_png(page_image, box)
        added.append(
            ParsedElement(
                "image",
                IMAGE_PLACEHOLDER,
                box,
                asset_path=store_material_asset(
                    owner, f"p{parsed.page_number}-missed{index}.png", data
                ),
                image=ImageMeta(
                    review="needs_review",
                    reasons=("missed_by_model",),
                    detection="unread_area",
                    crop_hash=crop_hash(data),
                    pixel_size=pixel_size(data),
                ),
            )
        )
    elements = _in_reading_order((*parsed.elements, *added))
    return replace(
        parsed,
        elements=elements,
        markdown=_markdown(list(elements)),
        diagnostics=(*parsed.diagnostics, f"missed_regions:{len(added)}"),
    )


def _crop_png(image: Image.Image, box: tuple[float, float, float, float]) -> bytes:
    crop = image.crop(
        (
            int(box[0] * image.width),
            int(box[1] * image.height),
            int(box[2] * image.width),
            int(box[3] * image.height),
        )
    )
    buffer = BytesIO()
    crop.save(buffer, format="PNG")
    return buffer.getvalue()


def _ocr_unread_regions(parsed: ParsedPage, params: OcrRuntimeParams) -> ParsedPage:
    """«Быстро» дочитывает вырезы непрочитанных областей скана.

    Детектор строк пропускает крупную подпись схемы, надписи графика и
    отдельные метки; повторный OCR выреза с увеличением их находит. Совпадающее
    с текстом страницы не дублируется, а неуверенно прочитанная формула не
    объявляется прочитанной — остаётся вырезом с причиной.
    """
    if params.images_for("fast") != "text_only" or not paddle_fast.available():
        return parsed
    page_text = _normalized_text(parsed.plain_text)
    elements = list(parsed.elements)
    changed = False
    for index, element in enumerate(elements):
        if element.kind != "image" or not element.asset_path or element.image is not None:
            continue
        try:
            data = material_path(element.asset_path).read_bytes()
        except OSError:
            continue
        meta = ImageMeta(detection="unread_area", crop_hash=crop_hash(data),
                         pixel_size=pixel_size(data))
        recognized = _ocr_raster(_upscaled(data), "png", parsed.page_number, params)
        text = recognized[0] if recognized else None
        if text and _normalized_text(text) and _normalized_text(text) in page_text:
            text, recognized = None, None
        meta = _text_only_meta(
            meta, text, recognized[1] if recognized else None, params.quality_threshold
        )
        if text and meta.review != "needs_review":
            elements[index] = replace(
                element, text=text, confidence=recognized[1] if recognized else None, image=meta
            )
        else:
            elements[index] = replace(element, image=meta)
        changed = True
    if not changed:
        return parsed
    return replace(parsed, elements=tuple(elements))


def _upscaled(data: bytes, factor: int = 2) -> bytes:
    """Мелкий вырез крупнее: детектор строк PP-OCR не видит кегль меньше 10 px."""
    try:
        with Image.open(BytesIO(data)) as opened:
            if max(opened.size) >= DESCRIBE_MAX_SIDE_PX:
                return data
            enlarged = opened.convert("RGB").resize(
                (opened.width * factor, opened.height * factor), Image.Resampling.LANCZOS
            )
    except (OSError, ValueError):
        return data
    buffer = BytesIO()
    enlarged.save(buffer, format="PNG")
    return buffer.getvalue()


def finalize_images(
    parsed: ParsedPage, *, conditional_geometry: bool = False
) -> ParsedPage:
    """Подписи и роль каждого изображения страницы — до любых платных вызовов."""
    if not any(element.kind == "image" for element in parsed.elements):
        return parsed
    elements = list(parsed.elements)
    for index, element in enumerate(elements):
        if element.kind != "image":
            continue
        meta = element_meta(element) or ImageMeta()
        caption = meta.caption or find_caption(elements, index)
        element = replace(element, image=replace(meta, caption=caption))
        elements[index] = replace(
            element, image=classify(element, conditional_geometry=conditional_geometry)
        )
    return replace(parsed, elements=tuple(elements))


def _prepared_image(data: bytes) -> tuple[bytes, str] | None:
    """Вырез в формате и размере, который примет провайдер; `None` — не прочитать."""
    try:
        with Image.open(BytesIO(data)) as opened:
            media = SENDABLE_MEDIA.get(opened.format or "")
            if media and max(opened.size) <= DESCRIBE_MAX_SIDE_PX:
                return data, media
            converted = opened.convert("RGB")
            converted.thumbnail((DESCRIBE_MAX_SIDE_PX, DESCRIBE_MAX_SIDE_PX))
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    buffer = BytesIO()
    converted.save(buffer, format="PNG")
    return buffer.getvalue(), "image/png"


def describe_elements(
    elements: Sequence[ParsedElement],
    page_number: int,
    recognizer: PageRecognizer,
    indexes: Sequence[int],
    *,
    source: str = "parse",
    job_id: str | None = None,
) -> tuple[list[ParsedElement], int]:
    """Описать выбранные изображения по их сохранённым вырезам.

    Общий путь для разбора и для «Описать изображения» готового материала:
    вырез читается из хранилища, модели уходит он сам, подпись и ограниченный
    соседний текст. Возвращает новые элементы и число отправленных вырезов.
    """
    result = list(elements)
    requests: list[ImageRequest] = []
    for index in indexes:
        element = result[index]
        meta = element_meta(element) or ImageMeta()
        prepared = None
        if element.asset_path:
            try:
                prepared = _prepared_image(material_path(element.asset_path).read_bytes())
            except OSError:
                prepared = None
        if prepared is None:
            reason = "asset_missing" if not element.asset_path else "unsupported_format"
            result[index] = replace(
                element,
                image=replace(
                    meta,
                    review="needs_review" if meta.review == "unreviewed" else meta.review,
                    reasons=tuple(dict.fromkeys((*meta.reasons, reason))),
                ),
            )
            continue
        data, media_type = prepared
        requests.append(
            ImageRequest(
                index=index,
                image=data,
                page_number=page_number,
                crop_hash=meta.crop_hash or crop_hash(data),
                caption=meta.caption,
                context=neighbor_context(result, index),
                media_type=media_type,
            )
        )
    if not requests:
        return result, 0
    for answer in recognizer.describe_images(requests):
        element = result[answer.index]
        meta = element_meta(element) or ImageMeta()
        if answer.description is None:
            stopped = "budget_exhausted" in answer.reasons
            result[answer.index] = replace(
                element,
                image=replace(
                    meta,
                    processing=meta.processing if stopped else "error",
                    review=meta.review if stopped else "needs_review",
                    reasons=tuple(dict.fromkeys((*meta.reasons, *answer.reasons))),
                ),
            )
            continue
        result[answer.index] = with_description(
            element,
            answer.description,
            review=answer.review,
            reasons=answer.reasons,
            role_hint=answer.role_hint,
            provenance=ImageProvenance(
                source,  # type: ignore[arg-type]
                model_id=answer.model_id,
                prompt_version=IMAGE_PROMPT_VERSION,
                run_id=answer.run_id,
                job_id=job_id,
            ),
        )
    return result, len(requests)


def _describe_page_images(
    parsed: ParsedPage, recognizer: PageRecognizer, params: OcrRuntimeParams
) -> ParsedPage:
    """Режим изображений облачного запуска: описать, пропустить или оставить."""
    mode = params.images_for("cloud")
    targets = [
        index
        for index, element in enumerate(parsed.elements)
        if element.kind == "image"
        and needs_description(element_meta(element) or ImageMeta())
        and auto_send(element_meta(element) or ImageMeta())
    ]
    if not targets:
        return parsed
    if mode == "skip":
        elements = list(parsed.elements)
        for index in targets:
            meta = element_meta(elements[index]) or ImageMeta()
            elements[index] = replace(
                elements[index],
                image=replace(
                    meta,
                    processing="skipped" if meta.processing == "unprocessed" else meta.processing,
                    reasons=tuple(dict.fromkeys((*meta.reasons, "image_mode_skip"))),
                ),
            )
        return replace(parsed, elements=tuple(elements))
    if mode != "describe":
        return parsed
    elements, sent = describe_elements(parsed.elements, parsed.page_number, recognizer, targets)
    diagnostics = (*parsed.diagnostics, f"image_descriptions:{sent}") if sent else None
    return replace(
        parsed, elements=tuple(elements), diagnostics=diagnostics or parsed.diagnostics
    )


def _recognized_regions(
    page: fitz.Page, parsed: ParsedPage, recognizer: PageRecognizer, params: OcrRuntimeParams
) -> ParsedPage:
    """Дочитать внешней моделью только то, что текстовый слой не объясняет.

    Смысл режима: текст страницы уже есть и он точен — платить за его повторное
    распознавание незачем. Формулы уходят вырезами на транскрипцию, а таблица
    слоя с формулами-картинками внутри — одним вырезом целиком. Изображения
    — по режиму запуска: «Описывать» отдельным запросом на вырез, «Только
    текст» вырезами на надписи, «Не распознавать» не уходят вовсе. Служебные и
    сомнительные изображения (`image_candidates`) не уходят ни в каком режиме.
    """
    parsed = finalize_images(parsed)
    mode = params.images_for("cloud")
    text_only = mode == "text_only"
    rasters = [
        index
        for index, element in enumerate(parsed.elements)
        if element.kind == "formula" and element.text == IMAGE_PLACEHOLDER
    ]
    tables = inline_formulas.formulas_in_tables(parsed.elements, rasters)
    in_tables = {index for _, inner in tables.values() for index in inner}
    sendable = {
        index
        for index, element in enumerate(parsed.elements)
        if element.kind == "image"
        and needs_description(element_meta(element) or ImageMeta())
        and auto_send(element_meta(element) or ImageMeta())
    }
    shaped = (
        {index for index in sendable if _formula_shaped(parsed.elements[index], page)}
        if mode != "skip"
        else set()
    )
    targets: list[tuple[int, ParsedElement]] = []
    for index, element in enumerate(parsed.elements):
        if index in tables:
            # Вырез — по рамке таблицы вместе с приросшими строками формул.
            targets.append((index, replace(element, bbox=tables[index][0])))
        elif index in shaped:
            targets.append((index, replace(element, kind="formula")))
        elif (
            (element.kind == "formula" and index not in in_tables)
            or (text_only and index in sendable)
            # Таблица, из которой слой не достал ни одной ячейки (формулы или
            # картинки в каждой), читается вырезом, иначе от неё только рамка.
            or (element.kind == "table" and element.text == IMAGE_PLACEHOLDER)
        ):
            targets.append((index, element))
    if targets:
        parsed = _apply_region_answers(
            page, parsed, recognizer, targets, params, rasters,
            {index: inner for index, (_, inner) in tables.items()}, shaped,
        )
    return _describe_page_images(parsed, recognizer, params) if not text_only else parsed


def _formula_shaped(element: ParsedElement, page: fitz.Page) -> bool:
    """Изображение, похожее на выносную формулу: низкое, вытянутое, без подписи."""
    meta = element_meta(element) or ImageMeta()
    if meta.caption:
        return False
    width = (element.bbox[2] - element.bbox[0]) * page.rect.width
    height = (element.bbox[3] - element.bbox[1]) * page.rect.height
    return 0 < height <= DISPLAY_FORMULA_MAX_PT and width / height >= DISPLAY_FORMULA_MIN_ASPECT


def _display_formula(text: str) -> str:
    """Ответ про вырез формулы — выносная формула.

    Инструкция вырезов просит LaTeX без обрамления, и так приходит даже простое
    `P_n(k)`: без `$$` оно показалось бы строкой с подчёркиванием, а не формулой.
    """
    return text if "$" in text else f"$${text}$$"


def _page_words(page: fitz.Page) -> list[inline_formulas.Word]:
    return [inline_formulas.Word(box, word) for box, word in formula_zones.page_words(page)]


def _apply_region_answers(
    page: fitz.Page,
    parsed: ParsedPage,
    recognizer: PageRecognizer,
    targets: list[tuple[int, ParsedElement]],
    params: OcrRuntimeParams,
    rasters: Sequence[int] = (),
    tables: dict[int, list[int]] | None = None,
    shaped: set[int] | None = None,
) -> ParsedPage:
    """Транскрипция вырезов формул и таблиц (и надписей картинок в «Только текст»).

    После ответов формулы-картинки внутри строки встают в свои абзацы, номер
    формулы, прочитанный отдельно, — в её `\\tag{}`, а формулы внутри таблицы,
    прочитанной целиком, уходят вместе с ней. Изображение, похожее на формулу,
    становится формулой, только если модель так и ответила; иначе оно остаётся
    изображением и идёт на описание.
    """
    tables = tables or {}
    shaped = shaped or set()
    requests = [
        RegionRequest(index=index, kind=element.kind, image=raster.region_image(page, element.bbox))
        for index, element in targets
    ]
    answers = recognizer.recognize_regions(requests, parsed.page_number)
    recognized = {answer.index: answer for answer in answers}
    elements = list(parsed.elements)
    gone: set[int] = set()
    for index, element in targets:
        answer = recognized.get(index)
        text = answer.text.strip() if answer is not None else ""
        if index in shaped:
            if answer is not None and answer.kind == "formula" and text:
                elements[index] = replace(
                    element, text=_display_formula(text), confidence=answer.confidence,
                    recognition_source="vl", image=None,
                )
                continue
            # Не формула: в «Описывать» её ждёт описание, в «Только текст» —
            # надписи из этого же ответа.
            element = parsed.elements[index]
            if params.images_for("cloud") != "text_only":
                continue
        if element.kind == "image":
            meta = _text_only_meta(
                element_meta(element) or ImageMeta(),
                text or None,
                answer.confidence if answer is not None else None,
                params.quality_threshold,
            )
            elements[index] = replace(
                element,
                text=text or element.text,
                confidence=answer.confidence if text and answer is not None else element.confidence,
                recognition_source="vl" if text else element.recognition_source,
                image=meta,
            )
            continue
        if answer is None or not text:
            continue
        if index in tables:
            if answer.kind != "table" or not TABLE_SEPARATOR_RE.search(text):
                # Таблица не собралась: остаётся слой, а формулы внутри — вырезами.
                continue
            gone.update(tables[index])
        elif answer.kind == "formula":
            text = _display_formula(text)
        elements[index] = replace(
            element,
            kind=answer.kind,
            text=text,
            confidence=answer.confidence,
            recognition_source="vl",
        )
    inline = [
        index
        for index in rasters
        if index not in gone and elements[index].text != IMAGE_PLACEHOLDER
    ]
    elements, spliced = inline_formulas.splice_inline(elements, _page_words(page), inline)
    elements, tags = inline_formulas.merge_equation_tags(elements, gone | spliced)
    updated = tuple(
        item for index, item in enumerate(elements) if index not in gone | spliced | tags
    )
    quality, confidence = _page_quality(updated)
    diagnostics = [f"cloud_regions:{len(requests)}"]
    diagnostics += [f"table_regions:{len(tables)}"] if tables else []
    diagnostics += [f"inline_formulas:{len(spliced)}"] if spliced else []
    diagnostics += [f"formula_tags:{len(tags)}"] if tags else []
    return replace(
        parsed,
        elements=updated,
        markdown=_markdown(list(updated)),
        plain_text="\n".join(item.text for item in updated if item.kind != "image"),
        quality=quality,
        confidence=confidence,
        diagnostics=(*parsed.diagnostics, *diagnostics),
    )


def _blank_page(page: fitz.Page, page_index: int) -> ParsedPage:
    return ParsedPage(page_index + 1, page.rect.width, page.rect.height, "", "", "native", ())


PageRoute = Literal["blank", "scan", "local_ocr", "cloud_page", "layer"]
# Ветки, на которых страница целиком уходит во внешнюю модель.
CLOUD_PAGE_ROUTES = frozenset({"scan", "cloud_page"})


def _page_route(
    diagnosis: TextLayerDiagnosis, mode: ParserMode, params: OcrRuntimeParams,
    cloud: bool, whole_page: bool,
) -> PageRoute:
    """Ветка разбора страницы по диагнозу слоя, режиму и стратегии запуска."""
    if diagnosis.route == "blank" and not whole_page:
        return "blank"
    if whole_page or diagnosis.route == "scan":
        return "scan"
    if diagnosis.suspicious and mode == ParserMode.FAST:
        return "local_ocr"
    if diagnosis.suspicious and cloud and params.cloud_strategy == "auto":
        return "cloud_page"
    return "layer"


def _prefetch_pages(
    document: fitz.Document,
    upcoming: Sequence[int],
    routes: dict[int, tuple[TextLayerDiagnosis, PageRoute]],
    rendered: dict[int, tuple[bytes, float]],
    recognizer: PageRecognizer,
    params: OcrRuntimeParams,
) -> None:
    """Отдать модели наперёд страницы, которые целиком уйдут в неё ближайшими.

    Окно — `recognizer.concurrency` страниц подряд; растры сохраняются, чтобы
    не рендерить их второй раз, когда очередь дойдёт до страницы.
    """
    batch: list[PageImage] = []
    for page_index in upcoming:
        if routes[page_index][1] not in CLOUD_PAGE_ROUTES or page_index in rendered:
            continue
        page = document[page_index]
        rendered[page_index] = _render_page(page, params, for_model=True)
        batch.append(
            PageImage(rendered[page_index][0], page_index + 1, page.rect.width, page.rect.height)
        )
    if len(batch) > 1:
        recognizer.prefetch_pages(batch)


def _with_route(
    parsed: ParsedPage, diagnosis: TextLayerDiagnosis, fallback: str | None = None
) -> ParsedPage:
    """Причина маршрута страницы — в её диагностику: почему слой, OCR или модель."""
    extra = diagnosis.diagnostics()
    if fallback:
        extra = (*extra, f"route_fallback:{fallback}")
    return replace(parsed, diagnostics=tuple(dict.fromkeys((*parsed.diagnostics, *extra))))


def _pdf_pages(
    path: Path,
    mode: ParserMode,
    start_page: int,
    params: OcrRuntimeParams,
    page_numbers: Sequence[int] | None,
    owner: str,
    recognizer: PageRecognizer | None,
) -> Iterator[ParsedPage]:
    """Постраничный разбор PDF: ветка страницы — по диагнозу её текстового слоя.

    - `page` — каждая страница целиком в модель;
    - скан без слоя — целиком в модель или в локальный OCR;
    - частичный или испорченный слой — «Быстро» зовёт локальный OCR,
      «Адаптивно» отдаёт страницу модели целиком, «Экономно» оставляет слой и
      помечает страницу для проверки;
    - пригодный слой — разметка плюс вырезы по режиму изображений.

    Страницы, которые целиком уходят в модель, читаются наперёд окном
    (`_prefetch_pages`): порядок и чекпоинты остаются постраничными.
    """
    document = fitz.open(path)
    whole_page = mode == ParserMode.CLOUD and params.cloud_strategy == "page"
    repeated = repeated_image_xrefs(document)
    indices = list(_page_indices(document, start_page, page_numbers))
    window = max(1, recognizer.concurrency) if recognizer is not None else 1
    routes: dict[int, tuple[TextLayerDiagnosis, PageRoute]] = {}
    rendered: dict[int, tuple[bytes, float]] = {}
    for position, page_index in enumerate(indices):
        # Диагноз дешёвый (текстовый слой без растра), поэтому окно чтения
        # наперёд знает маршрут следующих страниц заранее.
        upcoming = indices[position : position + window]
        for ahead in upcoming:
            if ahead not in routes:
                found = diagnose(document[ahead])
                routes[ahead] = (
                    found, _page_route(found, mode, params, recognizer is not None, whole_page)
                )
        diagnosis, route = routes[page_index]
        page = document[page_index]
        if recognizer is not None and route in CLOUD_PAGE_ROUTES:
            if page_index not in rendered:
                _prefetch_pages(document, upcoming, routes, rendered, recognizer, params)
            parsed = _scanned_page(page, page_index, owner, params, recognizer,
                                   rendered.pop(page_index, None),
                                   layer=diagnosis.route == "text")
            fallback = "cloud_page" if whole_page or route == "cloud_page" else None
            yield _with_route(parsed, diagnosis, fallback)
            continue
        if route == "blank":
            yield _with_route(_blank_page(page, page_index), diagnosis)
            continue
        if route == "scan":
            parsed = _scanned_page(page, page_index, owner, params, recognizer)
            yield _with_route(parsed, diagnosis)
            continue
        if route == "local_ocr":
            parsed = _scanned_page(page, page_index, owner, params, None)
            yield _with_route(parsed, diagnosis, "local_ocr")
            continue
        parsed = _text_layer_page(document, page, page_index, owner, mode, params, repeated)
        if recognizer is not None:
            parsed = _recognized_regions(page, parsed, recognizer, params)
        else:
            parsed = finalize_images(parsed)
        if diagnosis.suspicious:
            # «Экономно»: слой оставлен, но верить ему нельзя — страница уходит
            # в «нужно проверить» вместе с причиной.
            parsed = replace(parsed, quality="ocr_low")
        yield _with_route(parsed, diagnosis)


def _photo_page(
    path: Path,
    params: OcrRuntimeParams,
    owner: str,
    recognizer: PageRecognizer | None,
) -> ParsedPage:
    """Отдельная картинка (снимок страницы или скан) как единственная страница.

    Исходный файл и есть оригинал страницы: он не теряется, даже если модель
    не вернула рамку для внутренней области. Вырезы внутренних схем режутся из
    самого снимка по надёжным рамкам.
    """
    if recognizer is not None:
        with Image.open(path) as image:
            width, height = image.size
            photo = image.convert("RGB")
        parsed = recognizer.recognize_page(path.read_bytes(), 1, float(width), float(height))
        parsed = _attach_region_assets(
            parsed, owner, lambda box: _crop_png(photo, box), "cloud_page"
        )
        return _describe_page_images(finalize_images(parsed), recognizer, params)
    parsed = paddle_fast.parse_image(
        path,
        1,
        language=params.fast_language,
        ocr_version=params.fast_model_id,
        quality_threshold=params.quality_threshold,
        owner=owner,
    )
    return finalize_images(_ocr_unread_regions(parsed, params))


def iter_pages(
    path: Path,
    mode: ParserMode,
    start_page: int = 1,
    *,
    params: OcrRuntimeParams | None = None,
    page_numbers: Sequence[int] | None = None,
    recognizer: PageRecognizer | None = None,
) -> Iterator[ParsedPage]:
    """Разобрать файл постранично выбранным режимом.

    :param mode: режим распознавания; `CLOUD` работает только вместе с `recognizer`.
    :param start_page: с какой страницы продолжать после чекпоинта воркера.
    :param page_numbers: явный список страниц, когда переразбирается часть материала.
    :param recognizer: порт внешней модели; `None` — разбор целиком локальный.
    """
    params = params or OcrRuntimeParams()
    suffix = path.suffix.lower()
    # Имя файла материала — его sha256, поэтому оно же служит папкой для картинок.
    owner = path.stem
    if suffix == ".pdf":
        yield from _pdf_pages(path, mode, start_page, params, page_numbers, owner, recognizer)
        return
    if start_page > 1:
        return
    if suffix in {".jpg", ".jpeg", ".png"}:
        yield _photo_page(path, params, owner, recognizer)
    elif suffix == ".docx":
        yield _docx_images_pass(_docx_page(path, owner), params, recognizer)
    elif suffix in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}:
        yield parse_audio(path)
    else:
        yield _text_page(path)
