"""Контракт модельных сценариев Уроков: заказ урока, оценка перед запуском, итог сборки."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.ai.schemas import AiModelSelection
from app.lessons.schemas import ApiModel, LessonLevel, LessonTemplate
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


class LessonAiBuildWrite(LessonAiOrder):
    # Предел расхода запуска; без него — верхняя граница оценки.
    max_cost_usd: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=6)
    confirm_unknown_price: bool = False


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
