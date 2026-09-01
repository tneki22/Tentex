"""Глобальная рабочая область материала: вид источника, доступ без проекта, поиск.

Ключевая граница задачи: чтение и обработка общего материала не должны требовать
`ProjectMaterial`, а привязки остаются проектными. Здесь проверяется первое.
"""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import add_page_with_fragments, link_material, make_exam_project, make_material
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.main import create_app
from app.materials import library
from app.materials import revisions as revision_registry
from app.materials.schemas import (
    LibraryMaterialAttachWrite,
    LibraryTextMaterialCreate,
    MaterialPurpose,
    ProcessingStart,
)
from app.models import (
    Material,
    MaterialFragment,
    MaterialPage,
    MaterialRevisionOrigin,
    MaterialSourceKind,
    PageQuality,
    ParserMode,
    ProjectStatus,
    SourceRole,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError


def _material(
    session: Session,
    seed: str,
    *,
    media_type: str,
    source_kind: MaterialSourceKind = MaterialSourceKind.FILE,
    source_url: str | None = None,
    outline: list[dict[str, object]] | None = None,
) -> Material:
    material = Material(
        id=uuid4(),
        sha256=seed.rjust(64, "0"),
        original_name=f"{seed}.bin",
        storage_path=f"materials/{seed}.bin",
        media_type=media_type,
        source_kind=source_kind,
        source_url=source_url,
        retrieved_at=utc_now() if source_url else None,
        size_bytes=10,
        page_count=1,
        active_parse_revision=0,
        outline=outline or [],
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(material)
    session.commit()
    return material


@pytest.mark.parametrize(
    ("media_type", "source_kind", "expected"),
    [
        ("application/pdf", MaterialSourceKind.FILE, "pdf"),
        ("image/png", MaterialSourceKind.FILE, "image"),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            MaterialSourceKind.FILE,
            "document",
        ),
        ("text/plain", MaterialSourceKind.TEXT, "plain_text"),
        ("text/markdown", MaterialSourceKind.URL, "web"),
        ("text/markdown", MaterialSourceKind.YOUTUBE, "youtube"),
        ("audio/mpeg", MaterialSourceKind.AUDIO, "audio"),
    ],
)
def test_presentation_kind_is_derived_once(
    session: Session, media_type: str, source_kind: MaterialSourceKind, expected: str
) -> None:
    material = _material(
        session,
        f"b{abs(hash(expected)) % 1000:03d}",
        media_type=media_type,
        source_kind=source_kind,
        source_url="https://example.org/a" if source_kind != MaterialSourceKind.FILE else None,
    )
    assert library.presentation_kind(material) == expected


def test_capabilities_follow_source_kind(session: Session) -> None:
    pdf = _material(session, "c01", media_type="application/pdf")
    add_page_with_fragments(session, pdf, page_number=1, revision=1, fragments=["Текст"])
    pdf.active_parse_revision = 1
    session.commit()

    detail = library.read_library_material(session, pdf.id)
    assert detail.presentation_kind == "pdf"
    assert detail.capabilities.can_compare is True
    assert detail.capabilities.can_run_ocr is True
    assert detail.capabilities.can_refresh_source is False
    assert detail.capabilities.can_edit_text is True
    assert detail.capabilities.has_timeline is False

    audio = _material(session, "c02", media_type="audio/mpeg", source_kind=MaterialSourceKind.AUDIO)
    audio_detail = library.read_library_material(session, audio.id)
    assert audio_detail.capabilities.can_run_ocr is False
    assert audio_detail.capabilities.has_timeline is True
    assert audio_detail.capabilities.can_edit_text is False


def test_embedded_outline_wins_over_recognized_headings(session: Session) -> None:
    material = _material(
        session,
        "c03",
        media_type="application/pdf",
        outline=[{"level": 1, "title": "Глава 1", "page": 1}],
    )
    material.active_parse_revision = 1
    session.commit()

    detail = library.read_library_material(session, material.id)
    assert detail.outline_source == "embedded"
    assert [item.title for item in detail.outline] == ["Глава 1"]


def test_recognized_outline_is_built_from_heading_fragments(session: Session) -> None:
    material = _material(session, "c04", media_type="application/pdf")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Заголовок", "Абзац"]
    )
    material.active_parse_revision = 1
    session.commit()
    # Первый фрагмент делаем заголовком: у PDF без закладок оглавление собирается так.
    page_fragments = library.fragments_by_page(session, material.id, 1)[1]
    page_fragments[0].element_kind = "heading"
    page_fragments[0].structure_level = 1
    session.commit()

    detail = library.read_library_material(session, material.id)
    assert detail.outline_source == "recognized"
    assert [item.title for item in detail.outline] == ["Заголовок"]


