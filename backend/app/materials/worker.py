import argparse
import hashlib
import logging
import os
import shutil
import socket
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.jobs import process_ai_job
from app.bindings.answers_link import link_answers_material
from app.bindings.search import reindex_material
from app.bindings.service import transfer_bindings_on_revision
from app.db import SessionLocal, upgrade_database
from app.logging_config import configure_logging
from app.materials import library
from app.materials import revisions as revision_registry
from app.materials.parsers.base import ParsedPage
from app.materials.parsers.cloud_vlm import CloudRecognizer
from app.materials.parsers.native import extract_outline, iter_pages, text_layer_pages
from app.materials.schemas import MaterialPurpose
from app.materials.storage import material_path
from app.materials.typst import (
    CompileResult,
    compile_bundle,
    extract_bundle,
    missing_packages,
    package_issues,
    source_chunks,
)
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    MaterialPage,
    MaterialRevisionOrigin,
    MaterialState,
    PageQuality,
    ParserMode,
    ProcessingStage,
    ProjectMaterial,
    TypstMaterial,
    TypstSourceChunk,
    utc_now,
)
from app.ocr import settings as ocr_settings
from app.projects.errors import ProjectConflictError, ProjectNotFoundError

log = logging.getLogger("tentex.worker")

LEASE_SECONDS = 60


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _selected(task: BackgroundJob) -> list[int]:
    return [int(value) for value in task.checkpoint.get("selected_pages") or []]


def claim_job(session: Session, worker_id: str) -> BackgroundJob | None:
    """Взять самую старую задачу в очереди — независимо от её вида (`kind`).

    ВНИМАНИЕ (известное ограничение, не чинится в этом заходе): выбор читает
    строку и пишет в неё в одной транзакции. Два воркера (`--scale worker=2`)
    могут прочитать одну и ту же `queued`-строку до того, как первый успеет
    выставить `state=running`, и оба возьмутся за одну задачу. Для одного
    пользователя на одной машине это не заходит — лиз (`LEASE_SECONDS`)
    защищает только от мёртвого воркера. Безопасный второй воркер потребует
    условного взятия: `UPDATE ... WHERE id=? AND state='queued'` с проверкой
    `rowcount == 1` вместо read-then-write.
    """
    now = utc_now()
    with session.begin():
        expired = list(
            session.scalars(
                select(BackgroundJob).where(
                    BackgroundJob.state == BackgroundJobState.RUNNING,
                    BackgroundJob.lease_expires_at < now,
                )
            )
        )
        for expired_job in expired:
            expired_job.state = BackgroundJobState.QUEUED
            expired_job.lease_owner = None
            expired_job.lease_expires_at = None
        job = session.scalar(
            select(BackgroundJob)
            .where(BackgroundJob.state == BackgroundJobState.QUEUED)
            .order_by(BackgroundJob.created_at)
            .limit(1)
        )
        if job is None:
            return None
        job.state = BackgroundJobState.RUNNING
        job.lease_owner = worker_id
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        job.updated_at = now
        # Стадии extract/segment и статус материала осмысленны только у
        # разбора: у ролей ИИ и у link_answers material_id пустой.
        if job.kind == BackgroundJobKind.PARSE:
            job.stage = ProcessingStage.EXTRACT
            material = session.get(Material, job.material_id)
            if material:
                material.status = MaterialState.PROCESSING
                material.outline = extract_outline(material_path(material.storage_path))
        elif job.kind == BackgroundJobKind.TYPST_COMPILE:
            job.stage = ProcessingStage.EXTRACT
            material = session.get(Material, job.material_id)
            if material:
                material.status = MaterialState.PROCESSING
        session.flush()
        session.expunge(job)
        log.info("claimed job=%s kind=%s material=%s", job.id, job.kind, job.material_id)
        return job


def _prepare_revision(session: Session, task_id: UUID) -> None:
    """Скопировать в строящуюся ревизию страницы, которые не переразбираются.

    Частичный запуск обязан дать полную версию: иначе прежние страницы исчезли
    бы из активного разбора, а привязки к ним осиротели бы без всякой причины.
    """
    with session.begin():
        task = session.get(BackgroundJob, task_id)
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
            copied = library.copy_page(session, page, revision)
            # Скопированной странице сразу нужны фрагменты, иначе при просмотре
            # строящейся ревизии по task_id (пока идёт частичный переразбор) все
            # непереразбираемые страницы показывались бы пустыми — «текста нет».
            # Финальную структуру всё равно пересоберёт `rebuild_structure`.
            library.rebuild_checkpoint_page(session, copied)


