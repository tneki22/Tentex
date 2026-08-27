"""HTTP-клиент из CPU-воркера к изолированному GPU-сервису режима «Учебник».

Сервис поднимает связку PP-StructureV3 + PP-FormulaNet: размечает страницу,
читает текст и переводит печатные формулы в LaTeX. Внутренняя метка источника
фрагмента — `vl` (историческое имя, менять её значит трогать данные), но
пользователю она показывается как «Учебник», а не «PaddleOCR-VL».
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from app.config import settings
from app.materials.parsers.base import ElementKind, ParsedElement, ParsedPage
from app.materials.storage import store_material_asset

ASSET_KINDS = {"formula", "table", "image"}
# Экран настроек перечитывает статус на каждый GET, а ещё опрашивает его сам —
# без короткого кэша один запрос браузера бьёт по сервису дважды подряд.
_HEALTH_CACHE_SECONDS = 2.0
_health_cache: dict[str, tuple[float, dict | None]] = {}
DEFAULT_QUALITY_THRESHOLD = 0.75
REQUIRED_LAYOUT_MODEL = "PP-DocLayout_plus-L"
LABEL_KIND: dict[str, ElementKind] = {
    "doc_title": "heading",
    "paragraph_title": "heading",
    "title": "heading",
    "text": "paragraph",
    "content": "paragraph",
    "reference": "paragraph",
    "reference_content": "paragraph",
    "formula": "formula",
    "display_formula": "formula",
    "inline_formula": "formula",
    "table": "table",
    "figure": "image",
    "image": "image",
    "chart": "image",
}


@dataclass(frozen=True, slots=True)
class TextbookStatus:
    available: bool
    label: str
    reason: str
    executor: str | None = None


def _json_request(path: str, payload: dict | None, timeout: float, *, base_url: str) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local configured service
        return json.loads(response.read().decode("utf-8"))


def health_payload(*, base_url: str | None = None) -> dict | None:
    """Сырой ответ `/health` GPU-сервиса. `None` — сервис не отвечает.

    Отдельно от `status()`, потому что настройки распознавания достают отсюда
    ещё и характеристики видеокарты: сервис — единственное место в системе,
    которое видит её напрямую.
    """
    url = base_url or settings.textbook_ocr_url
    now = time.monotonic()
    cached = _health_cache.get(url)
    if cached is not None and now - cached[0] < _HEALTH_CACHE_SECONDS:
        return cached[1]
    try:
        payload = _json_request("/health", None, timeout=0.6, base_url=url)
    except (OSError, URLError, TimeoutError, ValueError):
        payload = None
    result = payload if isinstance(payload, dict) else None
    _health_cache[url] = (now, result)
    return result


def reset_health_cache() -> None:
    """Для тестов и после запуска/остановки сервиса, чтобы статус не отставал."""
    _health_cache.clear()


def status(*, base_url: str | None = None) -> TextbookStatus:
    payload = health_payload(base_url=base_url)
    if payload is None:
        return TextbookStatus(False, "", "Сервис распознавания не отвечает.")
    ready = bool(payload.get("ready"))
    executor = str(payload.get("executor") or "") or None
    label = executor or "Сервис отвечает"
    layout_model = str(payload.get("layout_model") or "")
    if ready and layout_model != REQUIRED_LAYOUT_MODEL:
        return TextbookStatus(
            False,
            label,
            f"Сервис запущен со старой моделью разметки. Нужна {REQUIRED_LAYOUT_MODEL}; "
            "пересоберите и перезапустите сервис.",
            executor,
        )
    reason = str(payload.get("reason") or "Сервис ещё загружает модель в память видеокарты.")
    return TextbookStatus(ready, label, "" if ready else reason, executor)


def require_available(*, base_url: str | None = None) -> TextbookStatus:
    current = status(base_url=base_url)
    if not current.available:
        raise RuntimeError(current.reason)
    return current


def _bbox(value: object, width: float, height: float) -> tuple[float, float, float, float]:
    raw = value if isinstance(value, list) else [0, 0, width, height]
    if len(raw) != 4:
        raw = [0, 0, width, height]
    x0, y0, x1, y1 = (float(item) for item in raw)
    return (
        max(0.0, min(1.0, x0 / width)),
        max(0.0, min(1.0, y0 / height)),
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
    )


def _crop_asset(
    image: Image.Image,
    bbox: tuple[float, float, float, float],
    owner: str,
    page_number: int,
    index: int,
) -> str | None:
    if not owner:
        return None
    x0, y0, x1, y1 = bbox
    crop = image.crop(
        (
            round(x0 * image.width),
            round(y0 * image.height),
            round(x1 * image.width),
            round(y1 * image.height),
        )
    )
    from io import BytesIO

    output = BytesIO()
    crop.save(output, format="PNG")
    return store_material_asset(owner, f"vl-p{page_number}-{index}.png", output.getvalue())


def parse_image(
    path: Path,
    page_number: int,
    owner: str = "",
    *,
    base_url: str | None = None,
    timeout: float | None = None,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
) -> ParsedPage:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    try:
        payload = _json_request(
            "/parse",
            {"image_base64": encoded, "page_number": page_number},
            timeout=timeout if timeout is not None else settings.textbook_ocr_timeout_seconds,
            base_url=base_url or settings.textbook_ocr_url,
        )
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GPU-сервис вернул ошибку {error.code}: {detail}") from error
    except (OSError, URLError, TimeoutError) as error:
        raise RuntimeError("GPU-сервис распознавания недоступен во время обработки") from error

    width = float(payload.get("width") or 1)
    height = float(payload.get("height") or 1)
    raw_elements = payload.get("elements")
    if not isinstance(raw_elements, list):
        raise RuntimeError("GPU-сервис вернул ответ без элементов страницы")

    elements: list[ParsedElement] = []
    confidences: list[float] = []
    with Image.open(path) as source:
        source.load()
        for index, raw in enumerate(raw_elements):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or "text").lower()
            kind = LABEL_KIND.get(label, "paragraph")
            text = str(raw.get("content") or "").strip()
            if kind == "image" and not text:
                text = "[Изображение]"
            confidence_raw = raw.get("confidence")
            confidence = float(confidence_raw) if confidence_raw is not None else None
            if confidence is not None:
                confidences.append(confidence)
            bbox = _bbox(raw.get("bbox"), width, height)
            asset_path = (
                _crop_asset(source, bbox, owner, page_number, index)
                if kind in ASSET_KINDS
                else None
            )
            elements.append(
                ParsedElement(
                    kind=kind,
                    text=text,
                    bbox=bbox,
                    level=1 if kind == "heading" else None,
                    confidence=confidence,
                    asset_path=asset_path,
                    recognition_source="vl",
                )
            )
    plain = "\n".join(item.text for item in elements if item.kind != "image").strip()
    markdown = str(payload.get("markdown") or plain)
    confidence = min(confidences) if confidences else None
    quality = "ocr_low" if confidence is not None and confidence < quality_threshold else "ocr"
    diagnostics = tuple(str(item) for item in payload.get("diagnostics") or [])
    return ParsedPage(
        page_number=page_number,
        width=width,
        height=height,
        markdown=markdown,
        plain_text=plain,
        quality=quality,
        elements=tuple(elements),
        diagnostics=diagnostics,
        confidence=confidence,
    )
