from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def default_context_flags() -> dict[str, bool]:
    """Начальные context flags новой сессии — AI-CHATS.md §21.4."""
    return {
        "profile": True,
        "reference": True,
        "fragments": True,
        "attempts": False,
        "section_memory": False,
    }


def enum_type(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [item.value for item in values],
    )


class TemplateKey(StrEnum):
    EXAM = "exam"
    TEXTBOOK = "textbook"
    FREE = "free"


class WorkspaceVariant(StrEnum):
    EXAM = "exam"
    TEXTBOOK = "textbook"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    COMPLETED = "completed"


class GoalPurpose(StrEnum):
    EXAM = "exam"
    WORK = "work"
    INTERVIEW = "interview"
    INTEREST = "interest"


class GoalScope(StrEnum):
    WHOLE = "whole"
    GOAL = "goal"


class StartingLevel(StrEnum):
    BEGINNER = "beginner"
    FAMILIAR = "familiar"
    REFRESHING = "refreshing"


class TargetOutcome(StrEnum):
    AWARENESS = "awareness"
    UNDERSTANDING = "understanding"
    APPLICATION = "application"
    MASTERY = "mastery"


class StudyFormat(StrEnum):
    THEORY = "theory"
    THEORY_AND_PRACTICE = "theory_and_practice"
    PRACTICE = "practice"


class ExamFormat(StrEnum):
    QUESTIONS = "questions"
    QUESTIONS_TASKS = "questions_tasks"
    TICKETS = "tickets"
    UNKNOWN = "unknown"


class SourceRole(StrEnum):
    MAIN = "main"
    ADDITIONAL = "additional"
    REFERENCE = "reference"


class NodeType(StrEnum):
    SECTION = "section"
    TOPIC = "topic"
    SUBPOINT = "subpoint"


class ExamKind(StrEnum):
    QUESTION = "question"
    TASK = "task"
    TICKET = "ticket"


class GoalRole(StrEnum):
    TARGET = "target"
    PREREQUISITE = "prerequisite"
    RELATED = "related"


