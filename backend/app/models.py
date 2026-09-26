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
    column,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import conv

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def default_material_display_name(context: Any) -> str:
    """Начальное пользовательское имя совпадает с техническим исходным."""
    return str(context.get_current_parameters()["original_name"])


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


class ProgramBasisKind(StrEnum):
    OUTLINE = "outline"
    CUSTOM = "custom"


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
    # Границу раздела указала модель по скелету документа (срез F), пользователь подтвердил план.
    AI_SECTION = "ai_section"


class MaterialState(StrEnum):
    READY_TO_PROCESS = "ready_to_process"
    QUEUED = "queued"
    PROCESSING = "processing"
    PAUSED = "paused"
    NEEDS_INPUT = "needs_input"
    READY = "ready"
    FAILED = "failed"


class MaterialSourceKind(StrEnum):
    FILE = "file"
    TEXT = "text"
    URL = "url"
    YOUTUBE = "youtube"
    AUDIO = "audio"
    TYPST = "typst"


class ParserMode(StrEnum):
    FAST = "fast"
    CLOUD = "cloud"


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
    """Вид фоновой операции в общем реестре с независимыми ресурсными полосами.

    Модель разбора материала (Р3/Р4) поднята до общего реестра, а не заведена
    рядом с ним.
    """

    PARSE = "parse"
    TYPST_COMPILE = "typst_compile"
    AI_GROUPING = "ai_grouping"
    AI_IMPORT_REPAIR = "ai_import_repair"
    AI_PREPARATION = "ai_preparation"
    AI_CLEANUP = "ai_cleanup"
    LINK_ANSWERS = "link_answers"
    AI_ANSWER_SECTIONS = "ai_answer_sections"
    AI_PROGRAM_BUILD = "ai_program_build"
    COVERAGE_RESEARCH = "coverage_research"
    RETRIEVAL_INDEX = "retrieval_index"
    RETRIEVAL_MODEL_INSTALL = "retrieval_model_install"
    RETRIEVAL_EXHAUSTIVE = "retrieval_exhaustive"
    BACKUP_CREATE = "backup_create"
    PROJECT_EXPORT = "project_export"
    PROJECT_IMPORT = "project_import"
    STORAGE_VERIFY = "storage_verify"
    STORAGE_CLEANUP = "storage_cleanup"


class BackgroundJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class BackupKind(StrEnum):
    """Почему создан переносимый снимок установки."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"
    PRE_RESTORE = "pre_restore"


class BackupArchiveState(StrEnum):
    """Жизненный цикл файла копии, независимый от строки общей очереди."""

    QUEUED = "queued"
    CREATING = "creating"
    READY = "ready"
    FAILED = "failed"


class TransferKind(StrEnum):
    BACKUP = "backup"
    PROJECT = "project"


class TransferProfile(StrEnum):
    PERSONAL = "personal"
    SHARE = "share"


class ProcessingStage(StrEnum):
    QUEUED = "queued"
    EXTRACT = "extract"
    SEGMENT = "segment"
    COMPLETE = "complete"


class BlockClass(StrEnum):
    CONTENT = "content"
    SERVICE = "service"


class EmbeddingBackendKind(StrEnum):
    """Источник embeddings с одинаковым контрактом для индекса и запроса."""

    LOCAL_HF = "local_hf"
    OPENAI_COMPATIBLE = "openai_compatible"


class RetrievalIndexState(StrEnum):
    BUILDING = "building"
    READY = "ready"
    ACTIVE = "active"
    FAILED = "failed"


class RetrievalPreset(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    ACCURATE = "accurate"


class RetrievalChunkKind(StrEnum):
    TEXT = "text"
    TYPST_SOURCE = "typst_source"


class ModuleKey(StrEnum):
    """Разделы проекта, которые можно включить и выключить.

    Значение ``sql`` снято 17.09.2026 вместе с задачами на SQL (REQUIREMENTS.md §10).
    Колонка ``Project.enabled_modules`` — JSON без CHECK, старых данных с ``sql`` нет,
    поэтому миграция не нужна.
    """

    PLAN = "plan"
    LESSONS = "lessons"
    CARDS = "cards"
    REPETITIONS = "repetitions"
    ORAL_ANSWERS = "oral_answers"


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
    # Урок: выбор пользователя (`lesson`) и диапазон оглавления быстрого урока (`outline`).
    LESSON = "lesson"
    OUTLINE = "outline"


class LessonStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class LessonBlockKind(StrEnum):
    SOURCE = "source"
    NOTE = "note"
    MEDIA = "media"
    ACTIVITY = "activity"


class LessonNoteVariant(StrEnum):
    TEXT = "text"
    HEADING = "heading"
    EXPLANATION = "explanation"
    IMPORTANT = "important"
    EXAMPLE = "example"
    DEFINITION = "definition"
    WARNING = "warning"


class LessonBlockOrigin(StrEnum):
    MANUAL = "manual"
    OUTLINE = "outline"
    MODEL = "model"
    MIXED = "mixed"


class LessonBasis(StrEnum):
    SOURCES = "sources"
    SOURCES_AND_MODEL = "sources_and_model"
    MODEL_ONLY = "model_only"


class LessonRefRole(StrEnum):
    CONTENT = "content"
    SUPPORT = "support"


class ChatMessageRole(StrEnum):
    USER = "user"
    EXAMINER = "examiner"
    SYSTEM = "system"
    # Реплика модели в чате построения программы учебника — семантически
    # ответ ассистента, а не экзаменатора (AGENTS.md, TEXTBOOK_MODE.md §3).
    ASSISTANT = "assistant"


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
    # Предложение изменений дерева программы учебника — операции с чекбоксами,
    # применяются отдельным вызовом apply/reject (docs/architecture/textbook-program.md).
    PROGRAM_DIFF = "program_diff"


class ChatMode(StrEnum):
    EXAM = "exam"
    # Учебниковый и свободный RAG-чат по теме или проекту (docs/architecture/retrieval.md).
    STUDY = "study"
    # Чат построения программы учебника — TEXTBOOK_MODE.md §3, режим «С ИИ».
    # Сессия проектная (program_node_id может быть NULL), а не по одному вопросу.
    PROGRAM = "program"
    # Чат «Поиск в интернете» в Материалах — тоже проектная сессия без темы
    # (docs/architecture/source-search-chat.md).
    SOURCE_SEARCH = "source_search"


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


class ActivityKind(StrEnum):
    """Способ проверки знания; календарь не зависит от этого перечисления."""

    FREE_ANSWER = "free_answer"
    CARD = "card"


class ActivityOrigin(StrEnum):
    MANUAL = "manual"
    FRAGMENT = "fragment"
    EXAM_CHAT = "exam_chat"


class CardState(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class CardSourceKind(StrEnum):
    NONE = "none"
    FRAGMENT = "fragment"
    REFERENCE = "reference"


class CardSessionState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CardSessionPace(StrEnum):
    CALM = "calm"
    FAST = "fast"


class CardSessionScope(StrEnum):
    TODAY = "today"
    HARD = "hard"
    SELECTED = "selected"
    ALL = "all"


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
    coverage_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    tree_detail: Mapped[str | None] = mapped_column(String, nullable=True)
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
    display_name: Mapped[str] = mapped_column(String, default=default_material_display_name)
    subject: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
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
    # NULL у страниц текстового слоя (`quality=native`) — распознавание им не
    # требовалось. У скопированной без переразбора страницы (частичный запуск)
    # переносится значение источника, а не режим текущей задачи: иначе версия
    # приписывала бы соседним нетронутым страницам чужую модель.
    parser_mode: Mapped[ParserMode | None] = mapped_column(
        enum_type(ParserMode, "material_page_parser_mode"), nullable=True
    )
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
        UniqueConstraint("page_id", "sort_order", name="uq_material_fragments_page_order"),
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
        # Частичный: Библиотека спрашивает только «есть ли у материала заголовки».
        # Заголовков пятая часть фрагментов, поэтому полный индекс тут лишний.
        Index(
            "ix_material_fragments_headings",
            "material_id",
            "page_id",
            sqlite_where=column("structure_level").is_not(None),
        ),
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
    render_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TypstMaterial(Base):
    """Метаданные Typst-проекта, отделённые от общего материала.

    В `Material` остаются общие поля Библиотеки, а здесь — только сведения,
    нужные для воспроизводимой сборки и интерфейса разрешения зависимостей.
    """

    __tablename__ = "typst_materials"

    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), primary_key=True
    )
    input_kind: Mapped[str] = mapped_column(String(16))
    entrypoint: Mapped[str | None] = mapped_column(String, nullable=True)
    compiler_version: Mapped[str | None] = mapped_column(String, nullable=True)
    build_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    packages: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    current_pdf_path: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class TypstSourceChunk(Base):
    """Неизменённый отрезок исходника Typst, передаваемый модели вместо PDF-текста."""

    __tablename__ = "typst_source_chunks"
    __table_args__ = (
        CheckConstraint("line_from > 0 AND line_to >= line_from", name="typst_chunk_line_range"),
        Index("ix_typst_source_chunks_material_revision", "material_id", "revision", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String)
    line_from: Mapped[int] = mapped_column(Integer)
    line_to: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64))
    page_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnostic: Mapped[str | None] = mapped_column(String, nullable=True)


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
    # Когда пользователь разобрал готовое предложение (принял или убрал). Пусто
    # у задач, которые применяются сами, и у тех, чей результат ещё ждёт
    # проверки — см. `background.registry.REVIEW_REQUIRED_KINDS`.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StorageSettings(Base):
    """Глобальная политика копий; строка с id=1 создаётся лениво."""

    __tablename__ = "storage_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("retention_days BETWEEN 1 AND 365", name="retention_days_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    automatic_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_time: Mapped[str] = mapped_column(String(5), default="03:00")
    retention_days: Mapped[int] = mapped_column(Integer, default=7)
    backup_directory: Mapped[str | None] = mapped_column(String, nullable=True)
    last_automatic_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class BackupArchive(Base):
    """Управляемый `.tentex-backup`; старые ручные sqlite-файлы сюда не входят."""

    __tablename__ = "backup_archives"
    __table_args__ = (Index("ix_backup_archives_created", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[BackupKind] = mapped_column(enum_type(BackupKind, "backup_kind"))
    state: Mapped[BackupArchiveState] = mapped_column(
        enum_type(BackupArchiveState, "backup_archive_state"),
        default=BackupArchiveState.QUEUED,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("background_jobs.id", ondelete="SET NULL"), nullable=True
    )
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TransferArtifact(Base):
    """Загруженный или подготовленный пакет до скачивания/подтверждения импорта."""

    __tablename__ = "transfer_artifacts"
    __table_args__ = (Index("ix_transfer_artifacts_expires", "expires_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[TransferKind] = mapped_column(enum_type(TransferKind, "transfer_kind"))
    profile: Mapped[TransferProfile | None] = mapped_column(
        enum_type(TransferProfile, "transfer_profile"), nullable=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    package_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, index=True)
    file_path: Mapped[str] = mapped_column(String)
    file_name: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("background_jobs.id", ondelete="SET NULL"), nullable=True
    )
    imported_project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class EmbeddingProfile(Base):
    """Воспроизводимая конфигурация модели, независимо от места её запуска."""

    __tablename__ = "embedding_profiles"
    __table_args__ = (
        CheckConstraint("dimension IS NULL OR dimension > 0", name="dimension_positive"),
        CheckConstraint("batch_size > 0", name="batch_size_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    label: Mapped[str] = mapped_column(String, unique=True)
    backend_kind: Mapped[EmbeddingBackendKind] = mapped_column(
        enum_type(EmbeddingBackendKind, "embedding_backend_kind")
    )
    model_id: Mapped[str] = mapped_column(String)
    model_revision: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="RESTRICT"),
        nullable=True,
    )
    dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=32)
    normalize: Mapped[bool] = mapped_column(Boolean, default=True)
    pooling: Mapped[str] = mapped_column(String(16), default="mean")
    query_template: Mapped[str] = mapped_column(Text, default="{text}")
    document_template: Mapped[str] = mapped_column(Text, default="{text}")
    installed: Mapped[bool] = mapped_column(Boolean, default=False)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    test_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class RetrievalIndex(Base):
    """Неизменяемый снимок корпуса; READY становится ACTIVE только вручную."""

    __tablename__ = "retrieval_indexes"
    __table_args__ = (
        CheckConstraint("chunk_target_tokens > 0", name="chunk_target_positive"),
        CheckConstraint("chunk_max_tokens >= chunk_target_tokens", name="chunk_max_valid"),
        CheckConstraint("chunk_overlap_tokens >= 0", name="chunk_overlap_nonnegative"),
        CheckConstraint("chunk_count >= 0", name="chunk_count_nonnegative"),
        CheckConstraint("indexed_material_count >= 0", name="indexed_material_count_nonnegative"),
        Index("ix_retrieval_indexes_state_created", "state", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("embedding_profiles.id", ondelete="RESTRICT")
    )
    state: Mapped[RetrievalIndexState] = mapped_column(
        enum_type(RetrievalIndexState, "retrieval_index_state"),
        default=RetrievalIndexState.BUILDING,
    )
    preset: Mapped[RetrievalPreset] = mapped_column(
        enum_type(RetrievalPreset, "retrieval_preset"), default=RetrievalPreset.BALANCED
    )
    # Те же значения, что `retrieval.chunking.DEFAULT_*`: импорт оттуда был бы циклом.
    chunk_target_tokens: Mapped[int] = mapped_column(Integer, default=280)
    chunk_max_tokens: Mapped[int] = mapped_column(Integer, default=360)
    chunk_overlap_tokens: Mapped[int] = mapped_column(Integer, default=48)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    # `done` живёт у фоновой задачи и исчезает из экрана после завершения.
    # Индексу нужен собственный счётчик, чтобы честно показать сохранённый
    # частичный корпус и после перезагрузки.
    indexed_material_count: Mapped[int] = mapped_column(Integer, default=0)
    material_count: Mapped[int] = mapped_column(Integer, default=0)
    corpus_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    diagnostics: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RetrievalSettings(Base):
    """Единственная строка настроек общего retrieval-контура установки."""

    __tablename__ = "retrieval_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_index_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("retrieval_indexes.id", ondelete="SET NULL"), nullable=True
    )
    default_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("embedding_profiles.id", ondelete="SET NULL"), nullable=True
    )
    preset: Mapped[RetrievalPreset] = mapped_column(
        enum_type(RetrievalPreset, "retrieval_settings_preset"),
        default=RetrievalPreset.BALANCED,
    )
    expert_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class RetrievalChunk(Base):
    """Структурный кусок с точным обратным переходом к исходному материалу."""

    __tablename__ = "retrieval_chunks"
    __table_args__ = (
        UniqueConstraint("index_id", "sort_order", name="uq_retrieval_chunks_index_order"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint("token_count > 0", name="token_count_positive"),
        CheckConstraint(
            "page_from IS NULL OR (page_from > 0 AND page_to >= page_from)",
            name="page_range_valid",
        ),
        Index("ix_retrieval_chunks_index_material", "index_id", "material_id"),
        Index("ix_retrieval_chunks_index_block", "index_id", "block_id"),
        # Покрывающий индекс для перевода фрагментов BM25 в куски: без него
        # json_each(fragment_ids) читал строку целиком вместе с длинным text и
        # вектором, и на bind mount с Windows это стоило 5–10 с на поиск.
        Index(
            "ix_retrieval_chunks_material_fragments",
            "index_id", "material_id", "revision", "sort_order", "fragment_ids", "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    index_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("retrieval_indexes.id", ondelete="CASCADE")
    )
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_blocks.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[RetrievalChunkKind] = mapped_column(
        enum_type(RetrievalChunkKind, "retrieval_chunk_kind")
    )
    sort_order: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    page_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality: Mapped[PageQuality | None] = mapped_column(
        enum_type(PageQuality, "retrieval_chunk_quality"), nullable=True
    )
    fragment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    locator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class RetrievalBenchmarkCase(Base):
    __tablename__ = "retrieval_benchmark_cases"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    query: Mapped[str] = mapped_column(Text)
    relevant_material_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    relevant_locator_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class RetrievalBenchmarkRun(Base):
    __tablename__ = "retrieval_benchmark_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    index_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("retrieval_indexes.id", ondelete="CASCADE")
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class RetrievalExhaustiveRun(Base):
    """Зафиксированный полный обзор корпуса, переживающий перезапуск worker."""

    __tablename__ = "retrieval_exhaustive_runs"
    __table_args__ = (Index("ix_retrieval_exhaustive_session_created", "session_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("background_jobs.id", ondelete="CASCADE"), unique=True
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    user_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    final_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    query: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(32))
    corpus_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
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
    basis_kind: Mapped[ProgramBasisKind] = mapped_column(
        enum_type(ProgramBasisKind, "program_basis_kind"), default=ProgramBasisKind.CUSTOM
    )
    origin_note: Mapped[str | None] = mapped_column(String, nullable=True)
    origin_material_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # Подсказка ИИ, где искать материал для темы без опоры в источниках:
    # поисковые запросы и вид источника. Живёт отдельно от origin_note, потому
    # что переименование узла перезаписывает объяснение.
    material_search_queries: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    material_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ProgramNodeSourcePageRange(Base):
    __tablename__ = "program_node_source_page_ranges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "project_id",
            "program_node_id",
            "material_id",
            "outline_item_key",
            name="uq_program_node_source_page_range",
        ),
        CheckConstraint("page_from > 0", name="page_from_positive"),
        CheckConstraint("page_to >= page_from", name="page_range_ordered"),
        Index(
            "ix_program_node_source_ranges_project_material",
            "project_id",
            "material_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="RESTRICT")
    )
    source_name_snapshot: Mapped[str] = mapped_column(String)
    outline_item_key: Mapped[str] = mapped_column(String(200))
    page_from: Mapped[int] = mapped_column(Integer)
    page_to: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


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
    roles: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    semantic_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    semantic_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mechanism: Mapped[BindingMechanism] = mapped_column(
        enum_type(BindingMechanism, "binding_mechanism")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class CoverageRun(Base):
    """Неизменяемая область исследования; состояние исполнения принадлежит job."""

    __tablename__ = "coverage_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "request_key"),
        CheckConstraint("execution_generation >= 0", name="generation_nonnegative"),
        Index("ix_coverage_runs_project_created", "project_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="CASCADE"), unique=True
    )
    mode: Mapped[str] = mapped_column(String)
    request_key: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    protocol_version: Mapped[str] = mapped_column(String, default="verified-07")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprints: Mapped[dict[str, Any]] = mapped_column(JSON)
    model_roles: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON)
    execution_generation: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class CoverageTask(Base):
    """Ограниченный участок и неизменяемые receipts внутри одной общей задачи."""

    __tablename__ = "coverage_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "task_key"),
        Index("ix_coverage_tasks_run_state", "run_id", "state"),
        # Бюджет читает только receipts, а они лежат за checkpoint, result и
        # dependencies — четвертью мегабайта на задачу. В индексе они рядом с run_id.
        Index("ix_coverage_tasks_run_receipts", "run_id", "call_receipts"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_runs.id", ondelete="CASCADE"))
    task_key: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="overview")
    state: Mapped[str] = mapped_column(String, default="pending")
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("coverage_tasks.id", ondelete="SET NULL")
    )
    targets: Mapped[list[str]] = mapped_column(JSON)
    question: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dependencies: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    call_receipts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    stop_reason: Mapped[str | None] = mapped_column(String)


class CoverageBlockResult(Base):
    """Строка manifest существует до обработки, исторические locators переживают удаление."""

    __tablename__ = "coverage_block_results"
    __table_args__ = (
        UniqueConstraint("run_id", "block_id"),
        Index("ix_coverage_results_material_revision", "material_id", "material_revision"),
        Index("ix_coverage_results_run_state", "run_id", "work_state"),
        # Перекрывающий индекс: manifest и result весят десятки килобайт и лежат
        # физически раньше publication_state и reason, поэтому чтение даже лёгких
        # колонок тащило всю строку через overflow-страницы — 1,2 с на прогон из
        # 936 блоков. Все нужные экранам колонки лежат в самом индексе, и строка
        # таблицы больше не открывается.
        Index(
            "ix_coverage_results_projection",
            "run_id",
            "block_id",
            "work_state",
            "outcome",
            "publication_state",
            "material_id",
            "reason",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_runs.id", ondelete="CASCADE"))
    # Исторические ID намеренно без FK: материал может быть физически удалён.
    material_id: Mapped[UUID] = mapped_column(Uuid)
    material_revision: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[UUID] = mapped_column(Uuid)
    sort_order: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    work_state: Mapped[str] = mapped_column(String, default="pending")
    outcome: Mapped[str] = mapped_column(String, default="unresolved")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_version: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("coverage_tasks.id", ondelete="SET NULL")
    )
    publication_state: Mapped[str] = mapped_column(String, default="pending")
    reason: Mapped[str | None] = mapped_column(String)
    reuse_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class CoverageFinding(Base):
    """Гипотеза с опорами, но без автоматического изменения программы."""

    __tablename__ = "coverage_findings"
    __table_args__ = (Index("ix_coverage_findings_project_state", "project_id", "state"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_runs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)
    proposal_version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String, default="proposed")
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dependencies: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    applied_action_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_action_log.sequence", ondelete="SET NULL")
    )


class CoverageDecision(Base):
    """Личный запрет хранится независимо от существования Binding и материала."""

    __tablename__ = "coverage_decisions"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "target_key"),
        Index("ix_coverage_decisions_project_kind", "project_id", "kind"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)
    target_key: Mapped[str] = mapped_column(String)
    source_revision: Mapped[int | None] = mapped_column(Integer)
    anchor_fingerprint: Mapped[str | None] = mapped_column(String)
    goal_fingerprint: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    action_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_action_log.sequence", ondelete="SET NULL")
    )


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
            name=conv("ck_project_action_log_ck_project_action_log_payload_version_positive"),
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
    # Модель распознавания страниц режима «Облако». Отдельная от текстовой:
    # принимать картинку умеет далеко не всякая модель, а выбирать её надо там
    # же, где остальные — иначе один и тот же факт живёт в двух настройках.
    default_vision_provider_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="RESTRICT"),
        nullable=True,
    )
    default_vision_model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # {"provider_id": "...", "model_id": "...", "parameters": {...}} | None —
    # последний выбор в композере чата. Засевается в каждый новый чат: иначе
    # модель приходится переключать заново в каждой новой переписке.
    chat_model_preset: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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


class Activity(Base):
    """Общая проверяемая активность связывает попытки с единицей программы."""

    __tablename__ = "activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("evidence_strength >= 0 AND evidence_strength <= 1", name="strength_range"),
        Index("ix_activities_project_node", "project_id", "program_node_id"),
        # Частичный уникальный индекс: свободный ответ по теме заводится один раз,
        # а карточек по той же теме сколько угодно. Живёт в базе с миграции 0039 —
        # без объявления здесь `alembic check` считает его лишним и роняет CI.
        Index(
            "uq_activities_free_answer_node",
            "project_id",
            "program_node_id",
            unique=True,
            sqlite_where=sql_text("kind = 'free_answer'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    program_node_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    kind: Mapped[ActivityKind] = mapped_column(enum_type(ActivityKind, "activity_kind"))
    evidence_strength: Mapped[float] = mapped_column(Float, default=1.0)
    origin: Mapped[ActivityOrigin] = mapped_column(enum_type(ActivityOrigin, "activity_origin"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Card(Base):
    """Карточка хранит снимок источника, поэтому переживает удаление материала."""

    __tablename__ = "cards"
    __table_args__ = (
        Index("ix_cards_project_state", "project_id", "state", "deleted_at"),
        Index("ix_cards_source_fragment", "source_fragment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), unique=True
    )
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[CardSourceKind] = mapped_column(
        enum_type(CardSourceKind, "card_source_kind"), default=CardSourceKind.NONE
    )
    source_fragment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_fragments.id", ondelete="SET NULL"), nullable=True
    )
    source_reference_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[CardState] = mapped_column(
        enum_type(CardState, "card_state"), default=CardState.ACTIVE
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity: Mapped[Activity] = relationship(lazy="joined")


class CardSession(Base):
    """Снимок очереди позволяет продолжить сеанс после перезапуска клиента."""

    __tablename__ = "card_sessions"
    __table_args__ = (
        Index(
            "uq_card_sessions_active_project",
            "project_id",
            unique=True,
            sqlite_where=sql_text("state = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    scope: Mapped[CardSessionScope] = mapped_column(
        enum_type(CardSessionScope, "card_session_scope")
    )
    selected_unit_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    pace: Mapped[CardSessionPace] = mapped_column(enum_type(CardSessionPace, "card_session_pace"))
    limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    active_seconds: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[CardSessionState] = mapped_column(
        enum_type(CardSessionState, "card_session_state"), default=CardSessionState.ACTIVE
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("ordinal >= 1", name="ordinal_positive"),
        Index("ix_attempts_activity_created", "activity_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE")
    )
    parent_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    answer_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    active_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona: Mapped[ExaminerPersona | None] = mapped_column(
        enum_type(ExaminerPersona, "examiner_persona"), nullable=True
    )
    strictness: Mapped[ExaminerStrictness | None] = mapped_column(
        enum_type(ExaminerStrictness, "examiner_strictness"), nullable=True
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    activity: Mapped[Activity] = relationship(lazy="joined")

    @property
    def program_node_id(self) -> UUID | None:
        """Совместимое публичное поле экзамена берётся из общей Activity."""
        return self.activity.program_node_id


class Grade(Base):
    """Итог системы. Решение пользователя хранится рядом и не переписывает его."""

    __tablename__ = "grades"
    __table_args__ = (
        CheckConstraint(
            "self_assessment IS NULL OR self_assessment <> 'unscored'",
            name="self_assessment_scored",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 1 AND 4", name="confidence_range"
        ),
    )

    attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True
    )
    outcome: Mapped[AttemptOutcome] = mapped_column(enum_type(AttemptOutcome, "attempt_outcome"))
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
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ChatSession(Base):
    """Чат по одному вопросу (exam) либо по всей программе проекта (program).

    `program_node_id` — NULL у чата построения программы: он привязан к
    проекту целиком, а не к одному узлу (TEXTBOOK_MODE.md §3). Составной FK
    ниже с NULL-значением колонки просто не проверяется (SQLite MATCH SIMPLE).
    Новый чат не стирает старые.
    """

    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("project_id IS NOT NULL OR mode = 'source_search'",
                        name="library_search_scope"),
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        Index("ix_chat_sessions_node_updated", "project_id", "program_node_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    program_node_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # Ближайший предок-раздел на момент создания; NULL — плоский список.
    # Показывается и используется памятью раздела только с итерации 2.
    section_scope_node_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String)
    mode: Mapped[ChatMode] = mapped_column(enum_type(ChatMode, "chat_mode"), default=ChatMode.EXAM)
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
    # Параметры выбранной модели (`max_output_tokens`, `reasoning_effort`).
    # Отдельно от снимка выбора: его читают валидация чата и судья.
    model_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    context_flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=default_context_flags)
    draft_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class ChatMessage(Base):
    """Реплика или типизированный блок. Оценка здесь не хранится — только ссылка."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_id_sequence"),
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
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
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
        CheckConstraint("revision >= 1", name=conv("ck_conspects_ck_conspects_revision_positive")),
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


