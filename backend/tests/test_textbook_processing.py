from uuid import uuid4

import pytest
from conftest import add_page_with_fragments, make_material
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materials import library, service
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
from app.projects.errors import ProjectConflictError


def test_textbook_mode_is_rejected_with_health_reason(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = make_material(session, "a15")
    monkeypatch.setattr(
        textbook,
        "status",
        lambda: textbook.TextbookStatus(False, "Локально · GPU", "Сервис не запущен"),
    )

    with pytest.raises(ProjectConflictError) as error:
        library.start_processing_core(
            session,
            material.id,
            ProcessingStart(parser_mode=ParserMode.TEXTBOOK),
        )

    assert error.value.code == "parser_mode_unavailable"
    assert str(error.value) == "Сервис не запущен"


def test_capabilities_report_active_textbook_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        textbook,
        "status",
        lambda: textbook.TextbookStatus(
            True,
            "PaddleOCR-VL-1.6-0.9B · RTX 5060 · FP16",
            "",
        ),
    )

    result = service.capabilities()

    assert result.textbook_available is True
    assert result.textbook_label == "PaddleOCR-VL-1.6-0.9B · RTX 5060 · FP16"
    assert result.textbook_reason == ""


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
