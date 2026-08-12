"""images inside materials and files attached to reference answers

Картинки из PDF и DOCX становятся обычными фрагментами (element_kind = "image"),
поэтому привязываются к вопросу тем же механизмом, что и текст. К эталонному
ответу вдобавок можно принести свой файл — для него отдельная таблица.

Revision ID: 20260812_0009
Revises: 20260812_0008
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0009"
down_revision: str | Sequence[str] | None = "20260812_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("material_fragments", sa.Column("asset_path", sa.String(), nullable=True))
    op.create_table(
        "reference_answer_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "size_bytes >= 0", name="ck_reference_answer_attachments_size_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            name="fk_reference_answer_attachments_program_node",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reference_answer_attachments"),
    )
    op.create_index(
        "ix_answer_attachments_node",
        "reference_answer_attachments",
        ["project_id", "program_node_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_answer_attachments_node", table_name="reference_answer_attachments")
    op.drop_table("reference_answer_attachments")
    op.drop_column("material_fragments", "asset_path")
