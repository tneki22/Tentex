from uuid import uuid4

import pytest
from conftest import add_page_with_fragments, make_material
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materials import library
from app.materials import revisions as revision_registry
from app.materials.schemas import PageTextUpdate, ProcessingStart
from app.models import (
    Material,
    MaterialFragment,
    MaterialPage,
    MaterialRevision,
    MaterialRevisionOrigin,
    PageQuality,
    ParserMode,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError


def test_recorded_revision_is_readable_and_unique(session: Session) -> None:
    material = make_material(session, "a1")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Первая страница"]
    )

    revision_registry.record_revision(
        session,
        material.id,
        1,
        origin=MaterialRevisionOrigin.IMPORTED,
        parser_mode=ParserMode.FAST,
        summary=revision_registry.revision_summary(session, material.id, 1),
    )
    session.commit()

    listed = revision_registry.list_revisions(session, material.id)
    assert [row.revision for row in listed] == [1]
    assert listed[0].summary["page_count"] == 1

    with pytest.raises(ProjectConflictError) as error:
        revision_registry.record_revision(
            session, material.id, 1, origin=MaterialRevisionOrigin.PARSE
        )
    assert error.value.code == "material_revision_exists"


def test_deleting_material_removes_its_revisions(session: Session) -> None:
    material = make_material(session, "a2")
    revision_registry.record_revision(
        session, material.id, 1, origin=MaterialRevisionOrigin.IMPORTED
    )
    session.commit()

    session.delete(session.get(Material, material.id))
    session.commit()

    assert session.scalars(select(MaterialRevision)).all() == []


def test_manual_edit_keeps_previous_revision_and_records_history(session: Session) -> None:
    material = make_material(session, "a3")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Старый текст страницы"]
    )
    revision_registry.record_revision(
        session, material.id, 1, origin=MaterialRevisionOrigin.IMPORTED
    )
    session.commit()

    result = library.update_library_page_text(
        session, material.id, 1, PageTextUpdate(text="Новый текст страницы")
    )

    assert result.page.text.strip() == "Новый текст страницы"
    refreshed = session.get(Material, material.id)
    assert refreshed is not None and refreshed.active_parse_revision == 2
    # Прежняя версия остаётся читаемой: восстановление опирается на её страницы.
    old = library.read_library_page(session, material.id, 1, revision=1)
    assert old.text.strip() == "Старый текст страницы"
    history = revision_registry.list_revisions(session, material.id)
    assert [(row.revision, row.origin) for row in history] == [
        (2, MaterialRevisionOrigin.MANUAL_EDIT),
        (1, MaterialRevisionOrigin.IMPORTED),
    ]
    assert history[0].scope == {"kind": "page", "page": 1}


def test_historical_revision_is_read_only(session: Session) -> None:
    material = make_material(session, "a4")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    revision_registry.record_revision(
        session, material.id, 1, origin=MaterialRevisionOrigin.IMPORTED
    )
    session.commit()
    library.update_library_page_text(session, material.id, 1, PageTextUpdate(text="Правка"))

    with pytest.raises(ProjectConflictError) as error:
        library.update_library_page_text(
            session, material.id, 1, PageTextUpdate(text="Ещё правка", expected_revision=1)
        )
    assert error.value.code == "stale_material_revision"


def test_restore_creates_next_revision_instead_of_rewinding(session: Session) -> None:
    material = make_material(session, "a5")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Оригинал"])
    revision_registry.record_revision(
        session, material.id, 1, origin=MaterialRevisionOrigin.IMPORTED
    )
    session.commit()
    library.update_library_page_text(session, material.id, 1, PageTextUpdate(text="Правка"))

    detail = library.restore_revision(session, material.id, 1)

    assert detail.active_parse_revision == 3
    assert library.read_library_page(session, material.id, 1).text.strip() == "Оригинал"
    history = revision_registry.list_revisions(session, material.id)
    assert history[0].origin == MaterialRevisionOrigin.RESTORE
    assert history[0].parent_revision == 1
    assert [row.revision for row in history] == [3, 2, 1]


def test_unknown_revision_answers_not_found(session: Session) -> None:
    material = make_material(session, "a6")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    session.commit()

    with pytest.raises(ProjectNotFoundError) as error:
        library.read_library_page(session, material.id, 1, revision=7)
    assert error.value.code == "material_revision_not_found"


def test_needs_review_scope_without_review_pages_is_rejected(session: Session) -> None:
    material = make_material(session, "a7")
    material.media_type = "application/pdf"
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    session.commit()

    with pytest.raises(ProjectConflictError) as error:
        library.start_library_processing(
            session, material.id, ProcessingStart(parser_mode=ParserMode.FAST, scope="needs_review")
        )
    assert error.value.code == "material_has_no_review_pages"


def test_range_scope_is_unavailable_for_text_source(session: Session) -> None:
    material = make_material(session, "a8")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    session.commit()

    with pytest.raises(ProjectDomainError) as error:
        library.start_library_processing(
            session,
            material.id,
            ProcessingStart(parser_mode=ParserMode.FAST, scope="range", page_from=1, page_to=1),
        )
    assert error.value.code == "material_scope_unsupported"


def test_processing_start_numbers_revision_above_history(session: Session) -> None:
    material = make_material(session, "a9")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Текст"])
    revision_registry.record_revision(
        session, material.id, 1, origin=MaterialRevisionOrigin.IMPORTED
    )
    session.commit()

    detail = library.start_library_processing(
        session, material.id, ProcessingStart(parser_mode=ParserMode.FAST)
    )

    assert detail.task is not None
    task_checkpoint = library.latest_task(session, material.id)
    assert task_checkpoint is not None
    assert task_checkpoint.checkpoint["revision"] == 2
    assert task_checkpoint.checkpoint["source_revision"] == 1
    assert task_checkpoint.checkpoint["selected_pages"] == [1]
    assert task_checkpoint.total == 1


def test_timed_fragments_survive_rebuild(session: Session) -> None:
    material = make_material(session, "aa")
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=1,
        page_number=1,
        width=595,
        height=842,
        text="Первый сегмент",
        markdown="Первый сегмент",
        quality=PageQuality.NATIVE,
        elements=[
            {
                "kind": "paragraph",
                "text": "Первый сегмент",
                "bbox": [0, 0, 1, 0.1],
                "level": None,
                "confidence": None,
                "time_from": 12.5,
                "time_to": 18.0,
                "asset_path": None,
            }
        ],
        diagnostics=[],
    )
    session.add(page)
    session.commit()

    library.rebuild_structure(session, material.id, 1)
    session.commit()

    fragment = session.scalars(select(MaterialFragment)).one()
    assert (fragment.time_from, fragment.time_to) == (12.5, 18.0)
    read = library.read_library_page(session, material.id, 1)
    assert read.fragments[0].time_from == 12.5
    assert read.fragments[0].time_to == 18.0
