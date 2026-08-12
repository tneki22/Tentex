import argparse
import logging
import os
import socket
import time
from collections import defaultdict
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.bindings.answers_link import link_answers_material
from app.bindings.search import reindex_material
from app.bindings.service import transfer_bindings_on_revision
from app.db import SessionLocal, upgrade_database
from app.logging_config import configure_logging
from app.materials.parsers.base import ParsedPage
from app.materials.parsers.native import extract_outline, iter_pages
from app.materials.schemas import MaterialPurpose
from app.materials.segmentation import build_blocks
from app.materials.storage import material_path
from app.models import (
    Binding,
    BlockClass,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
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


def _save_page(session: Session, task_id: UUID, parsed: ParsedPage) -> bool:
    with session.begin():
        task = session.get(ProcessingTask, task_id)
        if task is None:
            return False
        revision = int(task.checkpoint["revision"])
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
                    elements=[
                        {
                            "kind": element.kind,
                            "text": element.text,
                            "bbox": list(element.bbox),
                            "level": element.level,
                            "confidence": element.confidence,
                            "time_from": element.time_from,
                            "time_to": element.time_to,
                            "asset_path": element.asset_path,
                        }
                        for element in parsed.elements
                    ],
                    diagnostics=list(parsed.diagnostics),
                    created_at=utc_now(),
                )
            )
        task.done = parsed.page_number
        task.checkpoint = {"revision": revision, "next_page": parsed.page_number + 1}
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


def _drop_unbound_fragments(
    session: Session,
    material_id: UUID,
    old_fragments_by_page: dict[int, list[MaterialFragment]],
) -> None:
    """Прошлую ревизию чистим, но оставляем то, за что держатся осиротевшие привязки."""
    session.flush()
    referenced = set(
        session.scalars(select(Binding.fragment_id).where(Binding.material_id == material_id))
    )
    stale = [
        fragment.id
        for fragments in old_fragments_by_page.values()
        for fragment in fragments
        if fragment.id not in referenced
    ]
    if stale:
        session.execute(delete(MaterialFragment).where(MaterialFragment.id.in_(stale)))


def _finish(session: Session, task_id: UUID) -> None:
    with session.begin():
        task = session.get(ProcessingTask, task_id)
        if task is None:
            return
        revision = int(task.checkpoint["revision"])
        task.stage = ProcessingStage.SEGMENT
        pages = list(
            session.scalars(
                select(MaterialPage)
                .where(
                    MaterialPage.material_id == task.material_id,
                    MaterialPage.revision == revision,
                )
                .order_by(MaterialPage.page_number)
            )
        )
        from app.materials.parsers.base import ParsedElement

        parsed_pages = [
            ParsedPage(
                page.page_number,
                page.width,
                page.height,
                page.markdown,
                page.text,
                page.quality.value,
                tuple(
                    ParsedElement(
                        element["kind"],
                        element["text"],
                        tuple(element["bbox"]),
                        element.get("level"),
                        element.get("confidence"),
                        element.get("time_from"),
                        element.get("time_to"),
                        element.get("asset_path"),
                    )
                    for element in page.elements
                ),
                tuple(page.diagnostics),
                page.confidence,
            )
            for page in pages
        ]
        material = session.get(Material, task.material_id)
        previous_revision = material.active_parse_revision if material else 0
        # Разбор заново — это новая ревизия, а не потеря работы: фрагменты прошлой
        # ревизии держим до переноса привязок (Р6), иначе каскад по FK снёс бы их.
        old_fragments_by_page: dict[int, list[MaterialFragment]] = defaultdict(list)
        if previous_revision:
            for fragment, page_number in session.execute(
                select(MaterialFragment, MaterialPage.page_number)
                .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
                .where(
                    MaterialFragment.material_id == task.material_id,
                    MaterialPage.revision == previous_revision,
                )
                .order_by(MaterialFragment.sort_order)
            ).all():
                old_fragments_by_page[page_number].append(fragment)

        # Повторный вызов после сбоя не должен удваивать фрагменты этой же ревизии.
        session.execute(
            delete(MaterialFragment).where(
                MaterialFragment.id.in_(
                    select(MaterialFragment.id)
                    .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
                    .where(
                        MaterialFragment.material_id == task.material_id,
                        MaterialPage.revision == revision,
                    )
                )
            )
        )
        session.execute(
            delete(MaterialBlock).where(
                MaterialBlock.material_id == task.material_id,
                MaterialBlock.revision == revision,
            )
        )
        page_by_number = {page.page_number: page for page in pages}
        new_fragments_by_page: dict[int, list[MaterialFragment]] = defaultdict(list)
        page_orders: dict[int, int] = {}
        for block_order, spec in enumerate(build_blocks(parsed_pages)):
            page_numbers = [page_number for page_number, _ in spec.elements] or [1]
            block = MaterialBlock(
                material_id=task.material_id,
                revision=revision,
                sort_order=block_order,
                title=spec.title,
                block_class=BlockClass.SERVICE if spec.service_reason else BlockClass.CONTENT,
                service_reason=spec.service_reason,
                page_from=min(page_numbers),
                page_to=max(page_numbers),
            )
            session.add(block)
            session.flush()
            for page_number, element in spec.elements:
                page = page_by_number[page_number]
                order = page_orders.get(page_number, 0)
                fragment = MaterialFragment(
                    material_id=task.material_id,
                    page_id=page.id,
                    block_id=block.id,
                    sort_order=order,
                    text=element.text,
                    bbox=list(element.bbox),
                    element_kind=element.kind,
                    structure_level=element.level,
                    asset_path=element.asset_path,
                    degraded_structure=not any(
                        item.get("kind") == "heading" for item in page.elements
                    ),
                    quality=page.quality,
                )
                session.add(fragment)
                new_fragments_by_page[page_number].append(fragment)
                page_orders[page_number] = order + 1
        if material:
            material.active_parse_revision = revision
            material.status = MaterialState.READY
            material.ocr_low_page_count = sum(page.quality == PageQuality.OCR_LOW for page in pages)
            material.diagnostics = sorted({item for page in pages for item in page.diagnostics})
            material.error = None
            session.flush()
            if old_fragments_by_page:
                transfer_bindings_on_revision(
                    session, task.material_id, old_fragments_by_page, new_fragments_by_page
                )
                _drop_unbound_fragments(session, task.material_id, old_fragments_by_page)
            reindex_material(session, task.material_id)
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
        start_page = int(task.checkpoint.get("next_page", 1))
        # SQLAlchemy starts a read transaction for session.get(); page checkpoints
        # need their own short transactions so a stopped worker never loses a page.
        session.rollback()
        for page in iter_pages(source_path, parser_mode, start_page):
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
