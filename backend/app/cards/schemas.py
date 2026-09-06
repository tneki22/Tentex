"""Публичный карточный контракт; клиентские типы генерируются из OpenAPI."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CardStateValue = Literal["active", "suspended"]
CardSourceValue = Literal["none", "fragment", "reference"]
CardScope = Literal["today", "hard", "selected", "all"]
CardPace = Literal["calm", "fast"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CardUnitRead(Contract):
    id: UUID
    title: str
    path: list[str]
    kind: Literal["ticket", "question", "task"]
    topic_ids: list[UUID]
    reference_revision: int | None = None


class CardSourceWrite(Contract):
    kind: CardSourceValue = "none"
    fragment_id: UUID | None = None
    reference_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def consistent_source(self) -> Self:
        if self.kind == "fragment" and self.fragment_id is None:
            raise ValueError("Для источника-фрагмента нужен fragment_id")
        if self.kind != "fragment" and self.fragment_id is not None:
            raise ValueError("fragment_id допустим только для источника-фрагмента")
        if self.kind != "reference" and self.reference_revision is not None:
            raise ValueError("Ревизия допустима только для эталонного ответа")
        return self


class CardWrite(Contract):
    program_node_id: UUID | None = None
    front: str = Field(min_length=1, max_length=20_000)
    back: str = Field(min_length=1, max_length=50_000)
    hint: str | None = Field(default=None, max_length=10_000)
    source: CardSourceWrite = Field(default_factory=CardSourceWrite)
    state: CardStateValue = "active"


class CardCreate(CardWrite):
    pass


class CardUpdate(Contract):
    expected_revision: int = Field(ge=1)
    program_node_id: UUID | None = None
    front: str | None = Field(default=None, min_length=1, max_length=20_000)
    back: str | None = Field(default=None, min_length=1, max_length=50_000)
    hint: str | None = Field(default=None, max_length=10_000)
    source: CardSourceWrite | None = None
    state: CardStateValue | None = None


class CardSourceRead(Contract):
    kind: CardSourceValue
    fragment_id: UUID | None
    reference_revision: int | None
    label: str
    material_name: str | None = None
    page_number: int | None = None
    text_snapshot: str | None = None
    lost: bool = False


class CardRead(Contract):
    id: UUID
    project_id: UUID
    program_node_id: UUID | None
    unit: CardUnitRead | None
    front: str
    back: str
    hint: str | None
    source: CardSourceRead
    state: CardStateValue
    revision: int
    deleted_at: datetime | None
    last_confidence: int | None
    attempt_count: int
    last_reviewed_at: datetime | None
    average_last_three: float | None
    created_at: datetime
    updated_at: datetime


class CardListRead(Contract):
    items: list[CardRead]
    total: int
    units: list[CardUnitRead]


class BulkCardItem(Contract):
    id: UUID
    expected_revision: int = Field(ge=1)


class RevisionWrite(Contract):
    expected_revision: int = Field(ge=1)


class CardBulkWrite(Contract):
    items: list[BulkCardItem] = Field(min_length=1, max_length=500)
    action: Literal["activate", "suspend", "delete", "restore"]


class FragmentPrefillRead(Contract):
    fragment_id: UUID
    proposed_program_node_id: UUID | None
    back: str
    source: CardSourceRead


class TodayUnitRead(Contract):
    unit: CardUnitRead
    card_count: int
    covered: bool
    cards: list[CardRead]


class ConfidenceBucket(Contract):
    confidence: int = Field(ge=1, le=4)
    count: int


class CardAnalyticsRead(Contract):
    period: Literal[7, 30]
    observation_count: int
    distribution: list[ConfidenceBucket]
    hard_card_count: int
    hardest_unit: CardUnitRead | None
    hardest_low_share: float | None
    hardest_observation_count: int


class CardSessionSummaryRead(Contract):
    id: UUID
    scope: CardScope
    pace: CardPace
    position: int
    card_count: int
    revision: int


class CardOverviewRead(Contract):
    program_exists: bool
    plan_exists: bool
    today_units: list[TodayUnitRead]
    covered_unit_count: int
    active_card_count: int
    estimated_minutes: int
    recent_cards: list[CardRead]
    hard_cards: list[CardRead]
    analytics: CardAnalyticsRead
    active_session: CardSessionSummaryRead | None
    units: list[CardUnitRead]


class SessionCardRead(Contract):
    card_id: UUID
    unit_id: UUID | None
    unit_title: str | None
    front: str
    back: str
    hint: str | None
    source: CardSourceRead
    state: Literal["pending", "rated", "deferred"]
    confidence: int | None = None


class CardSessionCreate(Contract):
    scope: CardScope
    selected_unit_ids: list[UUID] = Field(default_factory=list)
    pace: CardPace = "calm"
    limit_minutes: Literal[5, 10, 15] | None = None
    replace_active: bool = False

    @model_validator(mode="after")
    def selected_scope_has_units(self) -> Self:
        if self.scope == "selected" and not self.selected_unit_ids:
            raise ValueError("Выберите хотя бы один вопрос или билет")
        return self


class CardSessionRead(Contract):
    id: UUID
    project_id: UUID
    scope: CardScope
    selected_unit_ids: list[UUID]
    pace: CardPace
    limit_minutes: int | None
    queue: list[SessionCardRead]
    position: int
    active_seconds: int
    limit_reached: bool
    state: Literal["active", "completed", "cancelled"]
    revision: int
    missing_units: list[CardUnitRead]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class SessionProgressWrite(Contract):
    expected_revision: int = Field(ge=1)
    position: int = Field(ge=0)
    active_seconds: int = Field(ge=0, le=604_800)


class SessionReviewWrite(Contract):
    id: UUID
    expected_revision: int = Field(ge=1)
    confidence: int = Field(ge=1, le=4)
    active_seconds: int = Field(default=0, ge=0, le=86_400)


class SessionDeferWrite(Contract):
    id: UUID
    expected_revision: int = Field(ge=1)
    active_seconds: int = Field(default=0, ge=0, le=86_400)


class SessionFinishWrite(Contract):
    expected_revision: int = Field(ge=1)
    action: Literal["complete", "cancel"] = "complete"


class SessionRetryWrite(Contract):
    expected_revision: int = Field(ge=1)
