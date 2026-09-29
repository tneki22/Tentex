from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.lessons.task_schemas import StudyTaskRead
from app.models import (
    LessonBasis,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonStatus,
    SourceRole,
)
from app.projects.schemas import LatestUndoableAction


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


#: Шаблон модельного урока — модуль промпта (`lessons/ai_prompts.py`), код сборки один.
LessonTemplate = Literal["explain", "guide", "practice", "cheatsheet"]
#: Глубина сборки: один вызов, план и шаги, то же с рецензентом.
LessonLevel = Literal["draft", "standard", "detailed"]


class LessonBuildRead(ApiModel):
    """Как собран модельный урок — подпись в списках и во вкладке «Урок»."""

    template: LessonTemplate
    level: LessonLevel
    basis: LessonBasis
    model_id: str | None = None
    cost_usd: str | None = None


class LessonSummaryRead(ApiModel):
    id: UUID
    title: str
    status: LessonStatus
    duration_minutes: int | None
    program_node_ids: list[UUID]
    needs_review: bool
    completed_at: datetime | None
    updated_at: datetime
    build: LessonBuildRead | None = None


class LessonsOverviewRead(ApiModel):
    lessons: list[LessonSummaryRead]


class LessonSourceRangeRead(ApiModel):
    """Диапазон темы в одном источнике: из оглавления и после уточнения границ."""

    material_id: UUID
    source_name: str
    source_role: SourceRole
    priority: int
    is_parsed: bool
    outline_page_from: int
    outline_page_to: int
    page_from: int
    page_to: int
    starts_at_heading: bool
    ends_mid_page: bool
    default_selected: bool


class LessonTopicSourcesRead(ApiModel):
    program_node_id: UUID
    ranges: list[LessonSourceRangeRead]


class LessonQuickWrite(ApiModel):
    program_node_id: UUID
    # Пусто — «Быстрый урок» по первому основному источнику; список — «Из источников».
    material_ids: list[UUID] | None = None


class LessonManualWrite(ApiModel):
    program_node_id: UUID


class LessonBulkItem(ApiModel):
    """Строка таблицы массовой подготовки; «пропустить» просто не присылается."""

    program_node_id: UUID
    action: Literal["quick", "manual"]


class LessonBulkWrite(ApiModel):
    items: list[LessonBulkItem] = Field(min_length=1, max_length=500)


class LessonProgressWrite(ApiModel):
    """Позиция чтения: блок урока или `null`, если читать начали сначала."""

    last_block_id: UUID | None = None


class LessonCompletionWrite(ApiModel):
    completed: bool = True


LessonBlockOperation = Literal[
    "add_note", "add_page", "add_outline", "add_fragments", "add_block", "add_link", "add_image",
    "add_region",
    "delete", "move_up", "move_down", "split", "merge",
    "set_topic", "add_topic", "remove_topic", "set_always_pages", "set_collapsed", "relink",
]


class LessonBlockWrite(ApiModel):
    """Структурное действие над уроком; поля нужны по операции (контракт — lessons.md)."""

    expected_revision: int = Field(ge=1)
    operation: LessonBlockOperation
    block_id: UUID | None = None
    after_block_id: UUID | None = None
    # Вставка перед блоком; задан — важнее `after_block_id`. Нужен для «добавить выше»
    # у самого первого блока: «после предыдущего» там выразить нечем.
    before_block_id: UUID | None = None
    material_id: UUID | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)
    variant: LessonNoteVariant = LessonNoteVariant.TEXT
    # add_fragments — края выделения; add_block и split — фрагмент блока или разреза.
    from_fragment_id: UUID | None = None
    to_fragment_id: UUID | None = None
    fragment_id: UUID | None = None
    split_after_page: int | None = Field(default=None, ge=1)
    insert_note: bool = False
    program_node_id: UUID | None = None
    always_pages: bool | None = None
    collapsed: bool | None = None
    media_url: str | None = Field(default=None, max_length=2000)
    caption: str | None = Field(default=None, max_length=2000)
    # add_region — доля страницы `[x0, y0, x1, y1]` в тех же координатах, что bbox фрагмента.
    region_bbox: list[float] | None = None

    @field_validator("region_bbox")
    @classmethod
    def _valid_region(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 4 or any(not 0.0 <= number <= 1.0 for number in value):
            raise ValueError("Область задаётся четырьмя долями страницы от 0 до 1")
        if value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("Область должна быть непустым прямоугольником")
        return value


class LessonUnbindWrite(ApiModel):
    binding_ids: list[UUID] = Field(min_length=1, max_length=5000)


class LessonConfirmWrite(ApiModel):
    expected_revision: int = Field(ge=1)


class LessonNoteWrite(ApiModel):
    expected_revision: int = Field(ge=1)
    body_md: str = Field(max_length=100_000)
    variant: LessonNoteVariant | None = None


class LessonUpdateWrite(ApiModel):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] | None = None
    status: LessonStatus | None = None
    expected_revision: int = Field(ge=1)