def _save_page(session: Session, task_id: UUID, parsed: ParsedPage) -> bool:
    with session.begin():
        task = session.get(BackgroundJob, task_id)
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
            existing = MaterialPage(
                material_id=task.material_id,
                revision=revision,
                page_number=parsed.page_number,
                width=parsed.width,
                height=parsed.height,
                text=parsed.plain_text,
                markdown=parsed.markdown,
                quality=PageQuality(parsed.quality),
                confidence=parsed.confidence,
                # Текстовый слой обходится без распознавания — модели тут нет.
                parser_mode=task.parser_mode if parsed.quality != "native" else None,
                elements=[library.element_to_json(element) for element in parsed.elements],
                diagnostics=list(parsed.diagnostics),
                created_at=utc_now(),
            )
            session.add(existing)
            session.flush()
            library.rebuild_checkpoint_page(session, existing)
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
            task.state = BackgroundJobState.PAUSED
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
            result = link_answers_material(session, link.project_id, material_id)
            log.info(
                "answer matching completed",
                extra={
                    "project_id": str(link.project_id),
                    "material_id": str(material_id),
                    "expected": result.expected_questions,
                    "matched": len(result.matched_node_ids),
                    "available": len(result.available_node_ids),
                    "restored": result.restored_answers,
                    "preserved": result.preserved_answers,
                    "unresolved": len(result.ambiguous_sections),
                },
            )
        except (ProjectConflictError, ProjectNotFoundError):
            continue


def _finish(session: Session, task_id: UUID) -> None:
    with session.begin():
        task = session.get(BackgroundJob, task_id)
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
            transfer_bindings_on_revision(session, task.material_id, old_fragments, new_fragments)
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

        task.state = BackgroundJobState.COMPLETED
        task.stage = ProcessingStage.COMPLETE
        task.done = task.total
        task.lease_owner = None
        task.lease_expires_at = None
        task.completed_at = utc_now()
        task.updated_at = utc_now()


def process_parse_job(session: Session, task: BackgroundJob) -> None:
    """Довести задачу разбора материала (`BackgroundJobKind.PARSE`) до конца."""
    # Захватываются до первого rollback: он истощает (expire) атрибуты task,
    # а обращение к task.id/task.material_id между rollback и следующим явным
    # session.begin() тихо перечитывает их запросом и уже открытой транзакцией
    # сталкивается со следующим begin() — отсюда местные переменные, а не task.*.
    task_id = task.id
    material_id = task.material_id
    # Объявлена до try: ранний return до создания распознавателя не должен
    # мешать finally ниже проверить его на None.
    recognizer: CloudRecognizer | None = None
    try:
        material = session.get(Material, material_id)
        if material is None:
            return
        source_path = material_path(material.storage_path)
        parser_mode = task.parser_mode
        selected = _selected(task)
        next_index = int(task.checkpoint.get("next_index", 0))
        # SQLAlchemy starts a read transaction for session.get(); page checkpoints
        # need their own short transactions so a stopped worker never loses a page.
        session.rollback()
        params = ocr_settings.runtime_params(session)
        session.rollback()
        # Порт внешней модели заводится только для облачного разбора: локальные
        # режимы не должны и не могут дотянуться до шлюза.
        recognizer = (
            CloudRecognizer(session, params.quality_threshold)
            if parser_mode == ParserMode.CLOUD
            else None
        )
        _prepare_revision(session, task_id)
        if next_index < len(selected):
            remaining_pages = selected[next_index:]
            for page in iter_pages(
                source_path,
                parser_mode,
                remaining_pages[0],
                params=params,
                page_numbers=remaining_pages,
                recognizer=recognizer,
            ):
                if not _save_page(session, task_id, page):
                    return
        _finish(session, task_id)
    except Exception as error:
        session.rollback()
        log.exception("task failed material=%s: %s", material_id, error)
        with session.begin():
            failed = session.get(BackgroundJob, task_id)
            material = session.get(Material, material_id)
            if failed:
                failed.state = BackgroundJobState.FAILED
                failed.error = str(error)
                failed.lease_owner = None
                failed.lease_expires_at = None
                failed.updated_at = utc_now()
            if material:
                # Прежняя активная версия остаётся на месте: ошибка обработки не
                # должна отбирать у пользователя то, что уже было готово.
                material.status = MaterialState.FAILED
                material.error = str(error)
    finally:
        # Пауза, отмена или сбой — recognizer закрывается всегда, а не только
        # на счастливом пути: иначе общий event loop облачного разбора висит
        # до сборки мусора и заваливает лог `RuntimeError: Event loop is closed`.
        if recognizer is not None:
            recognizer.close()


