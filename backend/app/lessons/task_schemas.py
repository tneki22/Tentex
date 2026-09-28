"""Схемы заданий урока: подготовленное задание, чтение, попытка и её итог."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import AiModelSelection
from app.models import (
    AttemptOutcome,
    GradeMethod,
    LessonBasis,
    StudyTaskDifficulty,
    StudyTaskForm,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class StudyTaskDraftRead(ApiModel):
    """Задание, проверенное сервером, но ещё не записанное: в предложении и при сборке.

    `payload` — что видит читатель (варианты, шаги вперемешку, пары), `answer_key` —
    ключ проверки. `supports` — метки кусков урока, на которые опирается пояснение.
    """

    form: StudyTaskForm
    prompt_md: str
    payload: dict[str, Any]
    answer_key: dict[str, Any]
    reference_md: str | None
    explanation_md: str
    hint_md: str | None
    difficulty: StudyTaskDifficulty
    basis: LessonBasis
    supports: list[str]


class StudyTaskSourceRead(ApiModel):
    source_name: str
    page_from: int
    page_to: int


class StudyTaskAttemptRead(ApiModel):
    id: UUID
    activity_id: UUID
    ordinal: int
    answer: dict[str, Any] | None
    text: str | None
    # null — открытый ответ сохранён, но ещё не проверен (модели недоступны).
    outcome: AttemptOutcome | None
    method: GradeMethod | None
    score: float | None
    # Верен ли каждый пункт формы: вариант, пропуск, позиция, пара.
    items: list[bool]
    summary: str
    # Открытый ответ: что засчитано, что упущено, что неверно.
    credited: list[str]
    missed: list[str]
    wrong: list[str]
    pending_reason: str | None
    created_at: datetime


class StudyTaskRead(ApiModel):
    activity_id: UUID
    form: StudyTaskForm
    prompt_md: str
    payload: dict[str, Any]
    # Ключ отдаётся целиком: «Показать ответ» и разбор после проверки — у клиента.
    answer_key: dict[str, Any]
    reference_md: str | None
    explanation_md: str | None
    hint_md: str | None
    difficulty: StudyTaskDifficulty
    basis: LessonBasis
    sources: list[StudyTaskSourceRead]
    attempts: int
    last_attempt: StudyTaskAttemptRead | None


class StudyTaskAttemptWrite(ApiModel):
    """Ответ по форме: `{choice}`, `{choices}`, `{blanks}`, `{value}`, `{order}`, `{pairs}`;
    у открытого ответа — `text`."""

    answer: dict[str, Any] | None = None
    text: str | None = Field(default=None, max_length=10_000)
    active_seconds: int | None = Field(default=None, ge=0, le=86_400)


class LessonPracticeOrder(ApiModel):
    """«Добавить практику»: сколько заданий, на чём основаны, какой моделью."""

    basis: LessonBasis = LessonBasis.SOURCES_AND_MODEL
    count: int = Field(default=5, ge=3, le=10)
    request: str = Field(default="", max_length=1_000)
    model: AiModelSelection | None = None


class LessonPracticeWrite(LessonPracticeOrder):
    expected_revision: int = Field(ge=1)
    max_cost_usd: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=6)
    confirm_unknown_price: bool = False
