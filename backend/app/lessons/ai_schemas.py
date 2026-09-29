"""Контракт модельных сценариев Уроков: заказ урока, оценка перед запуском, итог сборки."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.ai.schemas import AiModelSelection
from app.lessons.ai_prompts import EnrichOpKind, StepKind
from app.lessons.schemas import ApiModel, LessonLevel, LessonTemplate
from app.lessons.task_schemas import StudyTaskDraftRead
from app.models import LessonBasis, SourceRole


class LessonAiOrder(ApiModel):
    """Что пользователь выбрал в диалоге «Собрать урок с ИИ»."""

    program_node_id: UUID
    template: LessonTemplate = "explain"
    level: LessonLevel = "draft"
    basis: LessonBasis = LessonBasis.SOURCES_AND_MODEL
    # Без списка — материалы по умолчанию: с диапазоном темы, иначе все не справочные.
    material_ids: list[UUID] | None = Field(default=None, max_length=50)
    minutes: int | None = Field(default=None, ge=5, le=240)
    wishes: str = Field(default="", max_length=1_000)
    # Без значения — конспект учитывается, если он не пуст.
    use_conspect: bool | None = None
    model: AiModelSelection | None = None


class LessonAiPlanStep(ApiModel):
    """Шаг плана — как его вернула модель и как его правят в редакторе плана."""

    kind: StepKind
    title: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1, max_length=500)
    # Метки кусков карты плана: `C4`.
    sources: list[str] = Field(default_factory=list, max_length=3)
    collapsed: bool | None = None
    introduces: list[str] = Field(default_factory=list, max_length=6)


class LessonAiPlanWrite(ApiModel):
    """Правленый план: сборка берёт паспорт и куски из задачи плана `job_id`."""

    job_id: UUID
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(default="", max_length=600)
    concepts: list[str] = Field(default_factory=list, max_length=30)
    steps: list[LessonAiPlanStep] = Field(min_length=1, max_length=16)


class LessonAiRunWrite(LessonAiOrder):
    # Предел расхода запуска; без него — верхняя граница оценки.
    max_cost_usd: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=6)
    confirm_unknown_price: bool = False


class LessonAiBuildWrite(LessonAiRunWrite):
    # Есть — собрать по этому плану; нет — «Черновик» или план внутри той же задачи.
    plan: LessonAiPlanWrite | None = None


class LessonAiResumeWrite(ApiModel):
    # Предел исчерпан — продолжить можно с новым, большим.
    max_cost_usd: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=6)


class LessonAiMaterialRead(ApiModel):
    material_id: UUID
    name: str
    role: SourceRole
    priority: int
    instruction: str | None
    kind: str
    is_parsed: bool
    # Диапазон темы по оглавлению в этом материале, если он есть.
    page_from: int | None
    page_to: int | None
    selected: bool


class LessonAiLevelRead(ApiModel):
    level: LessonLevel
    calls: int
    input_tokens: int
    output_tokens: int
    # Верхняя граница: весь предел ответа каждого вызова. Null — цена модели неизвестна.
    cost_usd: Decimal | None
    available: bool
    unavailable_reason: str | None = None


class LessonAiPreflightRead(ApiModel):
    program_node_id: UUID
    topic_title: str
    materials: list[LessonAiMaterialRead]
    candidates: int
    candidate_tokens: int
    material_state: str
    notes: list[str]
    # «Только материалы» возможно, только если нашлись куски материала.
    sources_available: bool
    default_minutes: int | None
    conspect_words: int
    use_conspect: bool
    models_available: bool
    models_unavailable_reason: str | None
    provider_id: UUID | None
    model_id: str | None
    model_label: str | None
    price_known: bool
    prices_from: datetime | None
    levels: list[LessonAiLevelRead]
    # «Что увидит модель» — тот же паспорт урока, что уйдёт в промпт.
    brief_text: str


class LessonAiBuildResult(ApiModel):
    """Итог задачи `ai_lesson/build`: новый черновик и что сервер отбросил с причиной.

    `lesson_id` пуст, если сборку отменили, пока шёл вызов модели.
    """

    lesson_id: UUID | None
    dropped: list[str]
    cost_usd: Decimal | None


class LessonAiCandidateRead(ApiModel):
    """Кусок карты плана — чем можно заменить опору шага (⇄)."""

    label: str
    material_name: str
    title: str | None
    page_from: int
    page_to: int
    tokens: int
    signals: list[str]


class LessonAiPlanRead(ApiModel):
    """Итог задачи `ai_lesson/plan`: план для редактора и цена сборки по нему."""

    program_node_id: UUID
    title: str
    goal: str
    concepts: list[str]
    steps: list[LessonAiPlanStep]
    candidates: list[LessonAiCandidateRead]
    template: LessonTemplate
    level: LessonLevel
    basis: LessonBasis
    minutes: int | None
    dropped: list[str]
    # Верх цены одного шага и неизменной части (рецензент с правками у «Подробного»):
    # редактор пересчитывает стоимость, пока в плане меняют шаги.
    step_cost_usd: Decimal | None
    fixed_cost_usd: Decimal | None
    fixed_calls: int


# --- «Дополнить урок» -------------------------------------------------------------------

EnrichDepth = Literal["economy", "full"]
#: Операции предложения: пять «Дополнить» и вставка задания «Добавить практику».
ProposalOpKind = Literal[EnrichOpKind, "insert_task"]


class LessonEnrichOrder(ApiModel):
    """Что выбрано в окне «Дополнить с ИИ»: шаблона нет, урок уже есть."""

    basis: LessonBasis = LessonBasis.SOURCES_AND_MODEL
    # «Экономно» — одна порция текста урока, «Полностью» — до четырёх.
    depth: EnrichDepth = "economy"
    request: str = Field(default="", max_length=1_000)
    # Выбран блок — просьба касается только его.
    block_id: UUID | None = None
    model: AiModelSelection | None = None


class LessonEnrichWrite(LessonEnrichOrder):
    expected_revision: int = Field(ge=1)
    max_cost_usd: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=6)
    confirm_unknown_price: bool = False


class LessonEnrichPreflightRead(ApiModel):
    portions: int
    calls: int
    input_tokens: int
    cost_usd: Decimal | None
    models_available: bool
    models_unavailable_reason: str | None
    model_label: str | None
    price_known: bool


class LessonProposalSource(ApiModel):
    """Кусок урока, на который ссылается предложение меткой `S*`."""

    label: str
    block_id: UUID
    source_name: str
    page_from: int
    page_to: int


class LessonProposalOp(ApiModel):
    id: str
    op: ProposalOpKind
    block_id: UUID | None
    # Вставка внутрь куска: разрез после этого фрагмента.
    after_fragment_id: UUID | None
    variant: str | None
    body_md: str | None
    supports: list[str]
    basis: LessonBasis | None
    collapsed: bool | None
    text: str | None
    reason: str
    # Вызов модели, который предложил изменение, — у вставленного пояснения.
    run_id: UUID | None = None
    # insert_task: задание с ключом; `block_id` — после какого блока, null — в конец.
    task: StudyTaskDraftRead | None = None


class LessonProposalRead(ApiModel):
    """Итог задачи `ai_lesson/enrich` или `practice`: изменения урока, которые ждут решения."""

    kind: Literal["enrich", "practice"] = "enrich"
    lesson_id: UUID
    program_node_id: UUID
    lesson_revision: int
    summary: str
    basis: LessonBasis
    ops: list[LessonProposalOp]
    sources: list[LessonProposalSource]
    dropped: list[str]
    cost_usd: Decimal | None


class LessonProposalApplyWrite(ApiModel):
    op_ids: list[str] = Field(min_length=1, max_length=50)
    expected_revision: int = Field(ge=1)


# --- массовая сборка -------------------------------------------------------------------


class LessonAiBulkOrder(ApiModel):
    """«с ИИ» в таблице массовой подготовки: один шаблон и основа на все темы, «Черновик»."""

    program_node_ids: list[UUID] = Field(min_length=1, max_length=50)
    template: LessonTemplate = "explain"
    basis: LessonBasis = LessonBasis.SOURCES_AND_MODEL
    model: AiModelSelection | None = None


class LessonAiBulkWrite(LessonAiBulkOrder):
    max_cost_usd: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=6)
    confirm_unknown_price: bool = False


class LessonAiBulkTopicRead(ApiModel):
    program_node_id: UUID
    title: str
    candidates: int
    sources_available: bool


class LessonAiBulkPreflightRead(ApiModel):
    """Темы в порядке программы, куски каждой и общая оценка — без вызова модели."""

    topics: list[LessonAiBulkTopicRead]
    calls: int
    cost_usd: Decimal | None
    models_available: bool
    models_unavailable_reason: str | None
    model_label: str | None
    price_known: bool


class LessonAiBulkTopicResult(ApiModel):
    program_node_id: UUID
    topic_title: str
    # Нет урока — тему пропустили: `skipped` говорит почему.
    lesson_id: UUID | None
    skipped: str | None
    dropped: list[str]


class LessonAiBulkResult(ApiModel):
    """Итог задачи `ai_lesson/bulk`: черновики по темам в порядке программы."""

    kind: Literal["bulk"] = "bulk"
    lessons: list[LessonAiBulkTopicResult]
    cost_usd: Decimal | None
