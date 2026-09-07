from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.background import registry
from app.background.schemas import BackgroundJobRead
from app.db import get_session

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/background-jobs", tags=["background-jobs"])


@router.get("", response_model=list[BackgroundJobRead])
def list_background_jobs(
    session: SessionDependency,
    active_only: bool = False,
    pending_review: bool = False,
    project_id: UUID | None = None,
    material_id: UUID | None = None,
) -> list[BackgroundJobRead]:
    """Список задач. `active_only` и `pending_review` вместе — объединение
    корзин: то, что идёт сейчас, плюс то, что досчиталось и ждёт человека."""
    return registry.list_jobs(
        session,
        active_only=active_only,
        pending_review=pending_review,
        project_id=project_id,
        material_id=material_id,
    )


@router.get("/{job_id}", response_model=BackgroundJobRead)
def get_background_job(job_id: UUID, session: SessionDependency) -> BackgroundJobRead:
    return registry.get_job(session, job_id)


@router.get("/{job_id}/result")
def get_background_job_result(job_id: UUID, session: SessionDependency) -> dict[str, Any]:
    """Разобранный ответ завершившейся задачи — то же, что вернул бы синхронный
    вызов. Отдельным маршрутом, а не полем в `BackgroundJobRead`: список задач
    опрашивается раз в несколько секунд, и таскать в каждом ответе целое
    предложение модели незачем.
    """
    return registry.get_job_result(session, job_id)


@router.post("/{job_id}/cancel", response_model=BackgroundJobRead)
def cancel_background_job(job_id: UUID, session: SessionDependency) -> BackgroundJobRead:
    return registry.cancel_job(session, job_id)


@router.post("/{job_id}/resolve", response_model=BackgroundJobRead)
def resolve_background_job(job_id: UUID, session: SessionDependency) -> BackgroundJobRead:
    """Снять задачу с корзины «ждут проверки»: предложение разобрано.

    Зовётся и диалогом после успешного применения, и панелью, когда результат
    убирают не глядя, — поэтому повторный вызов ничего не меняет.
    """
    return registry.resolve_job(session, job_id)
