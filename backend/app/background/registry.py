"""Реестр фоновых операций: читает и отменяет `background_jobs` напрямую.

Одна таблица под все виды задач (Ш1 плана) — поэтому сам модуль тонкий: он не
знает деталей разбора материала или вызовов ИИ, только общую ось состояний.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.background.schemas import BackgroundJobRead
from app.db import retry_on_locked
from app.materials import library
from app.materials.naming import material_display_name
from app.models import (
    AiSettings,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    MaterialSourceKind,
    OcrEngineConfig,
    ParserMode,
    Project,
    utc_now,
)
from app.ocr import speech
from app.ocr.engines import DEFAULT_FAST_MODEL_ID
from app.projects.errors import ProjectConflictError, ProjectNotFoundError

ACTIVE_JOB_STATES = {
    BackgroundJobState.QUEUED,
    BackgroundJobState.RUNNING,
    BackgroundJobState.PAUSED,
}

# Виды задач, которые заканчиваются не тем, что воркер досчитал, а тем, что
# человек посмотрел предложение и принял его. Пока этого не произошло, задача
# висит в отдельной корзине «ждут проверки»: иначе готовый план исчезал из
# панели вместе с активностью и вернуться к нему было неоткуда.
#
# Остальные виды сюда не входят по существу, а не по недосмотру:
# `parse` и `link_answers` применяют результат сами и подтверждения не просят;
# `ai_preparation` живёт внутри мастера, который подставляет оценку в форму сам,
# как только шаг открыт заново.
REVIEW_REQUIRED_KINDS = {
    BackgroundJobKind.AI_GROUPING,
    BackgroundJobKind.AI_IMPORT_REPAIR,
    BackgroundJobKind.AI_ANSWER_SECTIONS,
    BackgroundJobKind.AI_CLEANUP,
}


def _needs_review(job: BackgroundJob) -> bool:
    """Готовое предложение, которое ещё никто не разобрал.

    Результат обязателен: задача, завершившаяся без него, применять нечего —
    показывать её как ожидающую проверки значило бы звать в пустой диалог.
    """
    return (
        job.kind in REVIEW_REQUIRED_KINDS
        and job.state == BackgroundJobState.COMPLETED
        and job.reviewed_at is None
        and job.checkpoint.get("result") is not None
    )


def _subject(session: Session, job: BackgroundJob) -> str:
    """Над чем идёт работа — именем файла или проекта, а не идентификатором."""
    if (
        job.kind == BackgroundJobKind.RETRIEVAL_INDEX
        and job.checkpoint.get("mode") != "incremental"
    ):
        from app.models import EmbeddingProfile, RetrievalIndex

        profile = None
        profile_id = job.checkpoint.get("profile_id")
        if profile_id:
            profile = session.get(EmbeddingProfile, UUID(str(profile_id)))
        if profile is None:
            index_id = job.checkpoint.get("index_id")
            index = session.get(RetrievalIndex, UUID(str(index_id))) if index_id else None
            profile = session.get(EmbeddingProfile, index.profile_id) if index else None
        model_label = (
            f"с моделью {profile.model_id}" if profile is not None else "с embedding-моделью"
        )
        if job.material_id is not None:
            material = session.get(Material, job.material_id)
            if material is not None:
                return f"{material_display_name(material)} · {model_label}"
        return model_label
    if job.material_id is not None:
        material = session.get(Material, job.material_id)
        if material is not None:
            return material_display_name(material)
    if job.project_id is not None:
        project = session.get(Project, job.project_id)
        if project is not None:
            return project.name or "Проект без названия"
    if job.kind == BackgroundJobKind.RETRIEVAL_MODEL_INSTALL:
        return str(job.checkpoint.get("model_id") or "embedding-модель")
    if job.kind == BackgroundJobKind.BACKUP_CREATE:
        return "Вся установка"
    if job.kind in {BackgroundJobKind.PROJECT_EXPORT, BackgroundJobKind.PROJECT_IMPORT}:
        return "Перенос проекта"
    return ""


def _is_audio(session: Session, job: BackgroundJob) -> bool:
    if job.material_id is None:
        return False
    material = session.get(Material, job.material_id)
    return material is not None and material.source_kind == MaterialSourceKind.AUDIO


def _progress_unit(session: Session, job: BackgroundJob) -> str:
    """Чем измеряется `done` из `total`: у разбора страницы, у записи минуты."""
    if job.kind == BackgroundJobKind.RETRIEVAL_MODEL_INSTALL:
        return "файлов"
    if job.kind == BackgroundJobKind.RETRIEVAL_INDEX:
        return "материалов"
    if job.kind == BackgroundJobKind.BACKUP_CREATE:
        return "файлов"
    if job.kind in {BackgroundJobKind.PROJECT_EXPORT, BackgroundJobKind.PROJECT_IMPORT}:
        return "пакетов"
    if job.kind == BackgroundJobKind.IMAGE_DESCRIPTIONS:
        return "изображений"
    if job.kind not in (BackgroundJobKind.PARSE, BackgroundJobKind.TYPST_COMPILE):
        return ""
    return "минут" if _is_audio(session, job) else "страниц"


def _model_label(session: Session, job: BackgroundJob) -> str:
    """Чем именно читается материал: локальный движок или внешняя модель.

    У ролей ИИ модель выбирается по роли уже внутри шлюза, и в самой задаче её
    названия нет; retrieval-задачи, наоборот, всегда показывают понятный тип
    операции.
    """
    if job.kind == BackgroundJobKind.RETRIEVAL_MODEL_INSTALL:
        return "Скачивание embedding-модели"
    if job.kind == BackgroundJobKind.RETRIEVAL_INDEX:
        return "Сбор индекса"
    if job.kind == BackgroundJobKind.BACKUP_CREATE:
        return "Резервная копия"
    if job.kind == BackgroundJobKind.PROJECT_EXPORT:
        return "Экспорт проекта"
    if job.kind == BackgroundJobKind.PROJECT_IMPORT:
        return "Импорт проекта"
    if job.kind == BackgroundJobKind.STORAGE_VERIFY:
        return "Проверка хранилища"
    if job.kind == BackgroundJobKind.STORAGE_CLEANUP:
        return "Очистка временного"
    if job.kind == BackgroundJobKind.IMAGE_DESCRIPTIONS:
        return str(job.checkpoint.get("model_label") or "внешняя модель")
    if job.kind in REVIEW_REQUIRED_KINDS:
        checkpoint = job.checkpoint
        return str(
            checkpoint.get("model_label")
            or (checkpoint.get("result") or {}).get("actual_model_id")
            or "внешняя модель"
        )
    if job.kind != BackgroundJobKind.PARSE:
        return ""
    if _is_audio(session, job):
        # Запись читает не OCR: подпись «PP-OCRv5» у неё была бы неправдой.
        return speech.mode_label(session, job.parser_mode)
    if job.parser_mode == ParserMode.CLOUD:
        # Модель запуска зафиксирована в снимке задачи; у старых задач снимка нет.
        snapshot = (job.checkpoint.get("options") or {}).get("page_model") or {}
        if snapshot.get("model_id"):
            return str(snapshot["model_id"])
        row = session.get(AiSettings, 1)
        return (row.default_vision_model_id if row else None) or "внешняя модель"
    engine = session.get(OcrEngineConfig, "fast")
    return (engine.model_id if engine else None) or DEFAULT_FAST_MODEL_ID


def _read(session: Session, job: BackgroundJob) -> BackgroundJobRead:
    return BackgroundJobRead.model_validate(job).model_copy(
        update={
            "subject": _subject(session, job),
            "model_label": _model_label(session, job),
            "page_number": _positive_int(job.checkpoint.get("page_number")),
            "source_revision": _positive_int(
                (job.checkpoint.get("command") or {}).get("expected_revision")
            ),
            "deadline_seconds": _positive_int(job.checkpoint.get("deadline_seconds")),
            "max_attempts": _positive_int(job.checkpoint.get("max_attempts")),
            "progress_unit": _progress_unit(session, job),
            "needs_review": _needs_review(job),
            "control_action": (
                "finish"
                if job.kind == BackgroundJobKind.RETRIEVAL_INDEX
                and job.checkpoint.get("finish_requested")
                else "pause"
                if job.kind == BackgroundJobKind.RETRIEVAL_INDEX and job.pause_requested
                else None
            ),
        }
    )


def _positive_int(value: object) -> int | None:
    """Безопасно вывести числовую деталь из JSON checkpoint."""
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _job_or_404(session: Session, job_id: UUID) -> BackgroundJob:
    job = session.get(BackgroundJob, job_id)
    if job is None:
        raise ProjectNotFoundError("Фоновая задача не найдена", code="background_job_not_found")
    return job


def list_jobs(
    session: Session,
    *,
    active_only: bool = False,
    pending_review: bool = False,
    failed_only: bool = False,
    project_id: UUID | None = None,
    material_id: UUID | None = None,
    kind: str | None = None,
    page_number: int | None = None,
) -> list[BackgroundJobRead]:
    """Список задач с фильтрами.

    Флаги дают объединение корзин: активные, ожидающие проверки и просмотренные
    ещё не пользователем ошибки. Их пересечение пусто по определению.
    """
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())
    if active_only or pending_review or failed_only:
        buckets = []
        if active_only:
            buckets.append(BackgroundJob.state.in_(ACTIVE_JOB_STATES))
        if pending_review:
            buckets.append(
                and_(
                    BackgroundJob.kind.in_(REVIEW_REQUIRED_KINDS),
                    BackgroundJob.state == BackgroundJobState.COMPLETED,
                    BackgroundJob.reviewed_at.is_(None),
                )
            )
        if failed_only:
            buckets.append(
                and_(
                    BackgroundJob.state == BackgroundJobState.FAILED,
                    BackgroundJob.reviewed_at.is_(None),
                )
            )
        stmt = stmt.where(or_(*buckets))
    if project_id is not None:
        stmt = stmt.where(BackgroundJob.project_id == project_id)
    if material_id is not None:
        stmt = stmt.where(BackgroundJob.material_id == material_id)
    if kind is not None:
        try:
            job_kind = BackgroundJobKind(kind)
        except ValueError as error:
            raise ProjectConflictError(
                "Неизвестный вид фоновой задачи", code="background_job_kind_invalid"
            ) from error
        stmt = stmt.where(BackgroundJob.kind == job_kind)
    rows = list(session.scalars(stmt))
    # `checkpoint` — общий JSON-контейнер; номер страницы не заслуживает
    # колонки или завязки общего реестра на SQLite JSON-диалект. Список задач
    # мал, а Python-проверка одинаково читает старое число и старую строку.
    if page_number is not None:
        rows = [
            job
            for job in rows
            if _positive_int(job.checkpoint.get("page_number")) == page_number
        ]
    jobs = [_read(session, job) for job in rows]
    if not pending_review:
        return jobs
    # Задача без сохранённого результата в корзину не попадает (см.
    # `_needs_review`), а SQL про содержимое checkpoint не спрашивает.
    return [
        job
        for job in jobs
        if (
            job.needs_review
            or (active_only and job.state in ACTIVE_JOB_STATES)
            or (failed_only and job.state == BackgroundJobState.FAILED)
        )
    ]


def get_job(session: Session, job_id: UUID) -> BackgroundJobRead:
    return _read(session, _job_or_404(session, job_id))


def cancel_job(session: Session, job_id: UUID) -> BackgroundJobRead:
    """Отменить задачу.

    Работа над материалом (разбор и сборка Typst) отменяется через уже
    существующий `library.control_task_core`: там же выбрасывается строящаяся
    ревизия и восстанавливается статус материала — материал-специфичная логика,
    которую здесь дублировать нельзя. Без неё отменённая задача оставляла
    материал навсегда в «В очереди»: строка задачи снята, а статус нет.

    У задач без этой логики (роли ИИ, привязка ответов) путь короче: `queued`
    снимается сразу, а `running` получает `pause_requested` и достаётся до
    конца сама воркером — досрочно оборвать уже идущий вызов модели или расчёт
    нечем, но результат он всё равно получит статус `cancelled`, а не
    `completed` (см. `app.ai.jobs`).
    """
    job = _job_or_404(session, job_id)
    if (
        job.kind == BackgroundJobKind.RETRIEVAL_INDEX
        and job.checkpoint.get("mode") != "incremental"
    ):
        from app.retrieval.indexing import finish_index_build

        return finish_index_build(session, job_id)
    # У прохода 2 отмена обязана пройти через control_run: он один снимает
    # `paused`, освобождает lease и закрывает поколение, которого общий путь ниже
    # не знает.
    if job.kind == BackgroundJobKind.COVERAGE_RESEARCH:
        from app.coverage.lifecycle import control_run
        from app.coverage.schemas import RunControl
        from app.models import CoverageRun

        run = session.scalar(select(CoverageRun).where(CoverageRun.job_id == job_id))
        control_run(
            session,
            run.project_id,
            run.id,
            RunControl(action="cancel", expected_generation=run.execution_generation),
        )
        return get_job(session, job_id)

    # Чтение выше уже открыло транзакцию само (autobegin), а `session.begin()`
    # поверх начатой падает. Поэтому состояние снимается до отката, а не после:
    # откат сбрасывает объект, и обращение к его полю открыло бы транзакцию
    # заново — ровно ту, которую мы и закрывали.
    kind, state, material_id = job.kind, job.state, job.material_id
    material_scoped = kind in {BackgroundJobKind.PARSE, BackgroundJobKind.TYPST_COMPILE}
    # Снимок до отмены: `control_task_core` удаляет строку задачи вместе со
    # строящейся ревизией, и перечитывать её потом уже неоткуда.
    snapshot = _read(session, job) if material_scoped else None
    session.rollback()
    if material_scoped:
        assert material_id is not None and snapshot is not None

        def _cancel_material() -> None:
            if session.in_transaction():
                session.rollback()
            with session.begin():
                library.control_task_core(session, material_id, "cancel")

        retry_on_locked(_cancel_material)
        return snapshot.model_copy(update={"state": BackgroundJobState.CANCELLED})
    if state == BackgroundJobState.QUEUED:

        def _cancel_queued() -> None:
            if session.in_transaction():
                session.rollback()
            with session.begin():
                job.state = BackgroundJobState.CANCELLED
                job.updated_at = utc_now()

        retry_on_locked(_cancel_queued)
    elif state == BackgroundJobState.RUNNING:

        def _pause_running() -> None:
            if session.in_transaction():
                session.rollback()
            with session.begin():
                job.pause_requested = True
                job.updated_at = utc_now()

        retry_on_locked(_pause_running)
    else:
        raise ProjectConflictError(
            "Задачу нельзя отменить в текущем состоянии", code="background_job_not_cancellable"
        )
    session.expire_all()
    return get_job(session, job_id)


def resolve_job(session: Session, job_id: UUID) -> BackgroundJobRead:
    """Убрать из панели разобранный результат или просмотренную ошибку.

    Чем именно кончилось, реестр не хранит: применённый план виден по самим
    данным (структура программы, привязки ответов), и вторая запись об этом
    рядом стала бы второй правдой, которая рано или поздно разойдётся с первой.
    Здесь важно только одно — предложение больше не ждёт человека.

    Повторный вызов ничего не меняет: диалог применения и панель зовут этот
    маршрут независимо друг от друга, и гонка между ними не должна быть ошибкой.
    """
    job = _job_or_404(session, job_id)
    state, reviewed_at = job.state, job.reviewed_at
    if state not in {BackgroundJobState.COMPLETED, BackgroundJobState.FAILED}:
        raise ProjectConflictError(
            "Задачу ещё нельзя убрать из панели",
            code="background_job_not_completed",
        )
    if reviewed_at is None:
        # Как и в `cancel_job`: читающая транзакция закрывается до записи.
        def _mark_reviewed() -> None:
            if session.in_transaction():
                session.rollback()
            with session.begin():
                job.reviewed_at = utc_now()
                job.updated_at = utc_now()

        retry_on_locked(_mark_reviewed)
        session.expire_all()
    return get_job(session, job_id)


def get_job_result(session: Session, job_id: UUID) -> dict[str, Any]:
    """Отдать разобранный ответ роли, сохранённый завершившейся задачей.

    Именно это делает уход с экрана безопасным: задача досчитывается в фоне, а
    вернувшийся диалог забирает готовое предложение отсюда, вместо того чтобы
    звать модель заново и платить за неё второй раз.
    """
    job = _job_or_404(session, job_id)
    if job.state != BackgroundJobState.COMPLETED:
        raise ProjectConflictError(
            "Задача ещё не завершена — результата пока нет",
            code="background_job_not_completed",
        )
    result = job.checkpoint.get("result")
    if result is None:
        raise ProjectNotFoundError(
            "Задача завершилась без сохранённого результата",
            code="background_job_result_missing",
        )
    return result
