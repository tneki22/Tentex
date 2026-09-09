"""Единый model-facing контекст материала.

PDF нужен пользователю и FTS, но Typst-код — модели: подмена одного другим
ломает формулы. Этот адаптер намеренно не зависит от чата или проходов 1–2.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Material, MaterialSourceKind, TypstSourceChunk


def material_context(
    session: Session, material_id: UUID, page_number: int, fallback: str
) -> str:
    """Возвращает raw Typst с locator либо обычный текст фрагмента."""
    material = session.get(Material, material_id)
    if material is None or material.source_kind != MaterialSourceKind.TYPST:
        return fallback
    chunks = list(
        session.scalars(
            select(TypstSourceChunk)
            .where(
                TypstSourceChunk.material_id == material_id,
                TypstSourceChunk.revision == material.active_parse_revision,
                (TypstSourceChunk.page_from.is_(None))
                | (
                    (TypstSourceChunk.page_from <= page_number)
                    & (TypstSourceChunk.page_to >= page_number)
                ),
            )
            .order_by(TypstSourceChunk.sort_order)
            .limit(3)
        )
    )
    if not chunks:
        return fallback
    return "\n\n".join(
        f"[Typst: {chunk.path}, строки {chunk.line_from}–{chunk.line_to}]\n{chunk.source_text}"
        for chunk in chunks
    )
