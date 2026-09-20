from datetime import UTC, datetime

from conftest import link_material, make_exam_project, make_material
from sqlalchemy.orm import Session

from app.materials import library, service
from app.materials.schemas import (
    LibraryExternalMaterialCreate,
    LibraryMaterialAttachWrite,
    LibraryMaterialMetadataUpdate,
    MaterialUpdate,
)
from app.models import GoalPassport, MaterialSourceKind


def test_global_name_and_project_alias_follow_precedence(session: Session) -> None:
    project = make_exam_project(session)
    material = make_material(session, "d01")
    link_material(session, project, material)

    renamed = library.update_library_material_metadata(
        session,
        material.id,
        LibraryMaterialMetadataUpdate(display_name="Общее название"),
    )
    assert renamed.display_name == "Общее название"
    assert service.get_material(session, project.id, material.id).display_name == "Общее название"

    service.update_material(
        session, project.id, material.id, MaterialUpdate(display_name="Название проекта")
    )
    assert service.get_material(session, project.id, material.id).display_name == "Название проекта"

    service.update_material(
        session, project.id, material.id, MaterialUpdate(display_name=None)
    )
    assert service.get_material(session, project.id, material.id).display_name == "Общее название"


def test_attached_material_inherits_only_empty_project_subject(session: Session) -> None:
    project = make_exam_project(session)
    session.add(GoalPassport(project_id=project.id, subject="Физика"))
    empty = make_material(session, "d02")
    existing = make_material(session, "d03")
    existing.subject = "Математика"
    session.commit()

    library.attach_material_to_project(
        session, empty.id, LibraryMaterialAttachWrite(project_id=project.id)
    )
    library.attach_material_to_project(
        session, existing.id, LibraryMaterialAttachWrite(project_id=project.id)
    )

    assert session.get(type(empty), empty.id).subject == "Физика"
    assert session.get(type(existing), existing.id).subject == "Математика"


def test_source_refresh_preserves_custom_display_name(
    session: Session, monkeypatch
) -> None:
    material = make_material(session, "d04")
    material.source_kind = MaterialSourceKind.URL
    material.source_url = "https://example.org/article"
    material.display_name = "Моё название"
    session.commit()
    monkeypatch.setattr(
        library,
        "fetch_external",
        lambda _command: (
            "Новое исходное имя.md",
            "Полностью новый текст источника",
            "https://example.org/article",
            datetime.now(UTC).replace(tzinfo=None),
            MaterialSourceKind.URL,
        ),
    )

    result = library.refresh_source(session, material.id)

    assert result.changed is True
    assert result.material.original_name == "Новое исходное имя.md"
    assert result.material.display_name == "Моё название"


def test_new_external_material_accepts_subject(session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        library,
        "fetch_external",
        lambda _command: (
            "Статья.md",
            "Текст статьи",
            "https://example.org/article",
            datetime.now(UTC).replace(tzinfo=None),
            MaterialSourceKind.URL,
        ),
    )

    result = library.create_library_external(
        session,
        LibraryExternalMaterialCreate(
            kind="url", url="https://example.org/article", subject="Экономика"
        ),
    )

    assert result.subject == "Экономика"
    assert result.display_name == result.original_name
