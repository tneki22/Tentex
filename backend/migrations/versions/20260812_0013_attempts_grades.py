"""exam attempts, grades, and chat references

Revision ID: 20260812_0013
Revises: 20260812_0012
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0013"
down_revision: str | Sequence[str] | None = "20260812_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("parent_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "persona",
            enum("calm_teacher", "neutral_examiner", "strict_reviewer", name="examiner_persona"),
            nullable=False,
        ),
        sa.Column(
            "strictness",
            enum("soft", "normal", "strict", name="examiner_strictness"),
            nullable=False,
        ),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("ordinal >= 1", name=op.f("ck_attempts_ordinal_positive")),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
            name=op.f("fk_attempts_project_id_program_node_id_program_nodes"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_attempt_id"],
            ["attempts.id"],
            ondelete="SET NULL",
            name=op.f("fk_attempts_parent_attempt_id_attempts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempts")),
    )
    op.create_index(
        "ix_attempts_node_created",
        "attempts",
        ["project_id", "program_node_id", "created_at"],
    )
    op.create_table(
        "grades",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column(
            "outcome",
            enum("passed", "partial", "failed", "unscored", name="attempt_outcome"),
            nullable=False,
        ),
        sa.Column(
            "method",
            enum(
                "exact_match",
                "key_terms",
                "sql",
                "semantic",
                "ai_judge",
                "self_assessment",
                name="grade_method",
            ),
            nullable=True,
        ),
        sa.Column("credited_points", sa.JSON(), nullable=False),
        sa.Column("missed_points", sa.JSON(), nullable=False),
        sa.Column("wrong_points", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "self_assessment",
            enum("passed", "partial", "failed", "unscored", name="attempt_outcome"),
            nullable=True,
        ),
        sa.Column("ai_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "self_assessment IS NULL OR self_assessment <> 'unscored'",
            name=op.f("ck_grades_self_assessment_scored"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.id"],
            ondelete="CASCADE",
            name=op.f("fk_grades_attempt_id_attempts"),
        ),
        sa.ForeignKeyConstraint(
            ["ai_run_id"],
            ["ai_runs.id"],
            ondelete="SET NULL",
            name=op.f("fk_grades_ai_run_id_ai_runs"),
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_grades")),
    )
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("attempt_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("grade_attempt_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_chat_messages_attempt_id_attempts"),
            "attempts",
            ["attempt_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            op.f("fk_chat_messages_grade_attempt_id_grades"),
            "grades",
            ["grade_attempt_id"],
            ["attempt_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_constraint(
            op.f("fk_chat_messages_grade_attempt_id_grades"), type_="foreignkey"
        )
        batch.drop_constraint(op.f("fk_chat_messages_attempt_id_attempts"), type_="foreignkey")
        batch.drop_column("grade_attempt_id")
        batch.drop_column("attempt_id")
    op.drop_table("grades")
    op.drop_index("ix_attempts_node_created", table_name="attempts")
    op.drop_table("attempts")
