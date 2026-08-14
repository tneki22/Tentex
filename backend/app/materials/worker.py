import argparse
import logging
import os
import socket
import time
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings.answers_link import link_answers_material
from app.bindings.search import reindex_material
from app.bindings.service import transfer_bindings_on_revision
from app.db import SessionLocal, upgrade_database
from app.logging_config import configure_logging
from app.materials import library
from app.materials import revisions as revision_registry
from app.materials.parsers.base import ParsedPage
from app.materials.parsers.native import extract_outline, iter_pages
from app.materials.schemas import MaterialPurpose
from app.materials.storage import material_path
from app.models import (
    Material,
    MaterialPage,
    MaterialRevisionOrigin,
    MaterialState,
    PageQuality,
    ProcessingStage,
    ProcessingTask,
    ProcessingTaskState,
    ProjectMaterial,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError

log = logging.getLogger("tentex.worker")

LEASE_SECONDS = 60


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _selected(task: ProcessingTask) -> list[int]:
    return [int(value) for value in task.checkpoint.get("selected_pages") or []]


def claim_task(session: Session, worker_id: str) -> ProcessingTask | None:
    now = utc_now()
    with session.begin():
        expired = list(
            session.scalars(
                select(ProcessingTask).where(
                    ProcessingTask.state == ProcessingTaskState.RUNNING,
                    ProcessingTask.lease_expires_at < now,
                )
            )
        )
        for task in expired:
            task.state = ProcessingTaskState.QUEUED
            task.lease_owner = None
            task.lease_expires_at = None
        task = session.scalar(
            select(ProcessingTask)
            .where(ProcessingTask.state == ProcessingTaskState.QUEUED)
            .order_by(ProcessingTask.created_at)
            .limit(1)
        )
        if task is None:
            return None
        task.state = ProcessingTaskState.RUNNING
        task.stage = ProcessingStage.EXTRACT
        task.lease_owner = worker_id
        task.heartbeat_at = now
        task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        task.updated_at = now
        material = session.get(Material, task.material_id)
        if material:
            material.status = MaterialState.PROCESSING
            material.outline = extract_outline(material_path(material.storage_path))
        session.flush()
        session.expunge(task)
        log.info("claimed task=%s material=%s total=%s", task.id, task.material_id, task.total)
        return task


def _prepare_revision(session: Session, task_id: UUID) -> None:
    """Скопировать в строящуюся ревизию страницы, которые не переразбираются.

    Частичный запуск обязан дать полную версию: иначе прежние страницы исчезли
    бы из активного разбора, а привязки к ним осиротели бы без всякой причины.
    """
    with session.begin():
        task = session.get(ProcessingTask, task_id)
        if task is None:
            return
        revision = int(task.checkpoint["revision"])
        source_revision = int(task.checkpoint.get("source_revision") or 0)
        if not source_revision:
            return
        selected = set(_selected(task))
        present = set(
            session.scalars(
                select(MaterialPage.page_number).where(
                    MaterialPage.material_id == task.material_id,
                    MaterialPage.revision == revision,
                )
            )
        )
        for page in session.scalars(
            select(MaterialPage)
            .where(
                MaterialPage.material_id == task.material_id,
                MaterialPage.revision == source_revision,
            )
            .order_by(MaterialPage.page_number)
        ):
            if page.page_number in selected or page.page_number in present:
                continue
            library.copy_page(session, page, revision)


def _save_page(session: Session, task_id: UUID, parsed: ParsedPage) -> bool:
    with session.begin():
        task = session.get(ProcessingTask, task_id)
        if task is None:
            return False
        checkpoint = dict(task.checkpoint)
        revision = int(checkpoint["revision"])
        selected = _selected(task)
        if parsed.page_number not in selected:
            # Страница не входит в область запуска: её копию уже положили в ревизию.
            return True
        existing = session.scalar(
            select(MaterialPage).where(
                MaterialPage.material_id == task.material_id,
                MaterialPage.revision == revision,
                MaterialPage.page_number == parsed.page_number,
            )
        )
        if existing is None:
            session.add(
                MaterialPage(
                    material_id=task.material_id,
                    revision=revision,
                    page_number=parsed.page_number,
                    width=parsed.width,
                    height=parsed.height,
                    text=parsed.plain_text,
                    markdown=parsed.markdown,
                    quality=PageQuality(parsed.quality),
                    confidence=parsed.confidence,
                    elements=[library.element_to_json(element) for element in parsed.elements],
                    diagnostics=list(parsed.diagnostics),
                    created_at=utc_now(),
                )
            )
        # Считаем по позиции в выбранном списке, а не по номеру страницы: у
        # диапазона и списка «нужно проверить» номера не начинаются с единицы.
        checkpoint["next_index"] = max(
            int(checkpoint.get("next_index", 0)), selected.index(parsed.page_number) + 1
        )
        task.checkpoint = checkpoint
        task.done = min(task.total, int(checkpoint["next_index"]))
        task.heartbeat_at = utc_now()
        task.lease_expires_at = utc_now() + timedelta(seconds=LEASE_SECONDS)
        task.updated_at = utc_now()
        if task.pause_requested:
            task.state = ProcessingTaskState.PAUSED
            task.lease_owner = None
            task.lease_expires_at = None
            material = session.get(Material, task.material_id)
            if material:
                material.status = MaterialState.PAUSED
            return False
        return True


def _link_answers_projects(session: Session, material_id: UUID) -> None:
    """Файл ответов после разбора сам ложится на вопросы и заполняет эталоны.

    Осечка автопривязки не должна ронять разбор: файл уже разобран и полезен,
    а связать его заново можно кнопкой в «Обработке».
    """
    links = list(
        session.scalars(select(ProjectMaterial).where(ProjectMaterial.material_id == material_id))
    )
    for link in links:
        if MaterialPurpose.REFERENCE_ANSWERS.value not in (link.purposes or []):
            continue
        try:
            link_answers_material(session, link.project_id, material_id)
        except (ProjectConflictError, ProjectNotFoundError):
            continue


def _finish(session: Session, task_id: UUID) -> None:
    with session.begin():
        task = session.get(ProcessingTask, task_id)
        if task is None:
            return
        revision = int(task.checkpoint["revision"])
        task.stage = ProcessingStage.SEGMENT
        material = session.get(Material, task.material_id)
        if material is None:
            return
        previous_revision = material.active_parse_revision
        # Разбор заново — это новая ревизия, а не потеря работы: страницы и
        # фрагменты прошлой ревизии остаются, чтобы её можно было открыть и
        # восстановить, а привязки переносятся на новые фрагменты (Р6).
        old_fragments = library.fragments_by_page(session, task.material_id, previous_revision)
        new_fragments = library.rebuild_structure(session, task.material_id, revision)

        material.active_parse_revision = revision
        material.status = MaterialState.READY
        library.refresh_material_counters(session, material, revision)
        session.flush()
        if old_fragments:
            transfer_bindings_on_revision(
                session, task.material_id, old_fragments, new_fragments
            )
        reindex_material(session, task.material_id)

        storage_path, source_hash = revision_registry.inherit_source(
            session, material, previous_revision or None
        )
        summary = revision_registry.revision_summary(session, task.material_id, revision)
        summary["changed_pages"] = len(_selected(task))
        revision_registry.record_revision(
            session,
            task.material_id,
            revision,
            origin=(
                MaterialRevisionOrigin.PARSE
                if previous_revision
                else MaterialRevisionOrigin.IMPORTED
            ),
            parser_mode=task.parser_mode,
            parent_revision=previous_revision or None,
            task_id=task.id,
            source_storage_path=storage_path,
            source_hash=source_hash,
            scope=dict(task.checkpoint.get("scope") or {"kind": "all"}),
            summary=summary,
        )
        _link_answers_projects(session, task.material_id)

        task.state = ProcessingTaskState.COMPLETED
        task.stage = ProcessingStage.COMPLETE
        task.done = task.total
        task.lease_owner = None
        task.lease_expires_at = None
        task.completed_at = utc_now()
        task.updated_at = utc_now()


def process_task(session: Session, task: ProcessingTask) -> None:
    try:
        material = session.get(Material, task.material_id)
        if material is None:
            return
        source_path = material_path(material.storage_path)
        parser_mode = task.parser_mode
        selected = _selected(task)
        next_index = int(task.checkpoint.get("next_index", 0))
        # SQLAlchemy starts a read transaction for session.get(); page checkpoints
        # need their own short transactions so a stopped worker never loses a page.
        session.rollback()
        _prepare_revision(session, task.id)
        if next_index < len(selected):
            for page in iter_pages(source_path, parser_mode, selected[next_index]):
                if not _save_page(session, task.id, page):
                    return
        _finish(session, task.id)
    except Exception as error:
        session.rollback()
        log.exception("task failed material=%s: %s", task.material_id, error)
        with session.begin():
            failed = session.get(ProcessingTask, task.id)
            material = session.get(Material, task.material_id)
            if failed:
                failed.state = ProcessingTaskState.FAILED
                failed.error = str(error)
                failed.lease_owner = None
                failed.lease_expires_at = None
                failed.updated_at = utc_now()
            if material:
                # Прежняя активная версия остаётся на месте: ошибка обработки не
                # должна отбирать у пользователя то, что уже было готово.
                material.status = MaterialState.FAILED
                material.error = str(error)


def run_once() -> bool:
    with SessionLocal() as session:
        worker_id = _worker_id()
        task = claim_task(session, worker_id)
        if task is None:
            return False
        started = time.perf_counter()
        process_task(session, task)
        log.info(
            "processed task=%s material=%s %.1fms",
            task.id,
            task.material_id,
            (time.perf_counter() - started) * 1000,
        )
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    upgrade_database()
    configure_logging()
    if args.once:
        run_once()
        return
    while True:
        if not run_once():
            time.sleep(0.75)


if __name__ == "__main__":
    main()