class LessonRefRead(ApiModel):
    id: UUID
    role: LessonRefRole
    material_id: UUID | None
    source_name: str
    source_role: SourceRole | None
    material_revision: int | None
    page_from: int
    page_to: int
    from_fragment_id: UUID | None
    to_fragment_id: UUID | None
    region_bbox: list[float] | None
    always_pages: bool
    is_available: bool
    is_parsed: bool
    low_quality_pages: list[int]
    # Граница не нашла пары в новой ревизии и стала границей страницы.
    boundary_shifted: bool
    # Режим «Страницы»: листы, которые рисует именно эта ссылка (без дублей по уроку).
    pages_shown: list[int]
    # У опоры пояснения модели: `[S3]` в тексте блока открывает эту ссылку.
    citation_label: str | None = None
    # Урок пришёл файлом без своего материала: текст куска из файла уроков.
    snapshot_md: str | None = None
    # Тот же файл материала теперь есть в проекте — ссылку можно связать заново.
    can_relink: bool = False


class LessonBlockRead(ApiModel):
    id: UUID
    sort_order: int
    kind: LessonBlockKind
    variant: LessonNoteVariant | None
    body_md: str | None
    origin: LessonBlockOrigin
    basis: LessonBasis | None
    bound_program_node_id: UUID | None
    media_kind: Literal["image", "link"] | None
    # Только у внешней ссылки; изображение отдаёт `GET …/media/{block_id}`.
    media_url: str | None
    # Кусок материала свёрнут под пояснением строкой «▸ В учебнике: …».
    collapsed: bool = False
    refs: list[LessonRefRead]
    # Блок `activity`: задание урока с формой, ключом и последней попыткой.
    task: StudyTaskRead | None = None


class LessonTopicRead(ApiModel):
    program_node_id: UUID
    title_snapshot: str
    current_title: str | None
    needs_review: bool


class LessonRead(ApiModel):
    id: UUID
    project_id: UUID
    title: str
    goal: str | None
    status: LessonStatus
    duration_minutes: int | None
    revision: int
    needs_review: bool
    # Прохождение: где остановились и когда урок отметили пройденным.
    last_block_id: UUID | None
    completed_at: datetime | None
    # Последнее действие журнала — создание именно этого урока: «Отменить» доступно.
    undo_sequence: int | None
    topics: list[LessonTopicRead]
    blocks: list[LessonBlockRead]
    build: LessonBuildRead | None = None
    created_at: datetime
    updated_at: datetime


class LessonUnbindOffer(ApiModel):
    """Удалённый или перенесённый кусок оставил привязки к теме — снять их молча нельзя."""

    program_node_id: UUID
    topic_title: str
    binding_ids: list[UUID]


class LessonBulkResult(ApiModel):
    """Результат массовой подготовки: созданные уроки и одна общая отмена."""

    lessons: list[LessonSummaryRead]
    latest_undoable_action: LatestUndoableAction | None


class LessonChangeResult(ApiModel):
    lesson: LessonRead
    latest_undoable_action: LatestUndoableAction | None
    unbind_offer: LessonUnbindOffer | None = None
