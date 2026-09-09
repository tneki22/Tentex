"""Контракт Typst-контекста: модели нельзя подменять код текстом PDF."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.materials.context import material_context
from app.models import Material, MaterialSourceKind, MaterialState, TypstSourceChunk, utc_now


def test_typst_context_returns_exact_source_with_locator(session: Session) -> None:
    """Формула сохраняется в Typst-виде и получает путь со строками."""
    material = Material(
        id=uuid4(),
        sha256="a" * 64,
        original_name="main.typ",
        storage_path="typst/aa/source.zip",
        media_type="application/zip",
        source_kind=MaterialSourceKind.TYPST,
        size_bytes=1,
        status=MaterialState.READY,
        active_parse_revision=1,
        scan_page_count=0,
        ocr_low_page_count=0,
        outline=[],
        diagnostics=[],
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(material)
    session.add(
        TypstSourceChunk(
            material_id=material.id,
            revision=1,
            sort_order=0,
            path="main.typ",
            line_from=4,
            line_to=6,
            source_text="$integral_0^1 x dif x$",
            source_hash="b" * 64,
            page_from=1,
            page_to=1,
            diagnostic=None,
        )
    )
    session.commit()

    context = material_context(session, material.id, 1, "искажённый PDF-текст")

    assert "[Typst: main.typ, строки 4–6]" in context
    assert "$integral_0^1 x dif x$" in context
    assert "PDF" not in context
