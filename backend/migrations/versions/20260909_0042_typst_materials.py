"""Добавляет воспроизводимые Typst-материалы и исходные чанки.

Revision ID: 20260909_0042
Revises: 20260907_0041
"""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0042"
down_revision = "20260907_0041"
branch_labels = None
depends_on = None

OLD_MATERIAL_STATES = ("ready_to_process", "queued", "processing", "paused", "ready", "failed")
NEW_MATERIAL_STATES = (*OLD_MATERIAL_STATES, "needs_input")
OLD_SOURCE_KINDS = ("file", "text", "url", "youtube", "audio")
NEW_SOURCE_KINDS = (*OLD_SOURCE_KINDS, "typst")
OLD_JOB_KINDS = (
    "parse",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
    "ai_answer_sections",
)
NEW_JOB_KINDS = (*OLD_JOB_KINDS, "typst_compile")


def enum(*values: str, name: str) -> sa.Enum:
    """SQLite enum с CHECK: его нельзя расширить одним UPDATE."""
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    """Расширить перечисления SQLite через пересоздание CHECK и добавить таблицы."""
    with op.batch_alter_table("materials") as batch:
        batch.alter_column(
            "status",
            existing_type=enum(*OLD_MATERIAL_STATES, name="material_state"),
            type_=enum(*NEW_MATERIAL_STATES, name="material_state"),
            existing_nullable=False,
        )
        batch.alter_column(
            "source_kind",
            existing_type=enum(*OLD_SOURCE_KINDS, name="material_source_kind"),
            type_=enum(*NEW_SOURCE_KINDS, name="material_source_kind"),
            existing_nullable=False,
        )
    with op.batch_alter_table("material_revisions") as batch:
        batch.add_column(sa.Column("render_storage_path", sa.String(), nullable=True))
    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column(
            "kind",
            existing_type=enum(*OLD_JOB_KINDS, name="background_job_kind"),
            type_=enum(*NEW_JOB_KINDS, name="background_job_kind"),
            existing_nullable=False,
        )
    op.create_table(
        "typst_materials",
        sa.Column(
            "material_id",
            sa.Uuid(),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("input_kind", sa.String(length=16), nullable=False),
        sa.Column("entrypoint", sa.String(), nullable=True),
        sa.Column("compiler_version", sa.String(), nullable=True),
        sa.Column("build_hash", sa.String(length=64), nullable=True),
        sa.Column("packages", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("issues", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("current_pdf_path", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "typst_source_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "material_id",
            sa.Uuid(),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("line_from", sa.Integer(), nullable=False),
        sa.Column("line_to", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("diagnostic", sa.String(), nullable=True),
        sa.CheckConstraint("line_from > 0 AND line_to >= line_from", name="typst_chunk_line_range"),
    )
    op.create_index(
        "ix_typst_source_chunks_material_revision",
        "typst_source_chunks",
        ["material_id", "revision", "sort_order"],
    )


def downgrade() -> None:
    """Удалить типст-расширения без затрагивания общих материалов."""
    op.drop_index("ix_typst_source_chunks_material_revision", table_name="typst_source_chunks")
    op.drop_table("typst_source_chunks")
    op.drop_table("typst_materials")
    with op.batch_alter_table("material_revisions") as batch:
        batch.drop_column("render_storage_path")
    op.execute("DELETE FROM background_jobs WHERE kind = 'typst_compile'")
    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column(
            "kind",
            existing_type=enum(*NEW_JOB_KINDS, name="background_job_kind"),
            type_=enum(*OLD_JOB_KINDS, name="background_job_kind"),
            existing_nullable=False,
        )
    with op.batch_alter_table("materials") as batch:
        batch.alter_column(
            "source_kind",
            existing_type=enum(*NEW_SOURCE_KINDS, name="material_source_kind"),
            type_=enum(*OLD_SOURCE_KINDS, name="material_source_kind"),
            existing_nullable=False,
        )
        batch.alter_column(
            "status",
            existing_type=enum(*NEW_MATERIAL_STATES, name="material_state"),
            type_=enum(*OLD_MATERIAL_STATES, name="material_state"),
            existing_nullable=False,
        )
