"""Компактный контракт планирования уроков без экзаменационной аналитики."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class LessonPlanItem(Contract):
    id: UUID
    lesson_id: UUID
    title: str
    on_date: date
    minutes: int = Field(ge=1, le=10080)
    origin: Literal["manual", "local"] = "manual"


class LessonCandidate(Contract):
    id: UUID
    title: str
    minutes: int
    completed_at: datetime | None
    eligible: bool


class LessonTimeRow(Contract):
    lesson_id: UUID | None
    title: str
    seconds: int


class LessonPlanningRead(Contract):
    revision: int
    today: date
    deadline: date | None
    daily_minutes: int
    days_per_week: int
    readonly: bool
    lessons: list[LessonCandidate]
    items: list[LessonPlanItem]
    unassigned_ids: list[UUID]
    unavailable_ids: list[UUID]
    estimated_finish: date | None
    outside_deadline_count: int
    today_seconds: int
    today_by_lesson: list[LessonTimeRow]


class DistributionWrite(Contract):
    mode: Literal["append", "rebuild_future"] = "append"


class DistributionRead(Contract):
    base_revision: int
    items: list[LessonPlanItem]
    unassigned_ids: list[UUID]
    estimated_finish: date | None


class PlanWrite(Contract):
    expected_revision: int = Field(ge=0)
    items: list[LessonPlanItem] = Field(max_length=10000)


class LessonTimeInterval(Contract):
    id: UUID
    session_id: UUID
    lesson_id: UUID
    started_at: datetime
    ended_at: datetime

    @model_validator(mode="after")
    def bounded_interval(self):
        if self.started_at.tzinfo is None or self.ended_at.tzinfo is None:
            raise ValueError("Нужен часовой пояс времени")
        seconds = (self.ended_at - self.started_at).total_seconds()
        if not 0 < seconds <= 300:
            raise ValueError("Интервал должен быть от 0 до 300 секунд")
        return self


class LessonTimeBatch(Contract):
    intervals: list[LessonTimeInterval] = Field(max_length=200)


class LessonTimeResult(Contract):
    accepted_ids: list[UUID]
    ignored_ids: list[UUID]