class Lesson(Base):
    """Урок — упорядоченный сценарий из ссылок на материал, пояснений, медиа и заданий."""

    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0", name="duration_nonnegative"
        ),
        Index("ix_lessons_project", "project_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[LessonStatus] = mapped_column(
        enum_type(LessonStatus, "lesson_status"), default=LessonStatus.DRAFT
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # Позиция чтения: пользователь один, отдельная таблица прохождения не нужна.
    last_block_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class LessonTopic(Base):
    """Тема урока со снимком формулировки: расхождение даёт «Требует проверки»."""

    __tablename__ = "lesson_topics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        Index("ix_lesson_topics_project_node", "project_id", "program_node_id"),
    )

    lesson_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True
    )
    program_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    topic_title_snapshot: Mapped[str] = mapped_column(String)


class LessonBlock(Base):
    __tablename__ = "lesson_blocks"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        Index("ix_lesson_blocks_lesson_order", "lesson_id", "sort_order"),
        Index("ix_lesson_blocks_ai_run", "ai_run_id"),
        Index("ix_lesson_blocks_activity", "activity_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    lesson_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE")
    )
    sort_order: Mapped[int] = mapped_column(Integer)
    kind: Mapped[LessonBlockKind] = mapped_column(enum_type(LessonBlockKind, "lesson_block_kind"))
    variant: Mapped[LessonNoteVariant | None] = mapped_column(
        enum_type(LessonNoteVariant, "lesson_note_variant"), nullable=True
    )
    body_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[LessonBlockOrigin] = mapped_column(
        enum_type(LessonBlockOrigin, "lesson_block_origin")
    )
    basis: Mapped[LessonBasis | None] = mapped_column(
        enum_type(LessonBasis, "lesson_basis"), nullable=True
    )
    ai_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True
    )
    activity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    media_path: Mapped[str | None] = mapped_column(String, nullable=True)
    bound_program_node_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class LessonSourceRef(Base):
    """Ссылка блока на материал. Удаление материала не каскадит: снимок остаётся."""

    __tablename__ = "lesson_source_refs"
    __table_args__ = (
        CheckConstraint("page_from > 0 AND page_to >= page_from", name="page_range_valid"),
        Index("ix_lesson_source_refs_block", "block_id"),
        Index("ix_lesson_source_refs_material", "material_id"),
        Index("ix_lesson_source_refs_from_fragment", "from_fragment_id"),
        Index("ix_lesson_source_refs_to_fragment", "to_fragment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("lesson_blocks.id", ondelete="CASCADE")
    )
    role: Mapped[LessonRefRole] = mapped_column(enum_type(LessonRefRole, "lesson_ref_role"))
    material_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), nullable=True
    )
    source_name_snapshot: Mapped[str] = mapped_column(String)
    material_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_from: Mapped[int] = mapped_column(Integer)
    page_to: Mapped[int] = mapped_column(Integer)
    from_fragment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_fragments.id", ondelete="SET NULL"), nullable=True
    )
    to_fragment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("material_fragments.id", ondelete="SET NULL"), nullable=True
    )
    region_bbox: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    always_pages: Mapped[bool] = mapped_column(Boolean, default=False)
    # Граничный фрагмент не нашёлся в новой ревизии — граница стала границей страницы.
    boundary_shifted: Mapped[bool] = mapped_column(Boolean, default=False)


# Регистрация таблиц подсистемы для create_all и Alembic.
from app.preparation import models as preparation_models  # noqa: E402,F401