def test_material_without_headings_has_no_outline(session: Session) -> None:
    material = _material(session, "c05", media_type="application/pdf")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Абзац"])
    material.active_parse_revision = 1
    session.commit()

    detail = library.read_library_material(session, material.id)
    assert detail.outline_source == "none"
    assert detail.outline == []
    assert detail.capabilities.has_outline is False


def test_page_is_readable_without_any_project(session: Session) -> None:
    material = make_material(session, "c06")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    session.commit()

    page = library.read_library_page(session, material.id, 1)
    assert page.page_number == 1
    assert library.read_library_material(session, material.id).usage == []


def test_global_text_material_is_created_without_project(session: Session) -> None:
    detail = library.create_library_text(
        session, LibraryTextMaterialCreate(name="Конспект.txt", text="Первый абзац")
    )

    assert detail.usage == []
    assert detail.presentation_kind == "plain_text"
    assert detail.status == "ready_to_process"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/materials/text", {"name": "Конспект.txt", "text": "Первый абзац"}),
        ("/api/materials/external", {"kind": "url", "url": "https://example.test"}),
    ],
)
def test_library_create_http_accepts_only_library_fields(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, str],
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        library,
        "fetch_external",
        lambda _command: (
            "Страница.md",
            "Сохранённый текст",
            "https://example.test",
            datetime(2026, 1, 1),
            MaterialSourceKind.URL,
        ),
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    response = TestClient(app, raise_server_exceptions=False).post(path, json=payload)

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_role", "main"),
        ("purposes", ["study_source"]),
        ("exam_slot", "question_list"),
    ],
)
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/materials/text", {"name": "Конспект.txt", "text": "Первый абзац"}),
        ("/api/materials/external", {"kind": "url", "url": "https://example.test"}),
    ],
)
def test_library_create_http_rejects_project_fields(
    session: Session,
    path: str,
    payload: dict[str, str],
    field: str,
    value: object,
) -> None:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    response = TestClient(app, raise_server_exceptions=False).post(
        path, json={**payload, field: value}
    )

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", field] and error["type"] == "extra_forbidden"
        for error in response.json()["detail"]
    )


@pytest.mark.parametrize(
    ("path_suffix", "payload"),
    [
        ("text", {"name": "Вопросы.txt", "text": "1. Первый вопрос"}),
        ("external", {"kind": "url", "url": "https://example.test"}),
    ],
)
def test_project_create_http_keeps_project_fields(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    payload: dict[str, str],
) -> None:
    project = make_exam_project(session)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        library,
        "fetch_external",
        lambda _command: (
            "Вопросы.md",
            "1. Первый вопрос",
            "https://example.test",
            datetime(2026, 1, 1),
            MaterialSourceKind.URL,
        ),
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/projects/{project.id}/materials/{path_suffix}",
        json={
            **payload,
            "source_role": "main",
            "purposes": ["exam_structure"],
            "exam_slot": "question_list",
        },
    )

    assert response.status_code == 201
    assert response.json()["source_role"] == "main"
    assert response.json()["purposes"] == ["exam_structure"]
    assert response.json()["exam_slot"] == "question_list"


def test_attach_links_existing_material_and_rejects_duplicate(session: Session) -> None:
    project = make_exam_project(session)
    material = make_material(session, "c07")
    session.commit()

    detail = library.attach_material_to_project(
        session,
        material.id,
        LibraryMaterialAttachWrite(
            project_id=project.id,
            display_name="Методичка проекта",
            source_role=SourceRole.MAIN,
            purposes=[MaterialPurpose.STUDY_SOURCE],
        ),
    )
    assert [usage.project_id for usage in detail.usage] == [project.id]
    assert detail.usage[0].display_name == "Методичка проекта"

    with pytest.raises(ProjectConflictError) as error:
        library.attach_material_to_project(
            session, material.id, LibraryMaterialAttachWrite(project_id=project.id)
        )
    assert error.value.code == "material_already_attached"


