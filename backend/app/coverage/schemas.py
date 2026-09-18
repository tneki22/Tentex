"""Строгий ответ одного блока; пакет намеренно не валидируется целиком."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import BackgroundJobState

Outcome = Literal["linked", "outside_program", "service", "mixed_resolved", "unresolved"]
Role = Literal["definition", "explanation", "example", "exercise", "reference"]


class StrictModel(BaseModel):
    """Неизвестные поля не могут менять протокол."""

    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    """Адрес фрагмента либо page:<material UUID>:<page number>."""

    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    ref: str
    quote: str = Field(default="", max_length=16000)
    description: str = Field(default="", max_length=4000)


class Link(StrictModel):
    """Назначение не заменяет происхождение Binding."""

    topic_id: UUID
    fragment_id: UUID
    semantic_kind: Literal["content", "mention", "context", "prerequisite"]
    roles: list[Role] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1, max_length=64)


class Disposition(StrictModel):
    """Неперекрывающиеся диапазоны покрывают каждый фрагмент ровно один раз."""

    fragment_id: UUID
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    outcome: Literal["content", "mention", "context", "outside_program", "service", "unresolved"]


class Finding(StrictModel):
    """Составное предложение остаётся отдельным проверяемым свидетельством."""

    kind: Literal[
        "new_topic",
        "rename",
        "split",
        "merge",
        "prerequisite",
        "overlap",
        "conflict",
        "joint_study",
    ]
    explanation: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class BlockDecision(StrictModel):
    """Модель предлагает исход, сервер перепроверяет полный учёт частей."""

    target_id: UUID
    outcome: Outcome
    reason: str = ""
    dispositions: list[Disposition] = Field(max_length=4096)
    links: list[Link] = Field(default_factory=list, max_length=128)
    findings: list[Finding] = Field(default_factory=list, max_length=32)


class Limits(StrictModel):
    """Общий предел охватывает повторы шлюза, а не только логические вызовы."""

    max_calls: int = Field(default=100, ge=1, le=100000)
    max_total_tokens: int = Field(default=400000, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)


class RunPlan(StrictModel):
    """Офлайновая область запуска; выбор реальной модели подключается в И3."""

    material_ids: list[UUID] = Field(min_length=1, max_length=100)
    context_material_ids: list[UUID] = Field(default_factory=list, max_length=100)
    mode: Literal["initial", "incremental", "deep_program"] = "initial"
    expected_program_revision: int = Field(ge=0)
    limits: Limits = Field(default_factory=Limits)
    roles: dict[str, str] = Field(default_factory=dict)


class RunStart(RunPlan):
    """Идемпотентность относится ко всему телу запроса."""

    request_key: str = Field(min_length=1, max_length=160)
    preflight_fingerprint: str


class RunControl(StrictModel):
    """Generation защищает от команд устаревшей вкладки."""

    action: Literal["pause", "resume", "cancel"]
    expected_generation: int = Field(ge=0)


class PreflightRead(StrictModel):
    """Снимок разнородных полей предметных сущностей, без копии текста книги."""

    fingerprint: str
    snapshot: dict[str, Any]
    blocks: int
    execution_available: bool
    limits: Limits


class RunRead(StrictModel):
    """Работа и смысловые исходы — независимые оси."""

    id: UUID
    job_id: UUID
    state: BackgroundJobState
    execution_generation: int
    stop_reason: str | None
    snapshot: dict[str, Any]
    fingerprints: dict[str, str]
    stale: bool
    primary: dict[str, int]
    outcomes: dict[str, int]
    research: dict[str, int]
    pending_synthesis: int
    costs: dict[str, int | float]
    pause_requested: bool


class OverviewRead(StrictModel):
    """Неопределённость и знаменатели всегда присутствуют в ответе."""

    coverage_revision: int
    program_revision: int
    source_revisions: dict[str, int]
    partial: bool
    total: int
    distribution: dict[str, int]
    topics: dict[str, int]
    material_ratio: dict[str, int | float | str | None]
    findings: int


class BlockRead(StrictModel):
    """Текущая проекция одного блока."""

    block_id: UUID
    material_id: UUID
    revision: int
    bucket: str
    has_content: bool
    result_id: UUID | None


class BlocksRead(StrictModel):
    """Ограниченная страница с полным знаменателем."""

    items: list[BlockRead]
    total: int
    next_offset: int | None


class EvidenceRead(StrictModel):
    """Текст из оригинала и явная недоступность исторического локатора."""

    id: str
    key: str
    ref: str
    quote: str
    description: str
    repair: str
    start: int | None = None
    end: int | None = None
    original_ref: str | None = None
    available: bool
    stale: bool
    origin: str | None
    applied: bool
    locator: dict[str, Any] = Field(default_factory=dict)
