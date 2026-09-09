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
from app.materials import library
from app.models import (
    AiSettings,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    OcrEngineConfig,
    ParserMode,
    Project,
    utc_now,
)
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
# `ai_cleanup` относится к одной странице материала, а её номера в строке
# задачи нет — вернуть пользователя ровно на неё панель пока не может;
# `ai_preparation` живёт внутри мастера, который подставляет оценку в форму сам,
# как только шаг открыт заново.
REVIEW_REQUIRED_KINDS = {
    BackgroundJobKind.AI_GROUPING,
    BackgroundJobKind.AI_IMPORT_REPAIR,
    BackgroundJobKind.AI_ANSWER_SECTIONS,
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
    if job.material_id is not None:
        material = session.get(Material, job.material_id)
        if material is not None:
            return material.original_name
    if job.project_id is not None:
        project = session.get(Project, job.project_id)
        if project is not None:
            return project.name or "Проект без названия"
    return ""


def _model_label(session: Session, job: BackgroundJob) -> str:
    """Чем именно читается материал: локальный движок или внешняя модель.

    Заполняется только у разбора: у ролей ИИ модель выбирается по роли уже
    внутри шлюза, и в самой задаче её названия нет.
    """
    if job.kind != BackgroundJobKind.PARSE:
        return ""
    if job.parser_mode == ParserMode.CLOUD:
        row = session.get(AiSettings, 1)
        return (row.default_vision_model_id if row else None) or "внешняя модель"
    engine = session.get(OcrEngineConfig, "fast")
    return (engine.model_id if engine else None) or DEFAULT_FAST_MODEL_ID


def _read(session: Session, job: BackgroundJob) -> BackgroundJobRead:
    return BackgroundJobRead.model_validate(job).model_copy(
        update={
            "subject": _subject(session, job),
            "model_label": _model_label(session, job),
            "needs_review": _needs_review(job),
        }
    )


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
    project_id: UUID | None = None,
    material_id: UUID | None = None,
) -> list[BackgroundJobRead]:
    """Список задач с фильтрами.

    `active_only` и `pending_review` вместе дают объединение, а не пересечение:
    это ровно то, что показывает панель фоновых задач — и то, что идёт сейчас,
    и то, что уже досчиталось и ждёт человека. Пересечение этих двух условий
    пусто по определению, так что второго смысла у сочетания флагов нет.
    """
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())
    if active_only or pending_review:
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
        stmt = stmt.where(or_(*buckets))
    if project_id is not None:
        stmt = stmt.where(BackgroundJob.project_id == project_id)
    if material_id is not None:
        stmt = stmt.where(BackgroundJob.material_id == material_id)
    jobs = [_read(session, job) for job in session.scalars(stmt)]
    if not pending_review:
        return jobs
    # Задача без сохранённого результата в корзину не попадает (см.
    # `_needs_review`), а SQL про содержимое checkpoint не спрашивает.
    return [
        job
        for job in jobs
        if job.needs_review or (active_only and job.state in ACTIVE_JOB_STATES)
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
        with session.begin():
            library.control_task_core(session, material_id, "cancel")
        return snapshot.model_copy(update={"state": BackgroundJobState.CANCELLED})
    if state == BackgroundJobState.QUEUED:
        with session.begin():
            job.state = BackgroundJobState.CANCELLED
            job.updated_at = utc_now()
    elif state == BackgroundJobState.RUNNING:
        with session.begin():
            job.pause_requested = True
            job.updated_at = utc_now()
    else:
        raise ProjectConflictError(
            "Задачу нельзя отменить в текущем состоянии", code="background_job_not_cancellable"
        )
    session.expire_all()
    return get_job(session, job_id)


def resolve_job(session: Session, job_id: UUID) -> BackgroundJobRead:
    """Отметить, что готовое предложение разобрано, — принято или убрано.

    Чем именно кончилось, реестр не хранит: применённый план виден по самим
    данным (структура программы, привязки ответов), и вторая запись об этом
    рядом стала бы второй правдой, которая рано или поздно разойдётся с первой.
    Здесь важно только одно — предложение больше не ждёт человека.

    Повторный вызов ничего не меняет: диалог применения и панель зовут этот
    маршрут независимо друг от друга, и гонка между ними не должна быть ошибкой.
    """
    job = _job_or_404(session, job_id)
    state, reviewed_at = job.state, job.reviewed_at
    if state != BackgroundJobState.COMPLETED:
        raise ProjectConflictError(
            "Разбирать нечего: задача ещё не завершена",
            code="background_job_not_completed",
        )
    if reviewed_at is None:
        # Как и в `cancel_job`: читающая транзакция закрывается до записи.
        session.rollback()
        with session.begin():
            job.reviewed_at = utc_now()
            job.updated_at = utc_now()
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