def test_attach_to_two_projects_lists_both_usages(session: Session) -> None:
    first = make_exam_project(session)
    second = make_exam_project(session)
    second.name = "Второй проект"
    material = make_material(session, "c08")
    session.commit()

    library.attach_material_to_project(
        session, material.id, LibraryMaterialAttachWrite(project_id=first.id)
    )
    detail = library.attach_material_to_project(
        session, material.id, LibraryMaterialAttachWrite(project_id=second.id)
    )

    assert {usage.project_id for usage in detail.usage} == {first.id, second.id}


def test_attach_to_archived_project_is_rejected(session: Session) -> None:
    project = make_exam_project(session, status=ProjectStatus.ARCHIVED)
    material = make_material(session, "c09")
    session.commit()

    with pytest.raises(ProjectConflictError) as error:
        library.attach_material_to_project(
            session, material.id, LibraryMaterialAttachWrite(project_id=project.id)
        )
    assert error.value.code == "project_read_only"


def test_attach_to_missing_project_is_not_found(session: Session) -> None:
    material = make_material(session, "c0a")
    session.commit()

    with pytest.raises(ProjectNotFoundError):
        library.attach_material_to_project(
            session, material.id, LibraryMaterialAttachWrite(project_id=uuid4())
        )


def test_search_finds_page_without_project_and_ignores_other_materials(session: Session) -> None:
    target = make_material(session, "c0b")
    other = make_material(session, "c0c")
    add_page_with_fragments(
        session, target, page_number=1, revision=1, fragments=["Индексы ускоряют выборку"]
    )
    add_page_with_fragments(
        session, other, page_number=1, revision=1, fragments=["Индексы в другом файле"]
    )
    session.commit()
    from app.bindings.search import reindex_material

    reindex_material(session, target.id)
    reindex_material(session, other.id)
    session.commit()

    result = library.search_library_material(session, target.id, "индекс")

    assert result.hits, "лексический поиск должен найти лемму «индекс»"
    assert all(hit.page_number == 1 for hit in result.hits)
    assert len(result.hits) == 1


def test_empty_query_returns_no_hits(session: Session) -> None:
    material = make_material(session, "c0d")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    session.commit()

    assert library.search_library_material(session, material.id, "   ").hits == []


def test_historical_search_uses_its_own_fragments(session: Session) -> None:
    material = make_material(session, "c0e")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Старая формулировка теоремы"]
    )
    revision_registry.record_revision(
        session, material.id, 1, origin=MaterialRevisionOrigin.IMPORTED
    )
    session.commit()
    from app.materials.schemas import PageTextUpdate

    library.update_library_page_text(
        session, material.id, 1, PageTextUpdate(text="Новая формулировка леммы")
    )

    historical = library.search_library_material(session, material.id, "теорема", revision=1)
    current = library.search_library_material(session, material.id, "теорема")

    assert [hit.text for hit in historical.hits] == ["Старая формулировка теоремы"]
    assert current.hits == []


def test_delete_preview_lists_every_project(session: Session) -> None:
    first = make_exam_project(session)
    second = make_exam_project(session)
    material = make_material(session, "c0f")
    link_material(session, first, material)
    link_material(session, second, material)
    session.commit()

    preview = library.material_delete_preview(session, material.id)

    assert {usage.project_id for usage in preview.material.usage} == {first.id, second.id}


def test_bulk_delete_removes_every_material_with_its_pages(session: Session) -> None:
    project = make_exam_project(session)
    first = make_material(session, "c0d")
    second = make_material(session, "c0e")
    link_material(session, project, first)
    link_material(session, project, second)
    add_page_with_fragments(session, first, page_number=1, revision=1, fragments=["Первый"])
    add_page_with_fragments(session, second, page_number=1, revision=1, fragments=["Второй"])
    session.commit()

    preview = library.materials_delete_preview(session, [first.id, second.id])
    assert {material.id for material in preview.materials} == {first.id, second.id}

    library.delete_library_materials(session, [first.id, second.id])

    assert library.list_library_materials(session) == []
    assert session.scalars(select(MaterialPage)).all() == []
    assert session.scalars(select(MaterialFragment)).all() == []