def _mark_typst_input_needed(
    session: Session, task_id: UUID, issues: list[dict[str, object]]
) -> None:
    """Проблема, разрешимая пользователем, не считается падением сборки."""
    with session.begin():
        task = session.get(BackgroundJob, task_id)
        if task is None:
            return
        material = session.get(Material, task.material_id)
        row = session.get(TypstMaterial, task.material_id)
        if material:
            material.status = MaterialState.NEEDS_INPUT
            material.error = None
        if row:
            row.issues = issues
        task.state = BackgroundJobState.COMPLETED
        task.stage = ProcessingStage.COMPLETE
        task.done = task.total
        task.completed_at = utc_now()
        task.updated_at = utc_now()
        task.lease_owner = None
        task.lease_expires_at = None


def _save_typst_chunks(
    session: Session, material_id: UUID, revision: int, bundle: Path, entrypoint: str, pages: int
) -> None:
    """Сохраняет exact-code отдельной таблицей: FTS-представление к нему не подмешивается."""
    with tempfile.TemporaryDirectory(prefix="tentex-typst-source-") as raw:
        root = Path(raw)
        extract_bundle(bundle, root)
        chunks = source_chunks(root, entrypoint, pages)
    with session.begin():
        for order, chunk in enumerate(chunks):
            session.add(
                TypstSourceChunk(
                    material_id=material_id, revision=revision, sort_order=order, **chunk
                )
            )


# Проблемы сборки, которые снимает сам пользователь, а не правка исходника.
RESOLVABLE_TYPST_ISSUES = frozenset(("missing_file", "package"))


def _mark_typst_failed(
    session: Session,
    task_id: UUID,
    material_id: UUID,
    message: str,
    diagnostics: list[dict[str, object]],
) -> None:
    """Один путь падения на оба случая: и отказ компилятора, и сбой воркера.

    Активная ревизия не трогается: неудачная сборка не должна отбирать у
    пользователя тот PDF, который уже был собран.
    """
    with session.begin():
        failed = session.get(BackgroundJob, task_id)
        material = session.get(Material, material_id)
        row = session.get(TypstMaterial, material_id)
        if failed:
            failed.state = BackgroundJobState.FAILED
            failed.error = message
            failed.lease_owner = None
            failed.lease_expires_at = None
            failed.updated_at = utc_now()
        if material:
            material.status = MaterialState.FAILED
            material.error = message
        if row:
            row.issues = diagnostics


def _register_typst_build(
    session: Session,
    material_id: UUID,
    revision: int,
    result: CompileResult,
    render_path: str,
    pages: int,
) -> None:
    """Отмечает уже активированную ревизию как собранную: PDF, версия, проблемы."""
    with session.begin():
        material = session.get(Material, material_id)
        row = session.get(TypstMaterial, material_id)
        revision_registry.require_revision(
            session, material_id, revision
        ).render_storage_path = render_path
        if material:
            material.status = MaterialState.READY
            material.error = None
            # До сборки числа страниц у Typst-проекта нет: оно появляется только
            # вместе с PDF, а Библиотека показывает его в карточке.
            material.page_count = pages
        if row:
            row.current_pdf_path = render_path
            row.compiler_version = result.compiler_version
            row.build_hash = hashlib.sha256(material_path(render_path).read_bytes()).hexdigest()
            row.issues = result.diagnostics


