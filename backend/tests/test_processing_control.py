"""Управление задачей разбора: отмена и видимость строящейся ревизии.

Оба сценария взяты из реальных багов OCR: паузу нельзя было отменить, а при
частичном переразборе непереразбираемые страницы показывались пустыми.
"""

from uuid import uuid4

import pytest
from conftest import add_page_with_fragments, make_material
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materials import library
from app.materials.parsers.base import ParsedElement
from app.materials.worker import _prepare_revision
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    MaterialPage,
    MaterialState,
    PageQuality,
    ParserMode,
    ProcessingStage,
    utc_now,
)
from app.projects.errors import ProjectConflictError


def _element(text: str) -> dict:
    return library.element_to_json(
        ParsedElement("paragraph", text, (0.0, 0.0, 1.0, 0.1), recognition_source="native")
    )


def _add_page(
    session: Session, material: Material, *, revision: int, page_number: int, text: str
) -> None:
    session.add(
        MaterialPage(
            id=uuid4(),
            material_id=material.id,
            revision=revision,
            page_number=page_number,
            width=595,
            height=842,
            text=text,
            markdown=text,
            quality=PageQuality.NATIVE,
            confidence=None,
            elements=[_element(text)],
            diagnostics=[],
            created_at=utc_now(),
        )
    )


def _task(material: Material, *, state: BackgroundJobState, selected: list[int]) -> BackgroundJob:
    now = utc_now()
    return BackgroundJob(
        id=uuid4(),
        material_id=material.id,
        kind=BackgroundJobKind.PARSE,
        state=state,
        stage=ProcessingStage.EXTRACT,
        parser_mode=ParserMode.FAST,
        done=0,
        total=len(selected),
        checkpoint={
            "revision": 2,
            "source_revision": 1,
            "selected_pages": selected,
            "next_index": 0,
            "scope": {"kind": "all"},
        },
        diagnostics=[],
        pause_requested=state == BackgroundJobState.PAUSED,
        created_at=now,
        updated_at=now,
    )


def test_cancel_discards_building_revision_and_frees_material(session: Session) -> None:
    material = make_material(session, "ca11")  # active_parse_revision=1, status READY
    material.page_count = 1
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Активная страница"]
    )
    # Строящаяся ревизия 2 с уже сохранённой страницей и её фрагментами.
    _add_page(session, material, revision=2, page_number=1, text="Черновик новой версии")
    session.flush()
    building = session.scalar(
        select(MaterialPage).where(
            MaterialPage.material_id == material.id, MaterialPage.revision == 2
        )
    )
    library.rebuild_checkpoint_page(session, building)
    task = _task(material, state=BackgroundJobState.PAUSED, selected=[1])
    session.add(task)
    session.commit()

    detail = library.control_library_task(session, material.id, "cancel")

    session.expire_all()
    assert session.get(BackgroundJob, task.id) is None
    assert (
        session.scalar(
            select(MaterialPage).where(
                MaterialPage.material_id == material.id, MaterialPage.revision == 2
            )
        )
        is None
    )
    refreshed = session.get(Material, material.id)
    assert refreshed.active_parse_revision == 1
    assert refreshed.status == MaterialState.READY
    # Активная версия и её страница целы.
    assert (
        session.scalar(
            select(MaterialPage).where(
                MaterialPage.material_id == material.id, MaterialPage.revision == 1
            )
        )
        is not None
    )
    assert detail.task is None


def test_cancel_of_first_parse_returns_material_to_ready_to_process(session: Session) -> None:
    material = make_material(session, "ca12")
    material.active_parse_revision = 0
    material.status = MaterialState.PAUSED
    material.page_count = 1
    _add_page(session, material, revision=1, page_number=1, text="Первый разбор")
    task = _task(material, state=BackgroundJobState.PAUSED, selected=[1])
    task.checkpoint = {**task.checkpoint, "revision": 1, "source_revision": 0}
    session.add(task)
    session.commit()

    library.control_library_task(session, material.id, "cancel")

    session.expire_all()
    assert session.get(BackgroundJob, task.id) is None
    assert session.get(Material, material.id).status == MaterialState.READY_TO_PROCESS


def test_cancel_is_rejected_for_completed_task(session: Session) -> None:
    material = make_material(session, "ca13")
    task = _task(material, state=BackgroundJobState.COMPLETED, selected=[1])
    session.add(task)
    session.commit()

    with pytest.raises(ProjectConflictError) as error:
        library.control_library_task(session, material.id, "cancel")
    assert error.value.code == "task_action_invalid"


def test_copied_page_is_readable_in_building_revision(session: Session) -> None:
    """Частичный переразбор: непереразбираемая страница должна показывать текст.

    Баг «текста нет» — при просмотре строящейся ревизии по task_id скопированные
    страницы не имели фрагментов, потому что `copy_page` их не строил.
    """
    material = make_material(session, "cb01")  # active_parse_revision=1
    material.page_count = 2
    _add_page(session, material, revision=1, page_number=1, text="Страница один")
    _add_page(session, material, revision=1, page_number=2, text="Страница два, её не трогаем")
    # Переразбираем только страницу 1; страница 2 копируется в ревизию 2.
    task = _task(material, state=BackgroundJobState.RUNNING, selected=[1])
    session.add(task)
    session.commit()

    _prepare_revision(session, task.id)

    page_two = library.read_library_page(session, material.id, 2, task_id=task.id)
    assert page_two.fragments, "скопированная страница должна иметь фрагменты, а не «текста нет»"
    assert page_two.fragments[0].text == "Страница два, её не трогаем"
