"""add reference answers linked to stable program nodes

Revision ID: 20260809_0004
Revises: 20260808_0003
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0004"
down_revision: str | Sequence[str] | None = "20260808_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reference_answers",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "origin_kind",
            sa.Enum(
                "manual",
                "import",
                name="reference_answer_origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "match_method",
            sa.Enum(
                "manual",
                "exact_title",
                name="reference_answer_match_method",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("matched_title", sa.String(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_label", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(trim(text)) > 0", name="ck_reference_answers_text_nonblank"),
        sa.CheckConstraint("revision >= 0", name="ck_reference_answers_revision_nonnegative"),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            name="fk_reference_answers_project_id_program_nodes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "project_id",
            "program_node_id",
            name="pk_reference_answers",
        ),
    )
    op.create_index(
        "ix_reference_answers_project_active",
        "reference_answers",
        ["project_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reference_answers_project_active", table_name="reference_answers")
    op.drop_table("reference_answers")
