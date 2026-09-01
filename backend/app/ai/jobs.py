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

from pydantic import BaseModel
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


async def _dispatch(session: Session, job: BackgroundJob, gateway: ModelGateway) -> BaseModel:
    """Восстановить команду из `checkpoint` и позвать тот же `run()`, которым
    пользуется синхронный HTTP-путь (прямой вызов, не через очередь).

    Возвращает ту же модель ответа, что получал бы синхронный вызов: именно её
    заберёт экран, вернувшийся к задаче после ухода (см. `_mark_finished`).
    """
    command = job.checkpoint.get("command") or {}
    if job.kind == BackgroundJobKind.AI_GROUPING:
        assert job.project_id is not None
        return await program_ai.run(
            session,
            gateway,
            job.project_id,
            program_ai.ProgramGroupingRunWrite.model_validate(command),
            job_id=job.id,
        )
    elif job.kind == BackgroundJobKind.AI_IMPORT_REPAIR:
        assert job.project_id is not None
        return await import_repair.run_program_repair(
            session,
            gateway,
            job.project_id,
            import_repair.ProgramRepairRunWrite.model_validate(command),
            job_id=job.id,
        )
    elif job.kind == BackgroundJobKind.AI_PREPARATION:
        assert job.project_id is not None
        return await preparation_ai.run(
            session,
            gateway,
            job.project_id,
            preparation_ai.PreparationEstimateRunWrite.model_validate(command),
            job_id=job.id,
        )
    elif job.kind == BackgroundJobKind.AI_CLEANUP:
        assert job.material_id is not None
        page_number = int(job.checkpoint["page_number"])
        return await ai_cleanup.run(
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
) -> BaseModel:
    async with asyncio.timeout(deadline):
        return await _dispatch(session, job, gateway)


def _mark_finished(session: Session, job_id: UUID, result: BaseModel) -> None:
    """Успех — но если пока шёл вызов, задачу успели отменить (`pause_requested`,
    см. `app.background.registry.cancel_job`), это не `completed`, а `cancelled`:
    досрочно оборвать уже идущий вызов модели нечем, но сообщать о нём как об
    успешном выполнении, которого пользователь не просил дожидаться, нечестно.

    Ответ роли кладётся в `checkpoint["result"]` уже разобранным — в той же
    форме, что вернул бы синхронный вызов. Сырой `ai_runs.response_payload` для
    этого не годится: у починки списка вопросов модель отвечает в плоском
    проволочном формате, и разворачивает его в дерево билетов серверный
    `_wire_to_suggestion`. Хранить здесь результат уже после этой сборки — то,
    что позволяет экрану вернуться к готовому предложению, не повторяя разбор.
    """
    with session.begin():
        job = session.get(BackgroundJob, job_id)
        if job is None:
            return
        checkpoint = dict(job.checkpoint)
        checkpoint["result"] = result.model_dump(mode="json")
        job.checkpoint = checkpoint
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


def process_ai_job(
    session: Session, job: BackgroundJob, gateway: ModelGateway | None = None
) -> None:
    """Выполнить задачу вызова модели, взятую из очереди воркером.

    Гейтвей по умолчанию боевой (`transport=None` → `production_transport`
    внутри `ModelGateway`) — воркер его не передаёт. Параметр существует
    ради тестов: они подставляют `ModelGateway(session, FakeTransport(...))`,
    не поднимая настоящего провайдера (см. `tests/test_ai_jobs.py`).
    """
    job_id = job.id
    deadline = DEADLINE_SECONDS.get(job.kind, 600)
    gateway = gateway or ModelGateway(session)
    try:
        result = asyncio.run(_run_with_deadline(session, job, gateway, deadline))
        _mark_finished(session, job_id, result)
    except TimeoutError:
        _mark_failed(
            session, job_id, f"Задача не уложилась в отведённые {deadline} с и была прервана"
        )
    except ProjectDomainError as error:
        _mark_failed(session, job_id, error.detail)
    except Exception as error:  # noqa: BLE001 — воркер не должен падать целиком из-за одной задачи
        log.exception("ai job failed job=%s kind=%s: %s", job_id, job.kind, error)
        _mark_failed(session, job_id, str(error))