class OriginKind(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    OUTLINE = "outline"
    PASS1 = "pass1"
    CATALOG = "catalog"
    MODEL = "model"


class ReferenceAnswerOrigin(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"


class ReferenceAnswerMatchMethod(StrEnum):
    MANUAL = "manual"
    EXACT_TITLE = "exact_title"
    # Заголовок разошёлся с формулировкой вопроса по написанию, но это тот же вопрос.
    FUZZY_TITLE = "fuzzy_title"
    # Пользователь сам указал вопрос для заголовка, который система не опознала.
    RESOLVED_TITLE = "resolved_title"
    # Номер раздела совпал с порядком вопросов; до проверки пользователем не подтверждаем.
    NUMBERED_ORDER = "numbered_order"


class MaterialState(StrEnum):
    READY_TO_PROCESS = "ready_to_process"
    QUEUED = "queued"
    PROCESSING = "processing"
    PAUSED = "paused"
    READY = "ready"
    FAILED = "failed"


class MaterialSourceKind(StrEnum):
    FILE = "file"
    TEXT = "text"
    URL = "url"
    YOUTUBE = "youtube"
    AUDIO = "audio"


class ParserMode(StrEnum):
    FAST = "fast"


class PageQuality(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    OCR_LOW = "ocr_low"


class RecognitionSource(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    VL = "vl"
    MANUAL = "manual"


class MaterialRevisionOrigin(StrEnum):
    """Откуда взялась ревизия материала. Наружу переводится человеческой фразой."""

    IMPORTED = "imported"
    PARSE = "parse"
    MANUAL_EDIT = "manual_edit"
    AI_CLEANUP = "ai_cleanup"
    SOURCE_REFRESH = "source_refresh"
    RESTORE = "restore"


class BackgroundJobKind(StrEnum):
    """Вид фоновой операции. Одна очередь и один воркер на все — модель разбора
    материала (Р3/Р4) поднята до общего реестра, а не заведена рядом с ним."""

    PARSE = "parse"
    AI_GROUPING = "ai_grouping"
    AI_IMPORT_REPAIR = "ai_import_repair"
    AI_PREPARATION = "ai_preparation"
    AI_CLEANUP = "ai_cleanup"
    LINK_ANSWERS = "link_answers"


class BackgroundJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class ProcessingStage(StrEnum):
    QUEUED = "queued"
    EXTRACT = "extract"
    SEGMENT = "segment"
    COMPLETE = "complete"


class BlockClass(StrEnum):
    CONTENT = "content"
    SERVICE = "service"


class ModuleKey(StrEnum):
    PLAN = "plan"
    LESSONS = "lessons"
    CARDS = "cards"
    REPETITIONS = "repetitions"
    ORAL_ANSWERS = "oral_answers"
    SQL = "sql"


class BindingStatus(StrEnum):
    MANUAL = "manual"
    CONFIRMED = "confirmed"
    MACHINE = "machine"
    REMOVED = "removed"
    ORPHANED = "orphaned"


class BindingMechanism(StrEnum):
    MANUAL = "manual"
    SEARCH = "search"
    # Разбор файла эталонных ответов по заголовкам: детерминированно, без модели.
    ANSWERS_FILE = "answers_file"
    PASS_TWO = "pass_two"


class ChatMessageRole(StrEnum):
    USER = "user"
    EXAMINER = "examiner"
    SYSTEM = "system"


class ChatStreamState(StrEnum):
    COMPLETE = "complete"
    STOPPED = "stopped"
    FAILED = "failed"


class ChatPayloadKind(StrEnum):
    NONE = "none"
    ANSWER_FORM = "answer_form"
    VERDICT = "verdict"
    TASK = "task"
    INTERACTIVE = "interactive"
    TOOL_RESULT = "tool_result"


class ChatMode(StrEnum):
    EXAM = "exam"
    # Зарегистрирован в capabilities, но сервис отвечает chat_mode_unavailable
    # до итерации 2 (AI-CHATS.md §21.4).
    STUDY = "study"


class ChatToolRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExaminerPersona(StrEnum):
    CALM_TEACHER = "calm_teacher"
    NEUTRAL_EXAMINER = "neutral_examiner"
    STRICT_REVIEWER = "strict_reviewer"


class ExaminerStrictness(StrEnum):
    SOFT = "soft"
    NORMAL = "normal"
    STRICT = "strict"


class AttemptOutcome(StrEnum):
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSCORED = "unscored"


class GradeMethod(StrEnum):
    EXACT_MATCH = "exact_match"
    KEY_TERMS = "key_terms"
    SQL = "sql"
    SEMANTIC = "semantic"
    AI_JUDGE = "ai_judge"
    SELF_ASSESSMENT = "self_assessment"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "color IS NULL OR color BETWEEN 1 AND 8",
            name=conv("ck_projects_ck_projects_color_range"),
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint(
            "program_revision >= 0",
            name=conv("ck_projects_ck_projects_program_revision_nonnegative"),
        ),
        Index("ix_projects_status_sort_order", "status", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    template_key: Mapped[TemplateKey] = mapped_column(enum_type(TemplateKey, "template_key"))
    workspace_variant: Mapped[WorkspaceVariant] = mapped_column(
        enum_type(WorkspaceVariant, "workspace_variant")
    )
    status: Mapped[ProjectStatus] = mapped_column(
        enum_type(ProjectStatus, "project_status"), default=ProjectStatus.DRAFT
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    color: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    program_revision: Mapped[int] = mapped_column(Integer, default=0)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    enabled_modules: Mapped[list[str]] = mapped_column(JSON, default=list)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class WizardDraft(Base):
    __tablename__ = "wizard_drafts"
    __table_args__ = (
        CheckConstraint("current_step BETWEEN 1 AND 5", name="current_step_range"),
        CheckConstraint("max_completed_step BETWEEN 1 AND 5", name="max_completed_step_range"),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        Index("ix_wizard_drafts_updated_at", "updated_at"),
    )

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    max_completed_step: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class GoalPassport(Base):
    __tablename__ = "goal_passports"
    __table_args__ = (
        CheckConstraint("minutes_per_day IS NULL OR minutes_per_day > 0", name="minutes_positive"),
        CheckConstraint(
            "days_per_week IS NULL OR days_per_week BETWEEN 1 AND 7", name="days_range"
        ),
        CheckConstraint("session_minutes IS NULL OR session_minutes > 0", name="session_positive"),
        CheckConstraint(
            "expected_item_count IS NULL OR expected_item_count > 0",
            name="expected_item_count_positive",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    purpose: Mapped[GoalPurpose | None] = mapped_column(
        enum_type(GoalPurpose, "goal_purpose"), nullable=True
    )
    scope: Mapped[GoalScope | None] = mapped_column(
        enum_type(GoalScope, "goal_scope"), nullable=True
    )
    starting_level: Mapped[StartingLevel | None] = mapped_column(
        enum_type(StartingLevel, "starting_level"), nullable=True
    )
    current_knowledge: Mapped[str | None] = mapped_column(String, nullable=True)
    target_outcome: Mapped[TargetOutcome | None] = mapped_column(
        enum_type(TargetOutcome, "target_outcome"), nullable=True
    )
    goal: Mapped[str | None] = mapped_column(String, nullable=True)
    success_criterion: Mapped[str | None] = mapped_column(String, nullable=True)
    important: Mapped[str | None] = mapped_column(String, nullable=True)
    excluded: Mapped[str | None] = mapped_column(String, nullable=True)
    study_format: Mapped[StudyFormat | None] = mapped_column(
        enum_type(StudyFormat, "study_format"), nullable=True
    )
    minutes_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exam_format: Mapped[ExamFormat | None] = mapped_column(
        enum_type(ExamFormat, "exam_format"), nullable=True
    )
    expected_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructor_requirements: Mapped[str | None] = mapped_column(String, nullable=True)
    exam_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    exam_procedure: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(
            "length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'",
            name="sha256_lowercase_hex",
        ),
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    original_name: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String, unique=True)
    media_type: Mapped[str] = mapped_column(String)
    source_kind: Mapped[MaterialSourceKind] = mapped_column(
        enum_type(MaterialSourceKind, "material_source_kind"), default=MaterialSourceKind.FILE
    )
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[MaterialState] = mapped_column(
        enum_type(MaterialState, "material_state"), default=MaterialState.READY_TO_PROCESS
    )
    active_parse_revision: Mapped[int] = mapped_column(Integer, default=0)
    parser_mode: Mapped[ParserMode | None] = mapped_column(
        enum_type(ParserMode, "parser_mode"), nullable=True
    )
    scan_page_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_low_page_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outline: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    diagnostics: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ProjectMaterial(Base):
    __tablename__ = "project_materials"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="priority_nonnegative"),
        Index("ix_project_materials_project_priority", "project_id", "priority"),
    )

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="RESTRICT"), primary_key=True
    )
    source_role: Mapped[SourceRole] = mapped_column(enum_type(SourceRole, "source_role"))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    affects_program: Mapped[bool] = mapped_column(Boolean, default=True)
    instruction: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    purposes: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["study_source"])
    exam_slot: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class MaterialPage(Base):
    __tablename__ = "material_pages"
    __table_args__ = (
        UniqueConstraint(
            "material_id",
            "revision",
            "page_number",
            name="uq_material_pages_revision_page",
        ),
        CheckConstraint(
            "revision > 0",
            name=conv("ck_material_pages_ck_material_pages_revision_positive"),
        ),
        CheckConstraint(
            "page_number > 0",
            name=conv("ck_material_pages_ck_material_pages_page_number_positive"),
        ),
        CheckConstraint(
            "width > 0 AND height > 0",
            name=conv("ck_material_pages_ck_material_pages_dimensions_positive"),
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=conv("ck_material_pages_ck_material_pages_confidence_range"),
        ),
        Index("ix_material_pages_material_revision_page", "material_id", "revision", "page_number"),
        # Покрывающие индексы для сводки Библиотеки. Строка страницы тяжёлая
        # (`elements`, `markdown`, `text` — 17 МБ на установку), и подсчёт качества
        # без них читал всю таблицу целиком через bind-mount.
        Index(
            "ix_material_pages_material_revision_quality",
            "material_id",
            "revision",
            "quality",
            "reviewed_at",
        ),
        Index("ix_material_pages_revision_lookup", "id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text, default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    quality: Mapped[PageQuality] = mapped_column(enum_type(PageQuality, "page_quality"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    elements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    diagnostics: Mapped[list[str]] = mapped_column(JSON, default=list)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class MaterialBlock(Base):
    __tablename__ = "material_blocks"
    __table_args__ = (
        UniqueConstraint(
            "material_id",
            "revision",
            "sort_order",
            name="uq_material_blocks_revision_order",
        ),
        CheckConstraint(
            "revision > 0",
            name=conv("ck_material_blocks_ck_material_blocks_revision_positive"),
        ),
        CheckConstraint(
            "sort_order >= 0",
            name=conv("ck_material_blocks_ck_material_blocks_sort_order_nonnegative"),
        ),
        CheckConstraint(
            "page_from > 0 AND page_to >= page_from",
            name=conv("ck_material_blocks_ck_material_blocks_page_range_valid"),
        ),
        Index(
            "ix_material_blocks_material_revision_order", "material_id", "revision", "sort_order"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    block_class: Mapped[BlockClass] = mapped_column(enum_type(BlockClass, "block_class"))
    service_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    page_from: Mapped[int] = mapped_column(Integer)
    page_to: Mapped[int] = mapped_column(Integer)


class MaterialFragment(Base):
    __tablename__ = "material_fragments"
    __table_args__ = (
        UniqueConstraint(
            "page_id", "sort_order", name="uq_material_fragments_page_order"
        ),
        CheckConstraint(
            "sort_order >= 0",
            name=conv("ck_material_fragments_ck_material_fragments_sort_order_nonnegative"),
        ),
        CheckConstraint(
            "structure_level IS NULL OR structure_level >= 0",
            name=conv("ck_material_fragments_ck_material_fragments_level_nonnegative"),
        ),
        CheckConstraint("time_from IS NULL OR time_from >= 0", name="time_from_nonnegative"),
        CheckConstraint("time_to IS NULL OR time_to >= 0", name="time_to_nonnegative"),
        CheckConstraint(
            "time_to IS NULL OR time_from IS NULL OR time_to >= time_from",
            name="time_range_valid",
        ),
        Index("ix_material_fragments_page_order", "page_id", "sort_order"),
        Index("ix_material_fragments_block", "block_id"),
        # Без него удаление материала и агрегаты Библиотеки сканируют всю таблицу.
        Index("ix_material_fragments_material", "material_id"),
        # Покрывающий для подсчёта фрагментов: `page_id` берётся из индекса,
        # тяжёлая строка фрагмента не читается вовсе.
        Index("ix_material_fragments_material_page", "material_id", "page_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    page_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_pages.id", ondelete="CASCADE")
    )
    block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_blocks.id", ondelete="CASCADE")
    )
    sort_order: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    bbox: Mapped[list[float]] = mapped_column(JSON)
    element_kind: Mapped[str] = mapped_column(String)
    structure_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    degraded_structure: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[PageQuality] = mapped_column(enum_type(PageQuality, "fragment_quality"))
    recognition_source: Mapped[RecognitionSource] = mapped_column(
        enum_type(RecognitionSource, "fragment_recognition_source"),
        default=RecognitionSource.NATIVE,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Исходный вырез доступен у изображений, формул и таблиц.
    asset_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # Границы сегмента у временных источников: расшифровка аудио и субтитры.
    time_from: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_to: Mapped[float | None] = mapped_column(Float, nullable=True)


class MaterialRevision(Base):
    """Реестр версий разбора общего материала.

    Активная версия хранится в `Material.active_parse_revision`; здесь лежит
    история: чем версия была получена, из какой выросла и что дала. Страницы и
    фрагменты зарегистрированных версий не удаляются при новой обработке —
    только вместе с самим материалом.
    """

    __tablename__ = "material_revisions"
    __table_args__ = (
        UniqueConstraint("material_id", "revision", name="uq_material_revision"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint(
            "parent_revision IS NULL OR parent_revision > 0", name="parent_revision_positive"
        ),
        Index("ix_material_revisions_material_revision", "material_id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    origin: Mapped[MaterialRevisionOrigin] = mapped_column(
        enum_type(MaterialRevisionOrigin, "material_revision_origin")
    )
    parser_mode: Mapped[ParserMode | None] = mapped_column(
        enum_type(ParserMode, "revision_parser_mode"), nullable=True
    )
    parent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class BackgroundJob(Base):
    """Единая очередь фоновых операций: разбор материала и вызовы ИИ вместе.

    Одна ось состояний живёт здесь (`state`) — независимо от исхода конкретного
    вызова модели, который остаётся в `AiRun.status` (там же `succeeded` и
    `cached`, это бухгалтерский факт вызова, а не стадия жизненного цикла
    задачи). `material_id`, `parser_mode` и `stage` осмысленны только у
    `PARSE`: у ролей ИИ и у `LINK_ANSWERS` они пустые.
    """

    __tablename__ = "background_jobs"
    __table_args__ = (
        # Имя намеренно оставлено старым (таблица была processing_tasks):
        # SQLite ненадёжно отражает имена CHECK-ограничений при пересборке
        # таблицы в batch-режиме Alembic — попытка переименовать её при
        # переносе на background_jobs ломает миграцию (см. 20260901_0031).
        CheckConstraint(
            "done >= 0 AND total >= 0 AND done <= total",
            name=conv("ck_processing_tasks_ck_processing_tasks_progress_valid"),
        ),
        Index("ix_background_jobs_state_created", "state", "created_at"),
        Index("ix_background_jobs_material_created", "material_id", "created_at"),
        Index("ix_background_jobs_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # Материал — только у разбора (PARSE). У ролей ИИ и у LINK_ANSWERS задача
    # привязана к проекту (или ни к чему — глобальные операции Библиотеки).
    material_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[BackgroundJobKind] = mapped_column(
        enum_type(BackgroundJobKind, "background_job_kind"), default=BackgroundJobKind.PARSE
    )
    state: Mapped[BackgroundJobState] = mapped_column(
        enum_type(BackgroundJobState, "background_job_state"),
        default=BackgroundJobState.QUEUED,
    )
    stage: Mapped[ProcessingStage | None] = mapped_column(
        enum_type(ProcessingStage, "processing_stage"), nullable=True
    )
    parser_mode: Mapped[ParserMode | None] = mapped_column(
        enum_type(ParserMode, "task_parser_mode"), nullable=True
    )
    done: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProgramNode(Base):
    __tablename__ = "program_nodes"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        Index(
            "ix_program_nodes_project_parent_order",
            "project_id",
            "parent_id",
            "sort_order",
        ),
        Index("ix_program_nodes_origin_material_id", "origin_material_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    node_type: Mapped[NodeType] = mapped_column(enum_type(NodeType, "node_type"))
    exam_kind: Mapped[ExamKind | None] = mapped_column(
        enum_type(ExamKind, "exam_kind"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String)
    section_purpose: Mapped[str | None] = mapped_column(String, nullable=True)
    goal_role: Mapped[GoalRole | None] = mapped_column(
        enum_type(GoalRole, "goal_role"), nullable=True
    )
    target_level: Mapped[TargetOutcome | None] = mapped_column(
        enum_type(TargetOutcome, "node_target_level"), nullable=True
    )
    is_in_current_program: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_material: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    origin_kind: Mapped[OriginKind] = mapped_column(
        enum_type(OriginKind, "origin_kind"), default=OriginKind.MANUAL
    )
    origin_note: Mapped[str | None] = mapped_column(String, nullable=True)
    origin_material_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ReferenceAnswer(Base):
    __tablename__ = "reference_answers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "revision >= 0",
            name=conv("ck_reference_answers_ck_reference_answers_revision_nonnegative"),
        ),
        Index("ix_reference_answers_project_active", "project_id", "is_active"),
        # Под каскад ON DELETE SET NULL при удалении материала-источника.
        Index("ix_reference_answers_source_material", "source_material_id"),
    )

    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    origin_kind: Mapped[ReferenceAnswerOrigin] = mapped_column(
        enum_type(ReferenceAnswerOrigin, "reference_answer_origin")
    )
    match_method: Mapped[ReferenceAnswerMatchMethod] = mapped_column(
        enum_type(ReferenceAnswerMatchMethod, "reference_answer_match_method")
    )
    matched_title: Mapped[str | None] = mapped_column(String, nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    source_label: Mapped[str | None] = mapped_column(String, nullable=True)
    source_material_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), nullable=True
    )
    source_page_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ReferenceAnswerAttachment(Base):
    """Файл, прикреплённый к эталонному ответу вручную.

    Картинки, приехавшие из материала, отдельно не копируются: они уже лежат
    фрагментами и показываются через привязки. Здесь только то, что пользователь
    принёс сам — фотография доски, схема, скан.
    """

    __tablename__ = "reference_answer_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "size_bytes >= 0",
            name=conv(
                "ck_reference_answer_attachments_ck_reference_answer_attachments_size_nonnegative"
            ),
        ),
        Index("ix_answer_attachments_node", "project_id", "program_node_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    file_name: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Binding(Base):
    __tablename__ = "bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "project_id",
            "program_node_id",
            "fragment_id",
            name="uq_bindings_node_fragment",
        ),
        Index("ix_bindings_project_node", "project_id", "program_node_id"),
        Index("ix_bindings_project_fragment", "project_id", "fragment_id"),
        Index("ix_bindings_material", "material_id"),
        # Отдельные индексы под каскады ON DELETE: `ix_bindings_project_fragment`
        # для них бесполезен, ведущая колонка не та. Без них SQLite сканирует всю
        # таблицу привязок на КАЖДЫЙ удаляемый фрагмент и КАЖДЫЙ блок.
        Index("ix_bindings_fragment", "fragment_id"),
        Index("ix_bindings_block", "block_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    fragment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_fragments.id", ondelete="CASCADE")
    )
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    block_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_blocks.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[BindingStatus] = mapped_column(enum_type(BindingStatus, "binding_status"))
    mechanism: Mapped[BindingMechanism] = mapped_column(
        enum_type(BindingMechanism, "binding_mechanism")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class WorkspaceState(Base):
    __tablename__ = "workspace_states"
    __table_args__ = (CheckConstraint("schema_version >= 1", name="schema_version_positive"),)

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ProjectActionLog(Base):
    __tablename__ = "project_action_log"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('draft', 'active')",
            name=conv("ck_project_action_log_ck_project_action_log_phase_value"),
        ),
        CheckConstraint(
            "payload_version >= 1",
            name=conv(
                "ck_project_action_log_ck_project_action_log_payload_version_positive"
            ),
        ),
        Index(
            "ix_project_action_log_project_phase_undone_sequence",
            "project_id",
            "phase",
            "undone_at",
            "sequence",
        ),
        {"sqlite_autoincrement": True},
    )

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    action_type: Mapped[str] = mapped_column(String)
    phase: Mapped[str] = mapped_column(String)
    payload_version: Mapped[int] = mapped_column(Integer, default=1)
    target_title: Mapped[str] = mapped_column(String)
    inverse_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AiProviderConnection(Base):
    __tablename__ = "ai_provider_connections"
    __table_args__ = (
        CheckConstraint(
            "catalog_profile IN ('openrouter', 'openai_compatible')",
            name="catalog_profile",
        ),
        UniqueConstraint("label", name="uq_ai_provider_connections_label"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    label: Mapped[str] = mapped_column(String)
    catalog_profile: Mapped[str] = mapped_column(String, default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String)
    api_key_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_catalog_refresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class AiSettings(Base):
    __tablename__ = "ai_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("confirm_input_tokens >= 0", name="confirm_tokens_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    external_models_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    operation_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    confirm_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    confirm_input_tokens: Mapped[int] = mapped_column(Integer, default=20_000)
    usd_rub_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    usd_rub_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    default_text_provider_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="RESTRICT"),
        nullable=True,
    )
    default_text_model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    default_speech_provider_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="RESTRICT"),
        nullable=True,
    )
    default_speech_model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class AiRoleSetting(Base):
    __tablename__ = "ai_role_settings"

    role: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_override_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="RESTRICT"),
        nullable=True,
    )
    model_override: Mapped[str | None] = mapped_column(String, nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class AiModelCatalogEntry(Base):
    __tablename__ = "ai_model_catalog"
    __table_args__ = (
        Index("ix_ai_model_catalog_provider_available", "provider_id", "is_available"),
    )

    provider_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supported_parameters: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_modalities: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_modalities: Mapped[list[str]] = mapped_column(JSON, default=list)
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prompt_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    completion_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    knowledge_cutoff: Mapped[str | None] = mapped_column(String, nullable=True)
    expiration_date: Mapped[str | None] = mapped_column(String, nullable=True)
    pricing_snapshot_at: Mapped[datetime] = mapped_column(DateTime)
    catalog_snapshot_at: Mapped[datetime] = mapped_column(DateTime)
    is_manually_added: Mapped[bool] = mapped_column(Boolean, default=False)
    favorite_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)


class AiRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'cached')",
            name="status",
        ),
        Index("ix_ai_runs_created_role", "created_at", "role"),
        Index("ix_ai_runs_project_created", "project_id", "created_at"),
        Index("ix_ai_runs_request_hash", "request_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    # Заполняется только у вызовов, запущенных из очереди фоновых операций —
    # прямой вызов гейтвея (например, экзаменационный чат) его не проставляет.
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("background_jobs.id", ondelete="SET NULL"), nullable=True
    )
    provider_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_label_snapshot: Mapped[str] = mapped_column(String, default="Неизвестный провайдер")
    role: Mapped[str] = mapped_column(String)
    modality: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    requested_model_id: Mapped[str] = mapped_column(String)
    actual_model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    context_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    estimated_input_tokens: Mapped[int] = mapped_column(Integer)
    estimated_output_tokens: Mapped[int] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    usd_rub_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    usd_rub_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    pricing_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Валидированный ответ нужен не только кэшу: пользователь может закрыть
    # диалог, пока модель работает, и позже вернуться к предложению.
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cached_from_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AiCacheEntry(Base):
    __tablename__ = "ai_cache_entries"
    __table_args__ = (Index("ix_ai_cache_project_role", "project_id", "role"),)

    request_hash: Mapped[str] = mapped_column(String, primary_key=True)
    source_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE")
    )
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[str] = mapped_column(String)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("ordinal >= 1", name="ordinal_positive"),
        Index("ix_attempts_node_created", "project_id", "program_node_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    parent_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    answer_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    active_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    persona: Mapped[ExaminerPersona] = mapped_column(
        enum_type(ExaminerPersona, "examiner_persona")
    )
    strictness: Mapped[ExaminerStrictness] = mapped_column(
        enum_type(ExaminerStrictness, "examiner_strictness")
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Grade(Base):
    """Итог системы. Решение пользователя хранится рядом и не переписывает его."""

    __tablename__ = "grades"
    __table_args__ = (
        CheckConstraint(
            "self_assessment IS NULL OR self_assessment <> 'unscored'",
            name="self_assessment_scored",
        ),
    )

    attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True
    )
    outcome: Mapped[AttemptOutcome] = mapped_column(
        enum_type(AttemptOutcome, "attempt_outcome")
    )
    method: Mapped[GradeMethod | None] = mapped_column(
        enum_type(GradeMethod, "grade_method"), nullable=True
    )
    credited_points: Mapped[list[Any]] = mapped_column(JSON, default=list)
    missed_points: Mapped[list[Any]] = mapped_column(JSON, default=list)
    wrong_points: Mapped[list[Any]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    self_assessment: Mapped[AttemptOutcome | None] = mapped_column(
        enum_type(AttemptOutcome, "attempt_outcome"), nullable=True
    )
    ai_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ChatSession(Base):
    """Один чат по одному вопросу. Новый чат не стирает старые."""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        Index("ix_chat_sessions_node_updated", "project_id", "program_node_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    # Ближайший предок-раздел на момент создания; NULL — плоский список.
    # Показывается и используется памятью раздела только с итерации 2.
    section_scope_node_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String)
    mode: Mapped[ChatMode] = mapped_column(
        enum_type(ChatMode, "chat_mode"), default=ChatMode.EXAM
    )
    persona: Mapped[ExaminerPersona] = mapped_column(
        enum_type(ExaminerPersona, "examiner_persona"),
        default=ExaminerPersona.NEUTRAL_EXAMINER,
    )
    strictness: Mapped[ExaminerStrictness] = mapped_column(
        enum_type(ExaminerStrictness, "examiner_strictness"),
        default=ExaminerStrictness.NORMAL,
    )
    # {"provider_id": "...", "model_id": "..."} | None — JSON-снимок, а не FK:
    # запись остаётся читаемой, если подключение провайдера позже удалено.
    model_override: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    context_flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=default_context_flags)
    draft_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ChatMessage(Base):
    """Реплика или типизированный блок. Оценка здесь не хранится — только ссылка."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "sequence", name="uq_chat_messages_session_id_sequence"
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[ChatMessageRole] = mapped_column(enum_type(ChatMessageRole, "chat_message_role"))
    text: Mapped[str] = mapped_column(Text, default="")
    stream_state: Mapped[ChatStreamState] = mapped_column(
        enum_type(ChatStreamState, "chat_stream_state"), default=ChatStreamState.COMPLETE
    )
    payload_kind: Mapped[ChatPayloadKind] = mapped_column(
        enum_type(ChatPayloadKind, "chat_payload_kind"), default=ChatPayloadKind.NONE
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Какая серверная операция создала сообщение: null — обычная реплика,
    # иначе ключ навыка или Tool (AI-CHATS.md §13).
    skill: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True
    )
    attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True
    )
    grade_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("grades.attempt_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ChatToolRun(Base):
    """Журнал выполнения Tool: вход, состояние и компактный результат.

    Состояния queued/running уже предусмотрены для будущего фонового
    исполнения (AI-CHATS.md §17.4); первая итерация выполняет Tool синхронно
    и сразу сохраняет succeeded/failed.
    """

    __tablename__ = "chat_tool_runs"
    __table_args__ = (Index("ix_chat_tool_runs_session_created", "session_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    tool_key: Mapped[str] = mapped_column(String)
    state: Mapped[ChatToolRunState] = mapped_column(
        enum_type(ChatToolRunState, "chat_tool_run_state"), default=ChatToolRunState.QUEUED
    )
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    # Типизированный блок, созданный этим запуском — null, пока не сохранён.
    message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OcrSettings(Base):
    """Глобальные настройки распознавания. Одна строка, как AiSettings."""

    __tablename__ = "ocr_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            "quality_threshold >= 0 AND quality_threshold <= 1", name="threshold_range"
        ),
        CheckConstraint("raster_scale IN (1.5, 2.0, 3.0)", name="raster_scale_known"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_mode: Mapped[ParserMode] = mapped_column(
        enum_type(ParserMode, "ocr_default_mode"), default=ParserMode.FAST
    )
    quality_threshold: Mapped[float] = mapped_column(Float, default=0.75)
    raster_scale: Mapped[float] = mapped_column(Float, default=2.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class OcrEngineConfig(Base):
    """Настройки одного движка распознавания из реестра `app.ocr.engines`.

    `mode` — строка, а не FK на перечисление: реестр шире, чем `ParserMode`
    (включает пока не реализованные `cloud`/`maximum`/`expert`), и новый движок
    не должен требовать миграции. `extra` несёт поля, специфичные для движка
    (например, адрес и таймаут GPU-сервиса «Учебника»).
    """

    __tablename__ = "ocr_engine_configs"

    mode: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    device: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    executor: Mapped[str | None] = mapped_column(String, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class Conspect(Base):
    """Личный конспект темы — одна строка на пару (проект, узел программы)."""

    __tablename__ = "conspects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "revision >= 1", name=conv("ck_conspects_ck_conspects_revision_positive")
        ),
        Index("ix_conspects_project", "project_id"),
    )

    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ConspectImage(Base):
    """Изображение конспекта. Живёт, пока на него ссылается сохранённый Markdown узла."""

    __tablename__ = "conspect_images"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "size_bytes >= 0",
            name=conv("ck_conspect_images_ck_conspect_images_size_nonnegative"),
        ),
        Index("ix_conspect_images_project_node", "project_id", "program_node_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    file_name: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


# Регистрация таблиц подсистемы для create_all и Alembic.
from app.preparation import models as preparation_models  # noqa: E402,F401
