from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import BackgroundJobKind, BackgroundJobState, ParserMode, ProcessingStage


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class BackgroundJobStartRead(ApiModel):
    """Ответ постановки в очередь (`start()`, Ш4 плана): 202 и id задачи —
    вместо ожидания результата в самом запросе."""

    job_id: UUID


class BackgroundJobRead(ApiModel):
    id: UUID
    kind: BackgroundJobKind
    state: BackgroundJobState
    material_id: UUID | None
    project_id: UUID | None
    # Стадии extract/segment и режим разбора осмысленны только у kind=parse.
    stage: ProcessingStage | None
    parser_mode: ParserMode | None
    done: int
    total: int
    diagnostics: list[str]
    error: str | None
    pause_requested: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
