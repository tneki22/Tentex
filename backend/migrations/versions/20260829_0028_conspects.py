"""add conspect and conspect image tables

Revision ID: 20260829_0028
Revises: 20260829_0027
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0028"
down_revision: str | Sequence[str] | None = "20260829_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conspects",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
            name="fk_conspects_program_node",
        ),
        sa.PrimaryKeyConstraint("project_id", "program_node_id", name="pk_conspects"),
        sa.CheckConstraint("revision >= 1", name="ck_conspects_revision_positive"),
    )
    op.create_index("ix_conspects_project", "conspects", ["project_id"], unique=False)

    op.create_table(
        "conspect_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
            name="fk_conspect_images_program_node",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conspect_images"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_conspect_images_size_nonnegative"),
    )
    op.create_index(
        "ix_conspect_images_project_node",
        "conspect_images",
        ["project_id", "program_node_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conspect_images_project_node", table_name="conspect_images")
    op.drop_table("conspect_images")
    op.drop_index("ix_conspects_project", table_name="conspects")
    op.drop_table("conspects")
