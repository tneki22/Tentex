"""add revisioned program journal

Revision ID: 20260808_0003
Revises: 6c7ad9e40c82
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0003"
down_revision: str | Sequence[str] | None = "6c7ad9e40c82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column("program_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "ck_projects_program_revision_nonnegative", "program_revision >= 0"
        )

    op.execute(
        """
        UPDATE program_nodes
        SET target_level = (
            SELECT goal_passports.target_outcome
            FROM goal_passports
            WHERE goal_passports.project_id = program_nodes.project_id
        )
        WHERE target_level IS NULL
          AND EXISTS (
            SELECT 1 FROM goal_passports
            WHERE goal_passports.project_id = program_nodes.project_id
              AND goal_passports.target_outcome IS NOT NULL
          )
        """
    )

    op.create_table(
        "project_action_log",
        sa.Column("sequence", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("target_title", sa.String(), nullable=False),
        sa.Column("inverse_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "phase IN ('draft', 'active')", name="ck_project_action_log_phase_value"
        ),
        sa.CheckConstraint(
            "payload_version >= 1",
            name="ck_project_action_log_payload_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_action_log_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("sequence", name="pk_project_action_log"),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_project_action_log_project_phase_undone_sequence",
        "project_action_log",
        ["project_id", "phase", "undone_at", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_action_log_project_phase_undone_sequence",
        table_name="project_action_log",
    )
    op.drop_table("project_action_log")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("ck_projects_program_revision_nonnegative", type_="check")
        batch_op.drop_column("program_revision")
