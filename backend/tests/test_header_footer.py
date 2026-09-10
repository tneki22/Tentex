from pathlib import Path
from uuid import uuid4

import pytest
from conftest import make_exam_project, make_topic_node
from PIL import Image, ImageDraw
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.materials import library
from app.materials.header_footer import HeaderFooterApplyWrite, apply, detect, preview
from app.materials.revisions import record_revision
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialRevision,
    MaterialRevisionOrigin,
    MaterialSourceKind,
    MaterialState,
    PageQuality,
    ProjectMaterial,
    SourceRole,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError


def element(
    text: str,
    bbox: list[float],
    *,
    kind: str = "paragraph",
    asset_path: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "text": text,
        "bbox": bbox,
        "level": None,
        "confidence": None,
        "asset_path": asset_path,
        "recognition_source": "native",
    }


def page(number: int, elements: list[dict[str, object]]) -> MaterialPage:
    return MaterialPage(
        id=uuid4(),
        material_id=uuid4(),
        revision=1,
        page_number=number,
        width=595,
        height=842,
        text="\n".join(str(item["text"]) for item in elements),
        markdown="\n\n".join(str(item["text"]) for item in elements),
        quality=PageQuality.NATIVE,
        elements=elements,
        diagnostics=[],
    )


def kinds(pages: list[MaterialPage]) -> dict[str, list[list[int]]]:
    result: dict[str, list[list[int]]] = {}
    for candidate in detect(pages):
        result.setdefault(candidate.kind, []).append(
            [item.page for item in candidate.occurrences]
        )
    return result


def test_detects_repeated_text_numbers_missing_edges_and_ocr_typo() -> None:
    pages = []
    for number in range(1, 8):
        items = [element("Содержательный текст", [0.1, 0.3, 0.8, 0.4])]
        if number not in {1, 7}:
            header = "Операционнне системы" if number == 4 else "Операционные системы"
            items += [
                element(header, [0.08, 0.035, 0.42, 0.06]),
                element(str(number), [0.48, 0.94, 0.52, 0.97]),
            ]
        pages.append(page(number, items))

    found = kinds(pages)
    assert found["header"] == [[2, 3, 4, 5, 6]]
    assert found["page_number"] == [[2, 3, 4, 5, 6]]


def test_detects_even_odd_templates_and_chapter_changes() -> None:
    pages = []
    for number in range(1, 9):
        chapter = "Глава первая" if number <= 4 else "Глава вторая"
        side = "Левая полоса" if number % 2 == 0 else "Правая полоса"
        pages.append(
            page(
                number,
                [
                    element(chapter, [0.1, 0.03, 0.35, 0.055]),
                    element(side, [0.62, 0.94, 0.9, 0.965]),
                ],
            )
        )

    found = kinds(pages)
    assert [1, 2, 3, 4] in found["header"]
    assert [5, 6, 7, 8] in found["header"]
    assert [2, 4, 6, 8] in found["footer"]
    assert [1, 3, 5, 7] in found["footer"]


def test_joins_split_line_and_rejects_unsafe_or_irrelevant_text() -> None:
    pages = [
        page(
            number,
            [
                element("ИУ-6", [0.08, 0.94, 0.16, 0.965]),
                element("Кафедра", [0.17, 0.94, 0.3, 0.965]),
                element("Повтор в середине", [0.1, 0.5, 0.5, 0.54]),
                element("Название раздела", [0.1, 0.03, 0.6, 0.07], kind="heading"),
                element("Колонтитул\nСодержательный абзац", [0.1, 0.01, 0.8, 0.075]),
                *(
                    [element("Одиночная строка", [0.6, 0.95, 0.9, 0.97])]
                    if number == 1
                    else []
                ),
            ],
        )
        for number in range(1, 5)
    ]

    candidates = detect(pages)
    assert len(candidates) == 1
    assert candidates[0].occurrences[0].text == "ИУ-6 Кафедра"
    assert all(len(item.indexes) == 2 for item in candidates[0].occurrences)


def test_repeated_image_uses_average_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    asset_dir = tmp_path / "storage" / "assets"
    asset_dir.mkdir(parents=True)
    paths = []
    for number in range(1, 5):
        image = Image.new("L", (64, 24), "white")
        ImageDraw.Draw(image).rectangle((4 + number % 2, 4, 28 + number % 2, 19), fill="black")
        path = asset_dir / f"logo-{number}.png"
        image.save(path)
        paths.append(path.relative_to(tmp_path / "storage").as_posix())
    different_paths = []
    for number in range(1, 5):
        different = Image.new("L", (64, 24), "white")
        start = 2 + (number - 1) * 15
        ImageDraw.Draw(different).rectangle((start, 3, start + 8, 21), fill="black")
        different_path = asset_dir / f"different-{number}.png"
        different.save(different_path)
        different_paths.append(different_path.relative_to(tmp_path / "storage").as_posix())

    pages = [
        page(
            number,
            [
                element(
                    "[Изображение]",
                    [0.08, 0.02, 0.25, 0.08],
                    kind="image",
                    asset_path=paths[number - 1],
                ),
                element(
                    "[Изображение]",
                    [0.7, 0.92, 0.9, 0.98],
                    kind="image",
                    asset_path=different_paths[number - 1],
                ),
            ],
        )
        for number in range(1, 5)
    ]

    found = kinds(pages)
    assert found["header"] == [[1, 2, 3, 4]]
    assert "footer" not in found


