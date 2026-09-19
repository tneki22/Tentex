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
    """Общий предел охватывает повторы шлюза, а не только логические вызовы.

    Пустые вызовы и токены не значат «без предела»: они выводятся из области
    запуска при старте. Плоские 100 вызовов и 400 000 токенов останавливали
    книгу на середине, хотя денежный предел человека не был и близко исчерпан.
    """

    max_calls: int | None = Field(default=None, ge=1, le=100000)
    max_total_tokens: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)


class RoleSelection(StrictModel):
    """Явный выбор модели; проход 2 не наследует дешёвый default."""

    provider_id: UUID
    model_id: str = Field(min_length=1)


class RunPlan(StrictModel):
    """Область запуска и явно выбранные модели ролей прохода 2."""

    material_ids: list[UUID] = Field(min_length=1, max_length=100)
    context_material_ids: list[UUID] = Field(default_factory=list, max_length=100)
    mode: Literal["initial", "incremental", "deep_program"] = "initial"
    expected_program_revision: int = Field(ge=0)
    limits: Limits = Field(default_factory=Limits)
    roles: dict[Literal["overview", "research"], RoleSelection] = Field(default_factory=dict)


class RunStart(RunPlan):
    """Идемпотентность относится ко всему телу запроса."""

    request_key: str = Field(min_length=1, max_length=160)
    preflight_fingerprint: str


class RunControl(StrictModel):
    """Generation защищает от команд устаревшей вкладки."""

    action: Literal["pause", "resume", "cancel"]
    expected_generation: int = Field(ge=0)
    # Продолжение после исчерпанного предела без нового потолка сразу же встанет снова.
    limits: Limits | None = None


class ModelRoleRead(StrictModel):
    """Разрешённая модель роли: context_length нужен экрану и расчёту пакета, а не только UI."""

    provider_id: str
    model_id: str
    model_source: str
    context_length: int | None = None
    prompt_version: str


class PreflightRead(StrictModel):
    """Снимок разнородных полей предметных сущностей, без копии текста книги."""

    fingerprint: str
    snapshot: dict[str, Any]
    blocks: int
    execution_available: bool
    execution_issue: str | None = None
    model_roles: dict[str, ModelRoleRead] = Field(default_factory=dict)
    limits: Limits
    # Чем оборачивается запуск: пакетов не меньше, постоянная часть каждого запроса.
    packets_at_least: int = 0
    prompt_overhead_tokens: int = 0
    packet_input_tokens: int = 0


class CompactLink(StrictModel):
    """Ссылка в alias-протоколе; текст опоры сервер берёт из снимка."""

    topic: str
    semantic_kind: Literal["content", "mention", "context", "prerequisite"]
    roles: list[Role] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list, max_length=64)


class CompactPart(StrictModel):
    """Исход одного фрагмента пакета."""

    fragment: str
    outcome: Literal["content", "mention", "context", "outside_program", "service", "unresolved"]
    links: list[CompactLink] = Field(default_factory=list, max_length=16)


class CompactDecision(StrictModel):
    """Диапазон определяется порядком targets только в текущем пакете."""

    from_target: str
    to_target: str
    outcome: Outcome
    reason: str = ""
    parts: list[CompactPart] = Field(default_factory=list, max_length=4096)


class SectionDescription(StrictModel):
    """Независимое описание раздела без подгонки под программу."""

    section: str
    summary: str = Field(min_length=1, max_length=4000)


class OverviewPacketResponse(StrictModel):
    """Компактный ответ первичного обзора."""

    decisions: list[CompactDecision] = Field(max_length=4096)
    section_descriptions: list[SectionDescription] = Field(default_factory=list, max_length=64)


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
    limits: dict[str, int | float | None]
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
    content_titles: list[str] = Field(default_factory=list)
    reading_titles: list[str] = Field(default_factory=list)
    material_ratio: dict[str, int | float | str | None]
    findings: int
    latest_run_id: UUID | None = None
    latest_run_state: BackgroundJobState | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


