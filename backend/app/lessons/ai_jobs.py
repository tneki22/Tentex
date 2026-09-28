"""Задача `ai_lesson` из очереди: подвид выбирает, какой модуль её выполняет."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.lessons import ai_build, ai_bulk, ai_enrich, ai_practice
from app.models import BackgroundJob

RUNNERS = {
    ai_enrich.SUBTYPE: ai_enrich.run,
    ai_practice.SUBTYPE: ai_practice.run,
    ai_bulk.SUBTYPE: ai_bulk.run,
}


async def run(session: Session, gateway: ModelGateway, job_id: UUID) -> BaseModel:
    """«Дополнить», задания и массовая сборка — свои модули; план и сборка урока — `ai_build`."""
    job = session.get(BackgroundJob, job_id)
    assert job is not None
    runner = RUNNERS.get(job.checkpoint.get("subtype"), ai_build.run)
    return await runner(session, gateway, job_id)
