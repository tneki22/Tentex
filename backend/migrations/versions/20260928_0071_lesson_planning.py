"""Время открытых уроков и граница отключения планирования.

Revision ID: 20260928_0071
Revises: 20260927_0070
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0071"
down_revision = "20260927_0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет nullable-поля без перестройки SQLite-таблиц."""
    op.add_column(
        "projects", sa.Column("lesson_planning_disabled_at", sa.DateTime(), nullable=True)
    )
    op.add_column("study_intervals", sa.Column("lesson_id", sa.Uuid(), nullable=True))
    op.add_column("study_intervals", sa.Column("lesson_title", sa.String(), nullable=True))
    op.create_index("ix_study_intervals_lesson", "study_intervals", ["project_id", "lesson_id"])


def downgrade() -> None:
    """Удаляет поля учебникового времени."""
    op.drop_index("ix_study_intervals_lesson", table_name="study_intervals")
    op.drop_column("study_intervals", "lesson_title")
    op.drop_column("study_intervals", "lesson_id")
    op.drop_column("projects", "lesson_planning_disabled_at")
