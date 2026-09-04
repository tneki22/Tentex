"""Единый контракт подготовки; клиентские типы генерируются из OpenAPI."""

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WorkKind = Literal["learn", "answer", "review", "gaps", "final"]
ActivityKind = Literal["view", "reading", "material", "conspect", "chat", "answer", "manual"]
AnswerMode = Literal["memory", "supported"]
Origin = Literal["manual", "local", "ai"]


class Contract(BaseModel):
    """Опечатка в команде не должна молча менять смысл сохранённых данных."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class BusyWindow(Contract):
    """Недоступный интервал может переходить через полночь."""

    start: time
    end: time
    weekday: int | None = Field(default=None, ge=0, le=6)
    on_date: date | None = None


class PreparationConfig(Contract):
    """Бюджет — ограничение поверх свободных часов, а не замена сна."""

    timezone: str = "Europe/Moscow"
    day_boundary: time = time(4)
    sleep_start: time = time(23)
    sleep_end: time = time(7)
    daily_minutes: int | None = Field(default=None, ge=0, le=1440)
    weekday_minutes: dict[int, int] = Field(default_factory=dict)
    date_minutes: dict[date, int] = Field(default_factory=dict)
    rest_dates: list[date] = Field(default_factory=list)
    busy_windows: list[BusyWindow] = Field(default_factory=list)
    exam_day_enabled: bool = False
    exam_reserve_minutes: int = Field(default=120, ge=0, le=1440)
    final_day_ratio: float = Field(default=0.5, ge=0, le=1)
    max_new_per_day: int = Field(default=10, ge=1, le=10000)
    max_reviews_per_day: int = Field(default=50, ge=1, le=10000)
    max_interval_days: int = Field(default=365, ge=1, le=3650)
    debt_rule: Literal["spread", "catch_up", "dismiss"] = "spread"
    coach_tone: Literal["calm", "gentle", "strict"] = "calm"
    ai_instructions: dict[str, str] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        """Неподдерживаемая зона обнаруживается до расчёта календаря."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Неизвестный часовой пояс") from exc
        return value

    @field_validator("weekday_minutes")
    @classmethod
    def valid_week(cls, value: dict[int, int]) -> dict[int, int]:
        """Недельные исключения используют индексы понедельник=0…воскресенье=6."""
        if any(k not in range(7) or v not in range(1441) for k, v in value.items()):
            raise ValueError("День недели 0–6, бюджет 0–1440 минут")
        return value

    @field_validator("date_minutes")
    @classmethod
    def valid_days(cls, value: dict[date, int]) -> dict[date, int]:
        """Дата может иметь нулевой бюджет, но не отрицательный."""
        if any(v not in range(1441) for v in value.values()):
            raise ValueError("Бюджет 0–1440 минут")
        return value


class SettingsRead(Contract):
    """Ревизия защищает настройки от двух одновременно открытых окон."""

    revision: int
    config: PreparationConfig


class SettingsWrite(Contract):
    """Настройки заменяются целиком после проверки ожидаемой ревизии."""

    expected_revision: int
    config: PreparationConfig


class Phase(Contract):
    """Название блока свободное; алгоритмы используют назначение kind."""

    id: UUID
    title: str = Field(min_length=1, max_length=160)
    start: date
    end: date
    kind: WorkKind = "learn"
    order: int = Field(default=0, ge=0)
    origin: Origin = "manual"

    @model_validator(mode="after")
    def valid_range(self):
        if self.end < self.start:
            raise ValueError("Конец блока раньше начала")
        return self


class PlanItem(Contract):
    """Одна дата назначается билету целиком, topic_ids вычисляет сервер."""

    id: UUID
    unit_id: UUID
    on_date: date
    kind: WorkKind = "learn"
    phase_id: UUID | None = None
    minutes: int = Field(default=30, ge=1, le=10080)
    order: int = Field(default=0, ge=0)
    pinned: bool = False
    origin: Origin = "manual"
    estimate_source: str = "Начальная оценка"
    reason: str = "Добавлено вручную"


