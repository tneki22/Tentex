"""Структурированный контракт трёх ролей подготовки и оценки полного запуска."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.ai.schemas import AiPreflight
from app.preparation.schemas import Contract, Phase, WorkKind


class ProgramContextRead(Contract):
    """Полное дерево раскрывается пользователю до обращения к модели."""

    id: UUID
    parent_id: UUID | None
    node_type: str
    exam_kind: str | None
    title: str
    path: list[str]
    sort_order: int
    target_level: str | None
    subpoints: list[str]
    has_answer: bool
    answer_chars: int


class PreparationAiPreflightRead(Contract):
    """Стоимость последовательного запуска складывается из всех обращений."""

    action: Literal["phases", "distribute", "full", "coach"]
    calls: list[AiPreflight]
    context: list[ProgramContextRead]
    confirmation_required: bool
    confirmation_reasons: list[str]


class PhaseSuggestion(Contract):
    """Блоки остаются предложением до отдельного применения пользователем."""

    phases: list[Phase] = Field(min_length=1, max_length=100)


class Assignment(Contract):
    """Модель назначает целый серверный unit, а не отдельного ребёнка билета."""

    unit_id: UUID
    on_date: date
    phase_id: UUID | None = None
    kind: WorkKind = "learn"
    minutes: int = Field(ge=1, le=10080)
    reason: str = Field(min_length=1, max_length=1000)


class Unassigned(Contract):
    """Каждое неназначенное задание получает явную причину."""

    unit_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class DistributionSuggestion(Contract):
    """Полнота проверяется по объединению assigned и unassigned каждого пакета."""

    items: list[Assignment] = Field(default_factory=list, max_length=500)
    unassigned: list[Unassigned] = Field(default_factory=list, max_length=500)


class CoachSuggestion(Contract):
    """Факт выбирается из серверного списка; модель формулирует следствие и шаг."""

    fact_key: Literal["today", "remaining", "yesterday"]
    consequence: str = Field(min_length=1, max_length=600)
    next_step: str = Field(min_length=1, max_length=600)