@pytest.mark.parametrize("parser_mode", [ParserMode.FAST, ParserMode.TEXTBOOK])
def test_detail_reports_quality_counters_for_active_revision(
    session: Session, parser_mode: ParserMode
) -> None:
    material = make_material(session, "c10")
    material.parser_mode = parser_mode
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    session.add(
        MaterialPage(
            id=uuid4(),
            material_id=material.id,
            revision=1,
            page_number=2,
            width=595,
            height=842,
            text="Скан",
            markdown="Скан",
            quality=PageQuality.OCR_LOW,
            elements=[],
            diagnostics=[],
        )
    )
    session.commit()

    detail = library.read_library_material(session, material.id)
    assert detail.native_page_count == 1
    assert detail.ocr_low_page_count == 1
    assert detail.parser_mode == parser_mode
    listed = next(
        item for item in library.list_library_materials(session) if item.id == material.id
    )
    assert listed.parser_mode == parser_mode
    assert listed.ocr_low_page_count == 1
    assert all(page.reviewed_at is None for page in detail.page_states)
    assert isinstance(detail.updated_at, datetime)


def test_confirming_low_ocr_page_clears_review_warning_without_changing_quality(
    session: Session,
) -> None:
    material = make_material(session, "c11")
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=1,
        page_number=1,
        width=595,
        height=842,
        text="Распознанный текст",
        markdown="Распознанный текст",
        quality=PageQuality.OCR_LOW,
        confidence=0.61,
        elements=[],
        diagnostics=["low_confidence"],
    )
    session.add(page)
    material.ocr_low_page_count = 1
    session.commit()
    revision_registry.record_revision(
        session,
        material.id,
        1,
        origin=MaterialRevisionOrigin.IMPORTED,
        summary=revision_registry.revision_summary(session, material.id, 1),
    )
    session.commit()

    first = library.confirm_library_page_review(session, material.id, 1)
    confirmed_at = session.get(MaterialPage, page.id).reviewed_at
    second = library.confirm_library_page_review(session, material.id, 1)

    assert confirmed_at is not None
    assert session.get(MaterialPage, page.id).reviewed_at == confirmed_at
    assert session.get(MaterialPage, page.id).quality == PageQuality.OCR_LOW
    assert first.ocr_low_page_count == 0
    assert first.ocr_page_count == 1
    assert second.page_states[0].reviewed_at == confirmed_at
    assert library.list_library_revisions(session, material.id)[0].summary[
        "review_page_count"
    ] == 0


def test_confirmed_page_is_excluded_from_needs_review_scope(session: Session) -> None:
    material = make_material(session, "c12")
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=1,
        page_number=1,
        width=595,
        height=842,
        text="Распознанный текст",
        markdown="Распознанный текст",
        quality=PageQuality.OCR_LOW,
        elements=[],
        diagnostics=[],
    )
    session.add(page)
    session.commit()

    library.confirm_library_page_review(session, material.id, 1)

    with pytest.raises(ProjectConflictError) as error:
        library._selected_pages(
            session,
            material,
            ProcessingStart(parser_mode="fast", scope="needs_review"),
        )
    assert error.value.code == "material_has_no_review_pages"


def test_copying_unchanged_page_preserves_review_confirmation(session: Session) -> None:
    material = make_material(session, "c13")
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=1,
        page_number=1,
        width=595,
        height=842,
        text="Проверенный текст",
        markdown="Проверенный текст",
        quality=PageQuality.OCR_LOW,
        reviewed_at=utc_now(),
        elements=[],
        diagnostics=[],
    )
    session.add(page)
    session.commit()

    copied = library.copy_page(session, page, 2)

    assert copied.reviewed_at == page.reviewed_at


def test_native_page_cannot_be_confirmed_as_low_ocr(session: Session) -> None:
    material = make_material(session, "c14")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])

    with pytest.raises(ProjectConflictError) as error:
        library.confirm_library_page_review(session, material.id, 1)

    assert error.value.code == "page_review_not_required"
