"""HTTP-контракт сводки «Состояние»."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.system import service
from app.system.schemas import SystemProbeRead, SystemStatusRead

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status", response_model=SystemStatusRead)
def get_system_status(session: SessionDependency) -> SystemStatusRead:
    """Лёгкие проверки для панели; сам ответ уже значит, что API жив."""
    return service.system_status(session)


@router.post("/write-probe", response_model=SystemProbeRead)
def post_write_probe(session: SessionDependency) -> SystemProbeRead:
    """Кнопка «Проверить»: проба записи без изменений и свежая сводка."""
    return service.probe_write_access(session)