class UnitRead(Contract):
    """Билет — одна единица планирования с несколькими изучаемыми вопросами."""

    id: UUID
    title: str
    path: list[str]
    kind: Literal["ticket", "question", "task"]
    topic_ids: list[UUID]
    topic_titles: list[str]
    target_level: str
    minutes: int
    estimate_source: str


class PlanRead(Contract):
    """Выполнение отделено от редактируемой структуры версии плана."""

    revision: int
    program_revision: int
    settings_revision: int
    stale: bool
    phases: list[Phase]
    items: list[PlanItem]
    completed_ids: list[UUID]
    unassigned_ids: list[UUID]
    can_undo: bool


class DraftWrite(Contract):
    """Один preview-контракт используется редактором, алгоритмом и ИИ."""

    expected_plan_revision: int
    expected_program_revision: int
    expected_settings_revision: int
    mode: Literal["manual", "count", "time", "catch_up", "spread", "dismiss"] = "manual"
    phases: list[Phase] | None = None
    items: list[PlanItem] | None = None
    unit_ids: list[UUID] | None = None
    start: date | None = None
    end: date | None = None


class DayLoad(Contract):
    """Фактическое время и вместимость дня не зависят от числа дорожек."""

    date: date
    capacity_minutes: int
    remaining_minutes: int
    planned_minutes: int
    active_seconds: int
    planned_count: int
    completed_count: int
    overload_minutes: int
    is_rest: bool
    passed_count: int = 0
    confirmed_count: int = 0
    new_count: int = 0
    review_count: int = 0


class DraftRead(Contract):
    """Preview хранится на сервере и переживает уход с экрана."""

    id: UUID
    base_revision: int
    program_revision: int
    settings_revision: int
    phases: list[Phase]
    items: list[PlanItem]
    removed_ids: list[UUID]
    unassigned_ids: list[UUID]
    changes: list[str]
    days: list[DayLoad]
    origin: Origin


class ApplyDraftWrite(Contract):
    """None принимает все изменения; пустой список не принимает задания."""

    selected_item_ids: list[UUID] | None = None
    apply_phases: bool = True


class RevisionWrite(Contract):
    """Команда отмены относится к конкретной видимой версии."""

    expected_revision: int


class TimeIntervalWrite(Contract):
    """Идентификатор пакета обеспечивает повторную доставку без дублей."""

    id: UUID
    session_id: UUID
    node_id: UUID
    kind: ActivityKind
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


class TimeBatchWrite(Contract):
    """Пакеты ограничены для предсказуемого восстановления после отсутствия сети."""

    intervals: list[TimeIntervalWrite] = Field(max_length=200)


class TimeBatchRead(Contract):
    """Клиент удаляет только подтверждённые id из временного буфера."""

    accepted_ids: list[UUID]


class ManualActivityWrite(Contract):
    """Ручное занятие не выдаётся за независимую проверку знания."""

    id: UUID
    node_id: UUID | None = None
    occurred_at: datetime
    seconds: int = Field(default=0, ge=0, le=86400)
    note: str = Field(default="", max_length=2000)
    understood: bool = False


class UnderstoodWrite(Contract):
    """Отметка применяется к вопросу или целому билету."""

    unit_id: UUID
    understood: bool = True


class QualityWrite(Contract):
    """Качество воспроизведения не заменяет вердикт судьи."""

    quality: int = Field(ge=0, le=5)


class TopicProgress(Contract):
    """Причина статуса доступна рядом с числом, а материал — отдельная ось."""

    node_id: UUID
    title: str
    path: list[str]
    unit_id: UUID
    target_level: str
    status: Literal["unseen", "understood", "practiced", "mastered"]
    has_material: bool
    successful_attempts: int
    required_successes: int
    latest_outcome: str | None
    due: date | None
    interval_days: int
    reason: str
    missed_points: list[str]
    active_seconds: int


