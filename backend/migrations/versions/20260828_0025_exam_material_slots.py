"""add project-specific exam material slots

Revision ID: 20260828_0025
Revises: 20260827_0024
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0025"
down_revision: str | Sequence[str] | None = "20260827_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_materials", sa.Column("exam_slot", sa.String(length=32), nullable=True)
    )
    op.create_index(
        op.f("ix_project_materials_exam_slot"),
        "project_materials",
        ["exam_slot"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_project_materials_exam_slot"), table_name="project_materials")
    op.drop_column("project_materials", "exam_slot")
