from pathlib import Path
from uuid import uuid4

import pytest
from conftest import add_page_with_fragments, make_material
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.materials import library
from app.materials.parsers import textbook
from app.materials.parsers.base import ParsedElement, ParsedPage
from app.materials.schemas import ProcessingStart
from app.materials.worker import _save_page, process_task
from app.models import (
    MaterialPage,
    MaterialRevision,
    MaterialState,
    ParserMode,
    ProcessingStage,
    ProcessingTask,
    ProcessingTaskKind,
    ProcessingTaskState,
    utc_now,
)
from app.ocr import downloads, hardware, service_control
from app.ocr import settings as ocr_settings
from app.projects.errors import ProjectConflictError


def test_textbook_mode_is_rejected_when_models_are_not_installed(
    session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Пустая установка не должна пускать в режим, которым нечем считать."""
    material = make_material(session, "a15")
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    hardware.reset_cache()

    with pytest.raises(ProjectConflictError) as error:
        library.start_processing_core(
            session,
            material.id,
            ProcessingStart(parser_mode=ParserMode.TEXTBOOK),
        )

    assert error.value.code == "parser_mode_unavailable"
    assert "модел" in str(error.value).lower()


def test_textbook_mode_is_rejected_when_service_is_down(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = make_material(session, "a15b")
    monkeypatch.setattr(downloads, "engine_ready", lambda engine: True)
    monkeypatch.setattr(
        textbook,
        "status",
        lambda *, base_url=None: textbook.TextbookStatus(False, "", "Сервис не отвечает."),
    )
    monkeypatch.setattr(
        service_control,
        "describe",
        lambda: service_control.ServiceStatus("stopped", "Сервис не запущен", can_start=True),
    )

    with pytest.raises(ProjectConflictError) as error:
        library.start_processing_core(
            session,
            material.id,
            ProcessingStart(parser_mode=ParserMode.TEXTBOOK),
        )

    assert error.value.code == "parser_mode_unavailable"
    assert str(error.value) == "Сервис не запущен"


def test_registry_reports_active_textbook_executor(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Что именно считает — видно на экране настроек, а не только в логах."""
    monkeypatch.setattr(downloads, "engine_ready", lambda engine: True)
    monkeypatch.setattr(
        textbook,
        "status",
        lambda *, base_url=None: textbook.TextbookStatus(
            True,
            "PP-StructureV3 + PP-FormulaNet Plus M",
            "",
            "PP-StructureV3 + PP-FormulaNet Plus M",
        ),
    )
    monkeypatch.setattr(
        service_control,
        "describe",
        lambda: service_control.ServiceStatus("running", "Сервис работает", can_stop=True),
    )
    monkeypatch.setattr(service_control, "environment_applied", lambda environment: True)

    engine = next(
        item for item in ocr_settings.read_settings(session).engines if item.mode == "textbook"
    )

    assert engine.readiness == "ready"
    assert engine.available is True
    assert engine.active_label == "PP-StructureV3 + PP-FormulaNet Plus M"
    assert engine.service is not None
    assert engine.service.can_stop is True


def test_gpu_failure_does_not_activate_incomplete_revision(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = make_material(session, "a16")
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Прежняя активная версия"],
    )
    now = utc_now()
    task = ProcessingTask(
        id=uuid4(),
        material_id=material.id,
        kind=ProcessingTaskKind.PARSE,
        state=ProcessingTaskState.RUNNING,
        stage=ProcessingStage.EXTRACT,
        parser_mode=ParserMode.TEXTBOOK,
        done=0,
        total=1,
        checkpoint={
            "revision": 2,
            "source_revision": 1,
            "selected_pages": [1],
            "next_index": 0,
            "scope": {"kind": "all"},
        },
        diagnostics=[],
        pause_requested=False,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.commit()
    monkeypatch.setattr(
        "app.materials.worker.iter_pages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("CUDA OOM")),
    )

    process_task(session, task)

    session.expire_all()
    assert session.get(type(material), material.id).active_parse_revision == 1
    assert session.get(type(material), material.id).status == MaterialState.FAILED
    assert session.get(ProcessingTask, task.id).state == ProcessingTaskState.FAILED
    assert session.scalar(
        select(MaterialPage).where(
            MaterialPage.material_id == material.id,
            MaterialPage.revision == 2,
        )
    ) is None
    assert session.scalar(
        select(MaterialRevision).where(
            MaterialRevision.material_id == material.id,
            MaterialRevision.revision == 2,
        )
    ) is None


def test_checkpoint_page_is_readable_before_revision_activation(session: Session) -> None:
    material = make_material(session, "a17")
    now = utc_now()
    task = ProcessingTask(
        id=uuid4(),
        material_id=material.id,
        kind=ProcessingTaskKind.PARSE,
        state=ProcessingTaskState.RUNNING,
        stage=ProcessingStage.EXTRACT,
        parser_mode=ParserMode.TEXTBOOK,
        done=0,
        total=1,
        checkpoint={
            "revision": 2,
            "source_revision": 1,
            "selected_pages": [1],
            "next_index": 0,
            "scope": {"kind": "all"},
        },
        diagnostics=[],
        pause_requested=False,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.commit()

    parsed = ParsedPage(
        page_number=1,
        width=100,
        height=200,
        markdown="Распознанная страница",
        plain_text="Распознанная страница",
        quality="ocr",
        elements=(
            ParsedElement(
                kind="paragraph",
                text="Распознанная страница",
                bbox=(0, 0, 100, 20),
                confidence=0.91,
                recognition_source="vl",
            ),
        ),
        confidence=0.91,
    )

    assert _save_page(session, task.id, parsed) is True

    page = library.read_library_page(
        session, material.id, 1, task_id=task.id
    )
    assert page.text == "Распознанная страница"
    assert page.fragments[0].recognition_source == "vl"
    assert page.fragments[0].confidence == 0.91
    assert session.get(ProcessingTask, task.id).done == 1
    assert session.get(type(material), material.id).active_parse_revision == 1