class ActivityRead(Contract):
    """Ответ хранится в Attempt; журнал содержит только ссылку и краткую проекцию."""

    id: UUID
    node_id: UUID | None
    title: str
    path: list[str]
    kind: ActivityKind
    occurred_at: datetime
    seconds: int | None
    note: str
    attempt_id: UUID | None = None
    chat_id: UUID | None = None
    outcome: str | None = None
    method: str | None = None
    self_assessment: str | None = None
    answer_mode: AnswerMode | None = None
    quality: int | None = None
    understood: bool = False


class HistoryRead(Contract):
    """Фильтры выполняются до пагинации, а не на текущей странице."""

    items: list[ActivityRead]
    total: int
    offset: int
    limit: int


class MemoryScenario(Contract):
    """Диапазон относится к сохранению уже подтверждённой части программы."""

    lower_percent: float
    upper_percent: float
    estimated_topics: int


class MemoryForecast(Contract):
    """Нет данных — нет процента; ИИ не вычисляет вероятность памяти."""

    available: bool
    reason: str
    observations: int
    distinct_topics: int
    observed_days: int
    confirmed_topics: int
    unknown_topics: int
    with_plan: MemoryScenario | None = None
    without_study: MemoryScenario | None = None
    method: str = "Эмпирический диапазон Уилсона по отложенным проверкам"


class PreparationSummary(Contract):
    """Чтение, выполнение расписания и подтверждение знания не смешиваются."""

    total_topics: int
    passed_topics: int
    confirmed_topics: int
    mastered_topics: int
    today_seconds: int
    week_seconds: int
    streak_days: int
    attempts_count: int
    passed_attempts: int
    partial_attempts: int
    failed_attempts: int
    pending_attempts: int
    disputed_attempts: int
    memory_attempts: int
    supported_attempts: int
    available_minutes: int
    remaining_work_minutes: int
    projected_finish: date | None
    pace_minutes_per_day: float | None
    pace_explanation: str
    seconds_by_kind: dict[str, int]


class CoachRead(Contract):
    """Локальная рекомендация доступна и во время ожидания внешней модели."""

    date: date
    text: str
    origin: Literal["local", "ai"]
    action: Literal["start", "redistribute", "create"]
    job_id: UUID | None = None
    reason: str | None = None


class OverviewRead(Contract):
    """Согласованный снимок экрана на серверное время."""

    project_id: UUID
    project_name: str
    readonly: bool = False
    now: datetime
    today: date
    deadline: date | None
    exam_time: time | None
    exam_at: datetime | None = None
    settings: SettingsRead
    plan: PlanRead
    units: list[UnitRead]
    days: list[DayLoad]
    topics: list[TopicProgress]
    summary: PreparationSummary
    memory: MemoryForecast
    coach: CoachRead


class QueueItem(Contract):
    """Одна строка очереди содержит целый билет или одиночный вопрос."""

    unit_id: UUID
    title: str
    topic_ids: list[UUID]
    kind: WorkKind
    minutes: int
    reason: str


class QueueRead(Contract):
    """Сохранённая позиция позволяет вернуться к дню после перезагрузки."""

    date: date
    items: list[QueueItem]
    position: int
    topic_position: int
    completed: bool


class QueuePositionWrite(Contract):
    """Курсор очереди меняется независимо от версии календаря."""

    position: int = Field(ge=0)
    topic_position: int = Field(default=0, ge=0)


class PreparationAiWrite(Contract):
    """Один запрос для трёх ролей и последовательного полного плана."""

    action: Literal["phases", "distribute", "full", "coach"]
    instruction: str = Field(default="", max_length=8000)
    confirmed: bool = False
    automatic: bool = False
    expected_plan_revision: int
    expected_program_revision: int
    expected_settings_revision: int


class AiStartRead(Contract):
    """Для offline и подтверждения затрат запуск может не создавать job."""

    job_id: UUID | None
    coach: CoachRead | None = None
    reason: str | None = None
