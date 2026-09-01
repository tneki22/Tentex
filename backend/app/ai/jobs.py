"""Диспетчер фоновых задач-ролей ИИ: одна очередь, один воркер, общий словарь
состояний (Ш2 плана, этап 3).

Каждая роль (`program_ai`, `import_repair`, `preparation_ai`, `ai_cleanup`)
уже умеет и оценить стоимость (`preflight`), и выполнить сам вызов (`run`) —
этот модуль восстанавливает команду из `checkpoint` задачи и зовёт тот же
`run`, но с боевым шлюзом моделей и предельным временем на задачу целиком.

Предельное время — на ЗАДАЧУ, а не на лиз. Лиз (`worker.LEASE_SECONDS`, 60с)
защищает от МЁРТВОГО воркера: если процесс упал, никто не продлевает лиз, и
задача возвращается в очередь. Он не защищает от ЗАВИСШЕГО воркера — живого
процесса, который продлевает лиз, но не продвигается (например, провайдер
завис на середине ответа). Отсюда `DEADLINE_SECONDS`: у каждой роли — свой
предел, и по истечении задача честно падает в `failed`, а воркер идёт дальше.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.materials import ai_cleanup
from app.models import BackgroundJob, BackgroundJobKind, BackgroundJobState, utc_now
from app.projects import import_repair, preparation_ai, program_ai
from app.projects.errors import ProjectDomainError

log = logging.getLogger("tentex.worker")

# Группировка и починка списка перечитывают много позиций программы и просят
# большой response_format (minimum_output_tokens 8000/12000 у program_ai и
# import_repair) — им нужен запас. Уборка страницы и оценка нагрузки короче.
DEADLINE_SECONDS: dict[BackgroundJobKind, int] = {
    BackgroundJobKind.AI_GROUPING: 600,
    BackgroundJobKind.AI_IMPORT_REPAIR: 900,
    BackgroundJobKind.AI_PREPARATION: 300,
    BackgroundJobKind.AI_CLEANUP: 300,
}


async def _dispatch(session: Session, job: BackgroundJob, gateway: ModelGateway) -> None:
    """Восстановить команду из `checkpoint` и позвать тот же `run()`, которым
    пользуется синхронный HTTP-путь (прямой вызов, не через очередь)."""
    command = job.checkpoint.get("command") or {}
    if job.kind == BackgroundJobKind.AI_GROUPING:
        assert job.project_id is not None
        await program_ai.run(
            session,
            gateway,
            job.project_id,
            program_ai.ProgramGroupingRunWrite.model_validate(command),
            job_id=job.id,
        )
    elif job.kind == BackgroundJobKind.AI_IMPORT_REPAIR:
        assert job.project_id is not None
        await import_repair.run_program_repair(
            session,
            gateway,
            job.project_id,
            import_repair.ProgramRepairRunWrite.model_validate(command),
            job_id=job.id,
        )
    elif job.kind == BackgroundJobKind.AI_PREPARATION:
        assert job.project_id is not None
        await preparation_ai.run(
            session,
            gateway,
            job.project_id,
            preparation_ai.PreparationEstimateRunWrite.model_validate(command),
            job_id=job.id,
        )
    elif job.kind == BackgroundJobKind.AI_CLEANUP:
        assert job.material_id is not None
        page_number = int(job.checkpoint["page_number"])
        await ai_cleanup.run(
            session,
            gateway,
            job.project_id,
            job.material_id,
            page_number,
            ai_cleanup.CleanupRunWrite.model_validate(command),
            job_id=job.id,
        )
    else:
        raise AssertionError(f"process_ai_job вызван для неожиданного вида задачи: {job.kind}")


async def _run_with_deadline(
    session: Session, job: BackgroundJob, gateway: ModelGateway, deadline: int
) -> None:
    async with asyncio.timeout(deadline):
        await _dispatch(session, job, gateway)


def _mark_finished(session: Session, job_id: UUID) -> None:
    """Успех — но если пока шёл вызов, задачу успели отменить (`pause_requested`,
    см. `app.background.registry.cancel_job`), это не `completed`, а `cancelled`:
    досрочно оборвать уже идущий вызов модели нечем, но сообщать о нём как об
    успешном выполнении, которого пользователь не просил дожидаться, нечестно.
    """
    with session.begin():
        job = session.get(BackgroundJob, job_id)
        if job is None:
            return
        job.state = (
            BackgroundJobState.CANCELLED if job.pause_requested else BackgroundJobState.COMPLETED
        )
        job.done = job.total or 1
        job.total = job.total or 1
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = utc_now()
        job.updated_at = utc_now()


def _mark_failed(session: Session, job_id: UUID, message: str) -> None:
    session.rollback()
    with session.begin():
        job = session.get(BackgroundJob, job_id)
        if job is None:
            return
        job.state = BackgroundJobState.FAILED
        job.error = message
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utc_now()


def process_ai_job(session: Session, job: BackgroundJob) -> None:
    """Выполнить задачу вызова модели, взятую из очереди воркером.

    Гейтвей здесь боевой (`transport=None` → `production_transport`), в
    отличие от тестов, где в него подставляется `FakeTransport`.
    """
    job_id = job.id
    deadline = DEADLINE_SECONDS.get(job.kind, 600)
    gateway = ModelGateway(session)
    try:
        asyncio.run(_run_with_deadline(session, job, gateway, deadline))
        _mark_finished(session, job_id)
    except TimeoutError:
        _mark_failed(
            session, job_id, f"Задача не уложилась в отведённые {deadline} с и была прервана"
        )
    except ProjectDomainError as error:
        _mark_failed(session, job_id, error.detail)
    except Exception as error:  # noqa: BLE001 — воркер не должен падать целиком из-за одной задачи
        log.exception("ai job failed job=%s kind=%s: %s", job_id, job.kind, error)
        _mark_failed(session, job_id, str(error))
