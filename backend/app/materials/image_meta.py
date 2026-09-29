"""Состояние изображений материала: JSON-кодек, текст для поиска и подписи.

Одно место на три потребителя: парсеры строят `ImageMeta` при разборе, ревизия
хранит её в `MaterialPage.elements` и `MaterialFragment.visual`, а описание
готового материала переписывает только её и текст элемента.

Наличие описания здесь не угадывается по префиксу текста: у старых страниц
без поля `image` состояние выводится один раз (`legacy_meta`) и дальше живёт
в явных осях роли, обработки и проверки.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import replace
from io import BytesIO
from typing import Any

from PIL import Image

from app.materials.parsers.base import (
    IMAGE_PLACEHOLDER,
    MODEL_DESCRIPTION_MARK,
    ImageDescription,
    ImageMeta,
    ImageProvenance,
    ParsedElement,
)

# Подпись к рисунку или таблице: «Рис. 3.2», «Рисунок 5», «Схема 1», «Fig. 2».
CAPTION_RE = re.compile(
    r"^\s*(?:рис(?:унок|\.)?|схема|график|диаграмма|табл(?:ица|\.)?|фото|"
    r"fig(?:ure|\.)?|table|chart|scheme)\s*[№#]?\s*[\dIVXА-Я]",
    re.IGNORECASE,
)
# Насколько далеко по вертикали (доля страницы) подпись может стоять от рисунка.
CAPTION_DISTANCE = 0.08
# Сколько соседнего текста уходит в запрос вместе с вырезом: хватает, чтобы
# назвать схему своим именем, и не превращает запрос в пересказ страницы.
CONTEXT_CHARS = 600
MAX_LABEL_CHARS = 400

# Что считается «ещё нет проверяемого текста изображения»: такие кандидаты
# входят в число N у кнопки «Описать изображения».
DESCRIBABLE_PROCESSING = frozenset({"unprocessed", "legacy", "text_only", "skipped", "error"})
# Состояния, при которых текст фрагмента-изображения можно прочесть и процитировать:
# описание модели или надпись, прочитанная в самом рисунке. Ручная правка (`review`)
# читаема при любом состоянии.
READABLE_PROCESSING = frozenset({"described", "text_only"})


def crop_hash(data: bytes) -> str:
    """Точный хеш выреза: по нему переиспользуются видимые факты повторов."""
    return hashlib.sha256(data).hexdigest()


def pixel_size(data: bytes) -> tuple[int, int] | None:
    """Размер выреза в пикселях. Формат, который PIL не читает (EMF), — None."""
    try:
        with Image.open(BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def is_placeholder(text: str) -> bool:
    return text.strip().startswith(IMAGE_PLACEHOLDER) and len(text.strip()) <= 40


def described_text(description: ImageDescription) -> str:
    """Текст фрагмента описанного изображения: метка модели, название, суть, надписи.

    Этот текст и ищется по словам, и попадает в чат. Метка стоит первой, чтобы
    цитата сама сообщала, что это описание модели, а не текст книги. Контекст
    подписи сюда не входит: он живёт своим фрагментом рядом.
    """
    parts = [MODEL_DESCRIPTION_MARK]
    title = description.title.strip().rstrip(".")
    if title:
        parts.append(f"{title}.")
    if description.summary.strip():
        parts.append(description.summary.strip())
    text = " ".join(parts)
    labels = [label.strip() for label in description.labels if label.strip()]
    if labels:
        text += "\nНадписи: " + "; ".join(labels)[:MAX_LABEL_CHARS]
    if description.table_markdown.strip():
        text += "\n" + description.table_markdown.strip()
    if description.latex.strip():
        text += f"\n$${description.latex.strip()}$$"
    return text


def legacy_meta(text: str, recognition_source: str, asset_path: str | None) -> ImageMeta:
    """Состояние изображения, разобранного до появления явных осей.

    Короткая облачная подпись прошлых версий — «неизвестное качество» (`legacy`):
    она не проверялась схемой ответа и не считается описанием.
    """
    reasons: tuple[str, ...] = () if asset_path else ("asset_missing",)
    if recognition_source == "manual":
        return ImageMeta(processing="text_only", review="manual", reasons=reasons,
                         provenance=ImageProvenance("manual"))
    if is_placeholder(text) or not text.strip():
        return ImageMeta(processing="unprocessed", reasons=reasons)
    if recognition_source == "vl":
        return ImageMeta(
            processing="legacy",
            review="needs_review",
            reasons=(*reasons, "legacy_caption"),
            provenance=ImageProvenance("legacy"),
        )
    return ImageMeta(processing="text_only", reasons=reasons)


def element_meta(element: ParsedElement) -> ImageMeta | None:
    """Состояние изображения элемента; у не-изображений — None."""
    if element.kind != "image":
        return None
    return element.image or legacy_meta(
        element.text, element.recognition_source, element.asset_path
    )


def fragment_meta(
    visual: dict[str, Any] | None, text: str, recognition_source: str, asset_path: str | None
) -> ImageMeta:
    """Состояние изображения-фрагмента; у старых страниц без поля оно выводится из текста."""
    if visual:
        return meta_from_json(visual)
    return legacy_meta(text, recognition_source, asset_path)


def has_readable_text(meta: ImageMeta, text: str) -> bool:
    """У изображения есть проверяемый текст: его можно прочесть, процитировать и связать.

    Заглушка «[Изображение]» и пустой текст текстом не считаются, даже если состояние
    говорит «описано»: так выглядят служебные и декоративные рисунки после описания.
    """
    if not text.strip() or is_placeholder(text):
        return False
    return meta.processing in READABLE_PROCESSING or meta.review == "manual"


def needs_description(meta: ImageMeta) -> bool:
    """Нет проверяемого текста, и изображение не исключено человеком или правилом."""
    return (
        meta.processing in DESCRIBABLE_PROCESSING
        and meta.review != "manual"
        and meta.role not in {"service", "decorative"}
    )


def with_description(
    element: ParsedElement,
    description: ImageDescription,
    *,
    review: str,
    reasons: Sequence[str],
    provenance: ImageProvenance,
    role_hint: str | None = None,
) -> ParsedElement:
    """Элемент с принятым описанием: текст для поиска и состояние меняются вместе.

    Мнение модели «это украшение/служебное» — не решение, а повод проверить:
    роль меняется, изображение уходит в очередь проверки и не индексируется как
    знание. Описание заведомо плохого выреза (`crop_suspect`) тоже не индексируется.
    Картинка, которая целиком оказалась формулой или таблицей с валидной
    разметкой, становится формулой или таблицей — как раньше при транскрипции.
    """
    meta = element_meta(element) or ImageMeta()
    all_reasons = list(dict.fromkeys((*meta.reasons, *reasons)))
    role = meta.role
    if role_hint in {"decorative", "service"} and meta.review not in {"manual", "verified"}:
        role = role_hint  # type: ignore[assignment]
        all_reasons.append(f"model_role_{role_hint}")
        review = "needs_review"
    elif role == "unknown" and role_hint == "content":
        role = "content"
    updated = replace(
        meta,
        role=role,
        processing="described",
        review=review,  # type: ignore[arg-type]
        reasons=tuple(dict.fromkeys(all_reasons)),
        description=description,
        provenance=provenance,
    )
    confidence = description.confidence
    if role in {"decorative", "service"} or "crop_suspect" in all_reasons:
        return replace(element, text=IMAGE_PLACEHOLDER, recognition_source="vl", image=updated,
                       confidence=confidence)
    if description.kind == "formula" and description.latex and review != "needs_review":
        return replace(element, kind="formula", text=f"$${description.latex}$$",
                       recognition_source="vl", image=None, confidence=confidence)
    if description.kind == "table" and description.table_markdown and review != "needs_review":
        return replace(element, kind="table", text=description.table_markdown,
                       recognition_source="vl", image=None, confidence=confidence)
    return replace(element, text=described_text(description), recognition_source="vl",
                   image=updated, confidence=confidence)


def find_caption(elements: Sequence[ParsedElement], index: int) -> str | None:
    """Ближайшая подпись над или под изображением в пределах `CAPTION_DISTANCE`."""
    image = elements[index]
    candidates: list[tuple[float, str]] = []
    for offset in (1, -1, 2, -2):
        position = index + offset
        if not 0 <= position < len(elements):
            continue
        neighbor = elements[position]
        if neighbor.kind == "image" or not CAPTION_RE.match(neighbor.text):
            continue
        gap = (
            neighbor.bbox[1] - image.bbox[3] if offset > 0 else image.bbox[1] - neighbor.bbox[3]
        )
        # Координаты-заглушки (DOCX, простой текст) не мерят расстояние: там
        # соседство по порядку — единственный признак.
        if not neighbor.bbox_reliable or gap <= CAPTION_DISTANCE:
            candidates.append((abs(offset), neighbor.text.strip()))
    if not candidates:
        return None
    return min(candidates)[1][:MAX_LABEL_CHARS]


def neighbor_context(elements: Sequence[ParsedElement], index: int) -> str:
    """Соседние абзацы вокруг изображения, не больше `CONTEXT_CHARS` символов."""
    before = [
        item.text.strip()
        for item in elements[max(0, index - 2) : index]
        if item.kind != "image" and item.text.strip()
    ]
    after = [
        item.text.strip()
        for item in elements[index + 1 : index + 3]
        if item.kind != "image" and item.text.strip()
    ]
    half = CONTEXT_CHARS // 2
    text_before = " ".join(before)[-half:]
    text_after = " ".join(after)[:half]
    return "\n".join(part for part in (text_before, text_after) if part)


# ── JSON-кодек ───────────────────────────────────────────────────────────────


def description_to_json(description: ImageDescription) -> dict[str, Any]:
    return {
        "kind": description.kind,
        "title": description.title,
        "summary": description.summary,
        "objects": list(description.objects),
        "relations": list(description.relations),
        "labels": list(description.labels),
        "unreadable": list(description.unreadable),
        "details": list(description.details),
        "table_markdown": description.table_markdown,
        "latex": description.latex,
        "context_note": description.context_note,
        "confidence": description.confidence,
    }


def description_from_json(value: dict[str, Any]) -> ImageDescription:
    return ImageDescription(
        kind=str(value.get("kind") or "other"),
        title=str(value.get("title") or ""),
        summary=str(value.get("summary") or ""),
        objects=tuple(str(item) for item in value.get("objects") or ()),
        relations=tuple(str(item) for item in value.get("relations") or ()),
        labels=tuple(str(item) for item in value.get("labels") or ()),
        unreadable=tuple(str(item) for item in value.get("unreadable") or ()),
        details=tuple(str(item) for item in value.get("details") or ()),
        table_markdown=str(value.get("table_markdown") or ""),
        latex=str(value.get("latex") or ""),
        context_note=str(value.get("context_note") or ""),
        confidence=value.get("confidence"),
    )


def meta_to_json(meta: ImageMeta) -> dict[str, Any]:
    provenance = meta.provenance
    return {
        "role": meta.role,
        "processing": meta.processing,
        "review": meta.review,
        "reasons": list(meta.reasons),
        "signals": list(meta.signals),
        "detection": meta.detection,
        "crop_hash": meta.crop_hash,
        "pixel_size": list(meta.pixel_size) if meta.pixel_size else None,
        "caption": meta.caption,
        "description": description_to_json(meta.description) if meta.description else None,
        "provenance": (
            {
                "source": provenance.source,
                "model_id": provenance.model_id,
                "provider_id": provenance.provider_id,
                "prompt_version": provenance.prompt_version,
                "run_id": provenance.run_id,
                "job_id": provenance.job_id,
            }
            if provenance
            else None
        ),
    }


def meta_from_json(value: dict[str, Any]) -> ImageMeta:
    provenance = value.get("provenance")
    description = value.get("description")
    size = value.get("pixel_size")
    return ImageMeta(
        role=value.get("role") or "unknown",
        processing=value.get("processing") or "unprocessed",
        review=value.get("review") or "unreviewed",
        reasons=tuple(value.get("reasons") or ()),
        signals=tuple(value.get("signals") or ()),
        detection=str(value.get("detection") or "embedded"),
        crop_hash=value.get("crop_hash"),
        pixel_size=(int(size[0]), int(size[1])) if size else None,
        caption=value.get("caption"),
        description=description_from_json(description) if description else None,
        provenance=(
            ImageProvenance(
                source=provenance.get("source") or "legacy",
                model_id=provenance.get("model_id"),
                provider_id=provenance.get("provider_id"),
                prompt_version=provenance.get("prompt_version"),
                run_id=provenance.get("run_id"),
                job_id=provenance.get("job_id"),
            )
            if provenance
            else None
        ),
    )
