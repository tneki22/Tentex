from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ParserMode
from app.ocr.engines import RASTER_SCALE_OPTIONS

RasterScale = Literal[*RASTER_SCALE_OPTIONS]
EngineRuntime = Literal["worker", "gpu_service", "cloud"]

# Машинное состояние движка. Заголовок и цвет по нему подбирает экран — здесь
# только факт, как и у кодов ошибок в `ProjectDomainError`.
Readiness = Literal[
    "ready",
    "downloading",
    "needs_models",
    "needs_service",
    "starting",
    "error",
    "unavailable",
]
JobState = Literal["running", "done", "failed", "cancelled"]
ServiceState = Literal["running", "starting", "stopped", "failed", "absent", "unavailable"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class OcrGlobalSettingsWrite(ApiModel):
    default_mode: ParserMode
    quality_threshold: float = Field(ge=0, le=1)
    raster_scale: RasterScale


class OcrEngineWrite(ApiModel):
    model_id: str | None = Field(default=None, max_length=200)
    device: str | None = Field(default=None, max_length=50)
    language: str | None = Field(default=None, max_length=10)
    executor: str | None = Field(default=None, max_length=50)
    extra: dict[str, object] = Field(default_factory=dict)


class OcrModelRead(ApiModel):
    key: str
    engine: str
    title: str
    summary: str
    good_for: str
    # Откуда именно приедут файлы: организация, ссылка и полные имена репозиториев.
    source_title: str
    source_url: str
    repos: list[str]
    license_title: str
    license_url: str
    size_bytes: int
    device: Literal["cpu", "gpu"]
    languages: str
    min_vram_mb: int | None
    recommended_vram_mb: int | None
    min_ram_mb: int
    notes: list[str]
    recommended: bool
    installed: bool
    installed_bytes: int
    # Подойдёт ли этой машине. `None` — проверить не удалось, и это не «нет».
    fits: bool | None
    fits_note: str
    job_state: JobState | None
    job_cancel_requested: bool
    job_done_bytes: int
    job_total_bytes: int
    job_current: str
    job_error: str


class OcrGpuRead(ApiModel):
    name: str
    vram_mb: int | None
    driver: str | None
    source: str


class OcrHardwareRead(ApiModel):
    cpu_cores: int | None
    ram_mb: int | None
    free_disk_mb: int | None
    gpu: OcrGpuRead | None
    gpu_reason: str
    notes: list[str]


class OcrServiceRead(ApiModel):
    state: ServiceState
    summary: str
    detail: str
    can_start: bool
    can_stop: bool


class OcrEngineRead(ApiModel):
    mode: str
    title: str
    description: str
    trade_off: str
    runtime: EngineRuntime
    configurable: bool
    enabled: bool
    available: bool
    readiness: Readiness
    status_detail: str
    # Что именно сейчас считает — модель или исполнитель, если это известно.
    active_label: str
    # Настройки, применяемые только при следующем запуске GPU-сервиса.
    restart_required: bool
    model_id: str | None
    device: str | None
    language: str | None
    executor: str | None
    extra: dict[str, object]
    updated_at: datetime | None
    models: list[OcrModelRead]
    service: OcrServiceRead | None


class OcrSettingsRead(ApiModel):
    default_mode: ParserMode
    quality_threshold: float
    raster_scale: float
    hardware: OcrHardwareRead
    engines: list[OcrEngineRead]
