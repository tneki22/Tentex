"""Хранилище подготовки: факты занятий отдельно от отменяемого календаря."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PreparationSettings(Base):
    """JSON соответствует PreparationConfig; номер нужен для stale-проверки."""

    __tablename__ = "preparation_settings"
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class PreparationPlan(Base):
    """Редактируемый документ ограниченного размера с атомарным сохранением."""

    __tablename__ = "preparation_plans"
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    program_revision: Mapped[int] = mapped_column(Integer, default=0)
    settings_revision: Mapped[int] = mapped_column(Integer, default=0)
    phases: Mapped[list] = mapped_column(JSON, default=list)
    items: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PreparationVersion(Base):
    """Undo восстанавливает структуру, но не удаляет реальные занятия."""

    __tablename__ = "preparation_versions"
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)


class PreparationDraft(Base):
    """Черновик хранит исходные ревизии и результат независимо от фоновой задачи."""

    __tablename__ = "preparation_drafts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    base_revision: Mapped[int] = mapped_column(Integer)
    program_revision: Mapped[int] = mapped_column(Integer)
    settings_revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    origin: Mapped[str] = mapped_column(String, default="local")
    applied_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class StudyActivity(Base):
    """Явные отметки и ручные занятия; ответы читаются непосредственно из Attempt."""

    __tablename__ = "study_activities"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("program_nodes.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, default="Занятие")
    path: Mapped[list] = mapped_column(JSON, default=list)
    kind: Mapped[str] = mapped_column(String, default="manual")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String, default="")
    understood: Mapped[bool] = mapped_column(Boolean, default=False)


class StudyInterval(Base):
    """Сырые интервалы доставляются идемпотентно; отчёты объединяют пересечения."""

    __tablename__ = "study_intervals"
    __table_args__ = (Index("ix_study_intervals_project_time", "project_id", "started_at"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"))
    node_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("program_nodes.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime] = mapped_column(DateTime)


class ReviewState(Base):
    """Проекция SM-2 пересобирается по неизменяемым попыткам и отдельному качеству."""

    __tablename__ = "preparation_reviews"
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("program_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    easiness: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    successful_count: Mapped[int] = mapped_column(Integer, default=0)
    delayed_successes: Mapped[int] = mapped_column(Integer, default=0)


class ReviewQuality(Base):
    """Уточнение качества отдельно от оценки системы и пользователя."""

    __tablename__ = "preparation_qualities"
    attempt_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True
    )
    quality: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=_now, onupdate=_now)


class PreparationCoach(Base):
    """Уникальность даты обеспечивает максимум один автоматический запуск."""

    __tablename__ = "preparation_coach"
    __table_args__ = (UniqueConstraint("project_id", "study_date"),)
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    study_date: Mapped[date] = mapped_column(Date, primary_key=True)
    text: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String, default="start")
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("background_jobs.id", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[str] = mapped_column(String, default="local")
    automatic_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class PreparationQueue(Base):
    """Дневная очередь и курсор не меняются при каждом открытии рабочей области."""

    __tablename__ = "preparation_queues"
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    study_date: Mapped[date] = mapped_column(Date, primary_key=True)
    items: Mapped[list] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    topic_position: Mapped[int] = mapped_column(Integer, default=0)
