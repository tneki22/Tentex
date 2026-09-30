"""Кусок из файла уроков — снова на фрагментах материала этой установки.

Идентификаторы фрагментов у каждой установки свои, даже для того же PDF: разбор
мог идти другой версией или другим распознаванием. Поэтому граница куска
переносится по тексту абзаца: тот же текст на той же странице — тот же абзац;
не нашёлся — граница становится краем страницы с пометкой «Разрез сдвинут»,
как при новой ревизии материала.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lessons.refs import Bounds
from app.models import Material, MaterialFragment, MaterialPage

# Сколько первых знаков абзаца должно совпасть, если отпечаток разошёлся из-за
# мелочи (переносы, пробелы у OCR), а место на странице то же.
PREFIX_CHARS = 40


def normalized(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalized(text).encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class Resolved:
    bounds: Bounds
    shifted: bool


def resolve_anchor(session: Session, material: Material, anchor: dict[str, Any] | None
                   ) -> UUID | None:
    """Фрагмент активной ревизии по якорю: сначала отпечаток текста, затем место и начало."""
    if not anchor or material.active_parse_revision <= 0:
        return None
    rows = session.execute(
        select(MaterialFragment.id, MaterialFragment.text)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(MaterialPage.material_id == material.id,
               MaterialPage.revision == material.active_parse_revision,
               MaterialPage.page_number == anchor.get("page"))
        .order_by(MaterialFragment.sort_order)
    ).all()
    wanted = anchor.get("hash")
    for fragment_id, text in rows:
        if text_hash(text) == wanted:
            return fragment_id
    index = anchor.get("index")
    prefix = normalized(anchor.get("text") or "")[:PREFIX_CHARS]
    if isinstance(index, int) and 0 <= index < len(rows) and prefix \
            and normalized(rows[index][1])[:PREFIX_CHARS] == prefix:
        return rows[index][0]
    return None


def resolve_bounds(session: Session, material: Material, page_from: int, page_to: int,
                   anchors: dict[str, Any] | None) -> Resolved | None:
    """Границы куска в материале; None — страниц куска в материале нет."""
    last = material.page_count or page_to
    if page_from > last:
        return None
    page_to = min(page_to, last)
    anchors = anchors or {}
    start = resolve_anchor(session, material, anchors.get("from"))
    end = resolve_anchor(session, material, anchors.get("to"))
    shifted = (anchors.get("from") is not None and start is None) \
        or (anchors.get("to") is not None and end is None)
    return Resolved(Bounds(page_from, page_to, start, end), shifted)
