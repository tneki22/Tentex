"""HTTP И2: офлайновые снимки, запуск, управление и текущие данные."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.coverage import interaction, lifecycle, queries, service
from app.coverage.schemas import (
    BlocksRead,
    DecisionReceipt,
    DecisionWrite,
    EvidenceRead,
    OverviewRead,
    PreflightRead,
    RunControl,
    RunPlan,
    RunRead,
    RunStart,
    TopicEvidenceRead,
    TopicsRead,
)
from app.db import get_session

router = APIRouter(prefix="/api/projects/{project_id}/coverage", tags=["coverage"])
DB = Annotated[Session, Depends(get_session)]


@router.post("/preflight", response_model=PreflightRead)
def preflight(project_id: UUID, command: RunPlan, session: DB):
    """Снимок без обращения к провайдеру."""
    return service.preflight(session, project_id, command)


@router.post("/runs", status_code=202, response_model=RunRead)
def start(project_id: UUID, command: RunStart, session: DB):
    """Атомарная постановка в общую очередь."""
    run_id = service.start_run(session, project_id, command)
    return queries.run_read(session, project_id, run_id)


@router.get("/runs/{run_id}", response_model=RunRead)
def read_run(project_id: UUID, run_id: UUID, session: DB):
    """Исторический прогресс и причины остановки."""
    return queries.run_read(session, project_id, run_id)


@router.post("/runs/{run_id}/control", response_model=RunRead)
def control(project_id: UUID, run_id: UUID, command: RunControl, session: DB):
    """Пауза, продолжение или отмена с проверкой поколения."""
    lifecycle.control_run(session, project_id, run_id, command)
    return queries.run_read(session, project_id, run_id)


@router.get("/overview", response_model=OverviewRead)
def overview(project_id: UUID, session: DB):
    """Сводка по всем активным источникам проекта."""
    return queries.overview(session, project_id)


@router.get("/issues", response_model=BlocksRead)
def issues(
    project_id: UUID,
    session: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Нерешённые, сбойные и устаревшие блоки всех источников одной страницей."""
    return queries.issue_blocks(session, project_id, offset, limit)


@router.get("/topics", response_model=TopicsRead)
def topics(
    project_id: UUID,
    session: DB,
    view: str = Query("readable", pattern="^(readable|gaps)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Темы для чтения и пробелы без подмены упоминаниями."""
    return interaction.topics_page(session, project_id, view, offset, limit)


@router.get("/blocks", response_model=BlocksRead)
def view_blocks(
    project_id: UUID,
    session: DB,
    view: str = Query("outside_program", pattern="^(outside_program|needs_action)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Неразобранное отдельно от технических проблем."""
    return interaction.blocks_page(session, project_id, view, offset, limit)


@router.get("/topics/{node_id}/evidence", response_model=TopicEvidenceRead)
def topic_evidence(project_id: UUID, node_id: UUID, session: DB):
    """Опоры темы в группах чтения с детерминированным порядком."""
    return interaction.topic_evidence(session, project_id, node_id)


@router.get("/sources/{material_id}/blocks", response_model=BlocksRead)
def blocks(
    project_id: UUID,
    material_id: UUID,
    session: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """Пагинация не скрывает число оставшихся блоков."""
    return queries.source_blocks(session, project_id, material_id, offset, limit)


@router.get("/evidence/{evidence_id}", response_model=EvidenceRead)
def evidence(project_id: UUID, evidence_id: str, session: DB):
    """Проверка принадлежности каждой части адреса."""
    return interaction.evidence_detail(session, project_id, evidence_id)


@router.post("/decisions", response_model=DecisionReceipt)
def decide(project_id: UUID, command: DecisionWrite, session: DB):
    """Одна команда, одна транзакция, один общий undo."""
    return interaction.apply_decision(session, project_id, command)