class BlockRead(StrictModel):
    """Текущая проекция одного блока."""

    block_id: UUID
    material_id: UUID
    revision: int
    bucket: str
    has_content: bool
    result_id: UUID | None
    title: str | None = None
    page_from: int
    page_to: int
    material_name: str
    reason: str | None = None


class BlocksRead(StrictModel):
    """Ограниченная страница с полным знаменателем и составом остатка."""

    coverage_revision: int
    items: list[BlockRead]
    total: int
    next_offset: int | None
    distribution: dict[str, int] = Field(default_factory=dict)


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
    binding_id: UUID | None = None
    topic_id: UUID | None = None
    topic_title: str | None = None
    material_id: UUID | None = None
    material_name: str | None = None
    page_from: int | None = None
    page_to: int | None = None
    fragment_ids: list[UUID] = Field(default_factory=list)
    text: str = ""
    roles: list[str] = Field(default_factory=list)
    semantic_kind: str | None = None
    status: str | None = None
    mechanism: str | None = None
    quality: str | None = None
    hidden: bool = False
    preferred: bool = False
    legacy: bool = False
    linked_topics: list[dict[str, Any]] = Field(default_factory=list)


class TopicRead(StrictModel):
    """Строка программы с текущим основанием для чтения."""

    node_id: UUID
    title: str
    parent_title: str | None = None
    evidence_count: int
    mention_count: int
    hidden_count: int
    legacy_count: int
    best_evidence_id: str | None = None


class TopicsRead(StrictModel):
    """Пагинированные темы одной ревизии покрытия."""

    coverage_revision: int
    items: list[TopicRead]
    total: int
    next_offset: int | None


class EvidenceSummary(StrictModel):
    """Компактная карточка точной опоры без числовой уверенности."""

    id: str
    binding_id: UUID
    topic_id: UUID
    material_id: UUID
    material_name: str
    page_from: int
    page_to: int
    fragment_ids: list[UUID]
    quote: str
    description: str = ""
    roles: list[str] = Field(default_factory=list)
    semantic_kind: str | None = None
    status: str
    mechanism: str
    quality: str
    available: bool
    stale: bool
    hidden: bool
    preferred: bool
    legacy: bool


class TopicEvidenceRead(StrictModel):
    """Группы чтения одной темы; разные источники остаются отдельными карточками."""

    coverage_revision: int
    topic_id: UUID
    topic_title: str
    best_evidence_id: str | None = None
    starter: list[EvidenceSummary] = Field(default_factory=list)
    explanations: list[EvidenceSummary] = Field(default_factory=list)
    practice: list[EvidenceSummary] = Field(default_factory=list)
    depth: list[EvidenceSummary] = Field(default_factory=list)
    mentions: list[EvidenceSummary] = Field(default_factory=list)
    hidden: list[EvidenceSummary] = Field(default_factory=list)
    legacy: list[EvidenceSummary] = Field(default_factory=list)


DecisionAction = Literal[
    "confirm",
    "remove",
    "restore",
    "reassign",
    "change_role",
    "hide",
    "show",
    "prefer",
    "clear_prefer",
    "service",
    "outside_goal",
]


class DecisionWrite(StrictModel):
    """Одна осознанная команда над связью или блоком."""

    request_key: str = Field(min_length=1, max_length=160)
    expected_coverage_revision: int = Field(ge=0)
    action: DecisionAction
    binding_id: UUID | None = None
    evidence_id: str | None = None
    block_id: UUID | None = None
    topic_ids: list[UUID] = Field(default_factory=list, max_length=100)
    role: Role | None = None
    semantic_kind: Literal["content", "mention", "context"] | None = None


class DecisionReceipt(StrictModel):
    """Стабильный ответ идемпотентной команды."""

    request_key: str
    action: DecisionAction
    coverage_revision: int
    action_sequence: int
    binding_ids: list[UUID] = Field(default_factory=list)
    message: str
