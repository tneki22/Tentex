"""Публичные схемы раздела «Хранилище»."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import BackupArchiveState, BackupKind, TransferProfile


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class BackupPolicyWrite(ApiModel):
    automatic_enabled: bool
    daily_time: str = "03:00"
    retention_days: int = Field(default=7, ge=1, le=365)
    backup_directory: str | None = Field(default=None, max_length=4096)

    @field_validator("daily_time")
    @classmethod
    def validate_daily_time(cls, value: str) -> str:
        """Хранить локальное время как стабильные `HH:MM`, без даты и зоны."""
        try:
            hour, minute = (int(part) for part in value.split(":"))
        except (TypeError, ValueError) as error:
            raise ValueError("Укажите время в формате ЧЧ:ММ") from error
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("Укажите время в формате ЧЧ:ММ")
        return f"{hour:02d}:{minute:02d}"


class BackupPolicyRead(BackupPolicyWrite):
    last_automatic_date: date | None


class StorageBreakdown(ApiModel):
    database: int
    files: int
    models: int
    backups: int
    temporary: int


class StorageSnapshot(ApiModel):
    data_directory: str
    backup_directory: str
    same_disk_warning: bool
    used_bytes: int
    free_bytes: int
    breakdown: StorageBreakdown
    policy: BackupPolicyRead
    last_backup_at: datetime | None
    maintenance: bool


class BackupArchiveRead(ApiModel):
    id: UUID
    kind: BackupKind
    state: BackupArchiveState
    job_id: UUID | None
    file_name: str | None
    size_bytes: int | None
    sha256: str | None
    manifest: dict[str, object]
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class BackupCreateRead(ApiModel):
    backup_id: UUID
    job_id: UUID


class TransferUploadRead(ApiModel):
    id: UUID
    kind: Literal["backup", "project"]
    file_name: str
    size_bytes: int
    manifest: dict[str, object]
    repeated: bool = False


class RestoreStartRead(ApiModel):
    operation_id: UUID
    state: Literal["waiting", "running"]


class RestoreStatusRead(ApiModel):
    operation_id: UUID
    state: Literal["waiting", "running", "completed", "failed", "rolled_back"]
    detail: str
    safety_backup_id: UUID | None = None
    completed_at: datetime | None = None


class ProjectExportCommand(ApiModel):
    profile: TransferProfile


class ProjectExportRead(ApiModel):
    artifact_id: UUID
    job_id: UUID


class ProjectImportCommand(ApiModel):
    allow_duplicate: bool = False


class ProjectImportRead(ApiModel):
    artifact_id: UUID
    job_id: UUID


class MaintenanceResult(ApiModel):
    ok: bool
    detail: str
    checked_files: int = 0
    missing_files: list[str] = Field(default_factory=list)
    freed_bytes: int = 0
