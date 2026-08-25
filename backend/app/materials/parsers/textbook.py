"""HTTP-клиент из CPU-воркера к изолированному PaddleOCR-VL сервису."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from app.config import settings
from app.materials.parsers.base import ElementKind, ParsedElement, ParsedPage
from app.materials.storage import store_material_asset

ASSET_KINDS = {"formula", "table", "image"}
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


def _json_request(path: str, payload: dict | None, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{settings.textbook_ocr_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local configured service
        return json.loads(response.read().decode("utf-8"))


def status() -> TextbookStatus:
    try:
        payload = _json_request("/health", None, timeout=0.6)
    except (OSError, URLError, TimeoutError, ValueError):
        return TextbookStatus(
            False,
            "Локально · GPU",
            "GPU-сервис не запущен. Запустите профиль Compose «textbook».",
        )
    ready = bool(payload.get("ready"))
    executor = str(payload.get("executor") or "") or None
    label = str(payload.get("label") or "PaddleOCR-VL 1.6 · GPU")
    reason = str(payload.get("reason") or "GPU-сервис ещё загружает модели.")
    return TextbookStatus(ready, label, "" if ready else reason, executor)


def require_available() -> TextbookStatus:
    current = status()
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


def parse_image(path: Path, page_number: int, owner: str = "") -> ParsedPage:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    try:
        payload = _json_request(
            "/parse",
            {"image_base64": encoded, "page_number": page_number},
            timeout=settings.textbook_ocr_timeout_seconds,
        )
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GPU-сервис вернул ошибку {error.code}: {detail}") from error
    except (OSError, URLError, TimeoutError) as error:
        raise RuntimeError("GPU-сервис PaddleOCR-VL недоступен во время обработки") from error

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
    quality = "ocr_low" if confidence is not None and confidence < 0.75 else "ocr"
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
