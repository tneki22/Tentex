from datetime import UTC, date, datetime
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
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
    TEXTBOOK = "textbook"


class PageQuality(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    OCR_LOW = "ocr_low"


class ProcessingTaskKind(StrEnum):
    PARSE = "parse"


class ProcessingTaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
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


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("color IS NULL OR color BETWEEN 1 AND 8", name="color_range"),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint("program_revision >= 0", name="program_revision_nonnegative"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class MaterialPage(Base):
    __tablename__ = "material_pages"
    __table_args__ = (
        UniqueConstraint("material_id", "revision", "page_number"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("page_number > 0", name="page_number_positive"),
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_material_pages_material_revision_page", "material_id", "revision", "page_number"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class MaterialBlock(Base):
    __tablename__ = "material_blocks"
    __table_args__ = (
        UniqueConstraint("material_id", "revision", "sort_order"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint("page_from > 0 AND page_to >= page_from", name="page_range_valid"),
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
        UniqueConstraint("page_id", "sort_order"),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint(
            "structure_level IS NULL OR structure_level >= 0", name="level_nonnegative"
        ),
        Index("ix_material_fragments_page_order", "page_id", "sort_order"),
        Index("ix_material_fragments_block", "block_id"),
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
    # Заполняется у element_kind == "image": путь к вынутой из файла картинке.
    asset_path: Mapped[str | None] = mapped_column(String, nullable=True)


class ProcessingTask(Base):
    __tablename__ = "processing_tasks"
    __table_args__ = (
        CheckConstraint("done >= 0 AND total >= 0 AND done <= total", name="progress_valid"),
        Index("ix_processing_tasks_state_created", "state", "created_at"),
        Index("ix_processing_tasks_material_created", "material_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    kind: Mapped[ProcessingTaskKind] = mapped_column(
        enum_type(ProcessingTaskKind, "processing_task_kind"), default=ProcessingTaskKind.PARSE
    )
    state: Mapped[ProcessingTaskState] = mapped_column(
        enum_type(ProcessingTaskState, "processing_task_state"),
        default=ProcessingTaskState.QUEUED,
    )
    stage: Mapped[ProcessingStage] = mapped_column(
        enum_type(ProcessingStage, "processing_stage"), default=ProcessingStage.QUEUED
    )
    parser_mode: Mapped[ParserMode] = mapped_column(enum_type(ParserMode, "task_parser_mode"))
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
    origin_material_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
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
        CheckConstraint("length(trim(text)) > 0", name="text_nonblank"),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        Index("ix_reference_answers_project_active", "project_id", "is_active"),
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
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
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
        UniqueConstraint("project_id", "program_node_id", "fragment_id"),
        Index("ix_bindings_project_node", "project_id", "program_node_id"),
        Index("ix_bindings_project_fragment", "project_id", "fragment_id"),
        Index("ix_bindings_material", "material_id"),
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
        CheckConstraint("phase IN ('draft', 'active')", name="phase_value"),
        CheckConstraint("payload_version >= 1", name="payload_version_positive"),
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