def process_typst_compile_job(session: Session, task: BackgroundJob) -> None:
    """Собрать Typst-проект и завести результат как обычную ревизию материала.

    Порядок шагов не случайный: сначала проверяются пакеты (сеть без явного
    разрешения не трогается), затем идёт сборка, и только полностью успешный
    результат доходит до `_finish` — до него активная ревизия остаётся прежней.
    """
    task_id, material_id = task.id, task.material_id
    if material_id is None:
        return
    try:
        material = session.get(Material, material_id)
        row = session.get(TypstMaterial, material_id)
        if material is None or row is None:
            return
        entrypoint = str(task.checkpoint.get("entrypoint") or row.entrypoint or "")
        storage_path = material.storage_path
        allow_download = bool(task.checkpoint.get("download_packages"))
        packages = missing_packages(row.packages or [])
        session.rollback()
        if packages and not allow_download:
            _mark_typst_input_needed(session, task_id, package_issues(packages))
            return

        revision = revision_registry.max_revision(session, material_id) + 1
        session.rollback()
        with session.begin():
            current = session.get(BackgroundJob, task_id)
            assert current is not None
            current.checkpoint = {**current.checkpoint, "revision": revision, "selected_pages": []}

        bundle = material_path(storage_path)
        result = compile_bundle(bundle, entrypoint, allow_download=allow_download)
        if not result.ok:
            # Нехватка файла или пакета — не поломка проекта, а вопрос к
            # пользователю: он дошлёт картинку или разрешит загрузку и соберёт
            # заново. Всё остальное — ошибка, которую чинят в исходнике.
            if any(issue.get("kind") in RESOLVABLE_TYPST_ISSUES for issue in result.diagnostics):
                _mark_typst_input_needed(session, task_id, result.diagnostics)
            else:
                first = result.diagnostics[0] if result.diagnostics else {}
                message = str(first.get("message") or "Сборка Typst не удалась")
                _mark_typst_failed(session, task_id, material_id, message, result.diagnostics)
            return

        assert result.pdf_path is not None
        # Тот же разбор, что у обычного PDF: страница целиком одним абзацем
        # оставляла материал без заголовков, а без них не работают ни блоки, ни
        # автопривязка ответов. Владелец вырезов — хеш bundle, как у файлов.
        pages = list(text_layer_pages(result.pdf_path, Path(storage_path).stem))
        with session.begin():
            material = session.get(Material, material_id)
            assert material is not None
            material.outline = extract_outline(result.pdf_path)
            current = session.get(BackgroundJob, task_id)
            assert current is not None
            current.checkpoint = {
                **current.checkpoint,
                "selected_pages": [page.page_number for page in pages],
            }
            current.total = len(pages)
        for page in pages:
            if not _save_page(session, task_id, page):
                return

        render_path = (Path("typst-rendered") / str(material_id) / f"{revision}.pdf").as_posix()
        destination = material_path(render_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(result.pdf_path, destination)
        # Растры страниц кэшируются по номеру: у обычного файла источник неизменен,
        # а у Typst каждая сборка даёт новый PDF — без сброса просмотрщик показывал
        # бы страницы прошлой версии.
        shutil.rmtree(material_path(f"pages/{material_id}"), ignore_errors=True)
        _save_typst_chunks(session, material_id, revision, bundle, entrypoint, len(pages))
        _finish(session, task_id)
        _register_typst_build(session, material_id, revision, result, render_path, len(pages))
    except Exception as error:
        session.rollback()
        log.exception("typst compile failed material=%s: %s", material_id, error)
        _mark_typst_failed(
            session, task_id, material_id, f"Внутренняя ошибка сборки Typst: {error}", []
        )


def process_link_answers_job(session: Session, job: BackgroundJob) -> None:
    """Выполнить `BackgroundJobKind.LINK_ANSWERS`.

    В отличие от ролей ИИ здесь нет ни `AiRun`, ни сетевого вызова:
    `link_answers_material` — синхронный локальный расчёт по уже загруженным
    данным, поэтому задача не идёт через `process_ai_job` и не тратит
    предельное время на вызов модели.
    """
    job_id = job.id
    project_id = job.project_id
    material_id = job.material_id
    try:
        assert project_id is not None and material_id is not None
        with session.begin():
            link_answers_material(session, project_id, material_id)
            finished = session.get(BackgroundJob, job_id)
            if finished:
                # Как и у ролей ИИ (app.ai.jobs._mark_finished): досрочно оборвать
                # уже идущий расчёт нечем, но отменённая задача не выглядит
                # завершённой, если пока она считала, её успели отменить.
                finished.state = (
                    BackgroundJobState.CANCELLED
                    if finished.pause_requested
                    else BackgroundJobState.COMPLETED
                )
                finished.done = finished.total
                finished.lease_owner = None
                finished.lease_expires_at = None
                finished.completed_at = utc_now()
                finished.updated_at = utc_now()
    except Exception as error:
        session.rollback()
        log.exception("link_answers job failed job=%s: %s", job_id, error)
        with session.begin():
            failed = session.get(BackgroundJob, job_id)
            if failed:
                failed.state = BackgroundJobState.FAILED
                failed.error = str(error)
                failed.lease_owner = None
                failed.lease_expires_at = None
                failed.updated_at = utc_now()


def run_once() -> bool:
    with SessionLocal() as session:
        worker_id = _worker_id()
        job = claim_job(session, worker_id)
        if job is None:
            return False
        started = time.perf_counter()
        # Одна очередь, один диспетчер: вид задачи решает, какой обработчик
        # её доводит до конца, а состояние (`state`) остаётся общим для всех.
        if job.kind == BackgroundJobKind.PARSE:
            process_parse_job(session, job)
        elif job.kind == BackgroundJobKind.TYPST_COMPILE:
            process_typst_compile_job(session, job)
        elif job.kind == BackgroundJobKind.LINK_ANSWERS:
            process_link_answers_job(session, job)
        else:
            process_ai_job(session, job)
        log.info(
            "processed job=%s kind=%s %.1fms",
            job.id,
            job.kind,
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