def _stored_material(session: Session) -> Material:
    material = Material(
        id=uuid4(),
        sha256="1" * 64,
        original_name="Пособие.pdf",
        storage_path="materials/test.pdf",
        media_type="application/pdf",
        source_kind=MaterialSourceKind.FILE,
        size_bytes=100,
        page_count=3,
        status=MaterialState.READY,
        active_parse_revision=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(material)
    for number in range(1, 4):
        stored_page = page(
            number,
            [
                element("Повторяющийся колонтитул", [0.1, 0.03, 0.7, 0.06]),
                element(f"Текст страницы {number}", [0.1, 0.3, 0.8, 0.4]),
            ],
        )
        stored_page.material_id = material.id
        session.add(stored_page)
    session.flush()
    from app.materials.library import rebuild_structure

    rebuild_structure(session, material.id, 1)
    record_revision(
        session,
        material.id,
        1,
        origin=MaterialRevisionOrigin.IMPORTED,
        source_storage_path=material.storage_path,
        source_hash=material.sha256,
    )
    session.commit()
    return material


def test_preview_is_read_only_and_apply_creates_one_revision(session: Session) -> None:
    material = _stored_material(session)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    session.add(
        ProjectMaterial(
            project_id=project.id,
            material_id=material.id,
            source_role=SourceRole.MAIN,
            purposes=["study_source"],
        )
    )
    old_fragments = list(
        session.scalars(
            select(MaterialFragment)
            .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
            .where(
                MaterialFragment.material_id == material.id,
                MaterialPage.revision == 1,
                MaterialPage.page_number == 1,
            )
            .order_by(MaterialFragment.sort_order)
        )
    )
    header_binding = Binding(
        project_id=project.id,
        program_node_id=node.id,
        fragment_id=old_fragments[0].id,
        material_id=material.id,
        block_id=old_fragments[0].block_id,
        status=BindingStatus.CONFIRMED,
        mechanism=BindingMechanism.MANUAL,
    )
    body_binding = Binding(
        project_id=project.id,
        program_node_id=node.id,
        fragment_id=old_fragments[1].id,
        material_id=material.id,
        block_id=old_fragments[1].block_id,
        status=BindingStatus.CONFIRMED,
        mechanism=BindingMechanism.MANUAL,
    )
    session.add_all([header_binding, body_binding])
    session.commit()
    before_pages = session.scalar(select(func.count()).select_from(MaterialPage))
    result = preview(session, material.id)
    assert len(result.candidates) == 1
    assert result.candidates[0].binding_count == 1
    assert session.scalar(select(func.count()).select_from(MaterialPage)) == before_pages

    applied = apply(
        session,
        material.id,
        HeaderFooterApplyWrite(
            expected_revision=result.revision,
            candidate_ids=[result.candidates[0].id],
        ),
    )
    assert applied.revision == 2
    assert session.scalar(select(func.count()).select_from(MaterialRevision)) == 2
    assert session.scalar(select(func.count()).select_from(MaterialPage)) == 6
    old_text = "\n".join(
        session.scalars(
            select(MaterialPage.text).where(
                MaterialPage.material_id == material.id,
                MaterialPage.revision == 1,
            )
        )
    )
    new_text = "\n".join(
        session.scalars(
            select(MaterialPage.text).where(
                MaterialPage.material_id == material.id,
                MaterialPage.revision == 2,
            )
        )
    )
    assert "Повторяющийся колонтитул" in old_text
    assert "Повторяющийся колонтитул" not in new_text
    assert "Текст страницы 3" in new_text
    assert session.scalar(
        select(func.count()).select_from(MaterialFragment).where(
            MaterialFragment.material_id == material.id,
            MaterialFragment.text == "Повторяющийся колонтитул",
        )
    ) == 3
    assert session.scalar(select(func.count()).select_from(MaterialBlock)) >= 2
    session.refresh(header_binding)
    session.refresh(body_binding)
    assert header_binding.status == BindingStatus.ORPHANED
    assert body_binding.status == BindingStatus.CONFIRMED
    assert body_binding.fragment_id != old_fragments[1].id
    assert library.search_library_material(session, material.id, "колонтитул").hits == []
    assert library.search_library_material(session, material.id, "страницы").hits


def test_apply_rejects_stale_revision(session: Session) -> None:
    material = _stored_material(session)
    result = preview(session, material.id)
    material.active_parse_revision = 2
    session.commit()

    with pytest.raises(ProjectConflictError) as caught:
        apply(
            session,
            material.id,
            HeaderFooterApplyWrite(
                expected_revision=result.revision,
                candidate_ids=[result.candidates[0].id],
            ),
        )
    assert caught.value.code == "stale_material_revision"


def test_apply_rejects_unknown_selection(session: Session) -> None:
    material = _stored_material(session)

    with pytest.raises(ProjectDomainError) as caught:
        apply(
            session,
            material.id,
            HeaderFooterApplyWrite(expected_revision=1, candidate_ids=["missing"]),
        )
    assert caught.value.code == "header_footer_selection_invalid"
    assert material.active_parse_revision == 1
