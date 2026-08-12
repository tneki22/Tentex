"""add stage 5 material processing pipeline

Revision ID: 20260810_0005
Revises: 20260809_0004
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0005"
down_revision: str | Sequence[str] | None = "20260809_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    with op.batch_alter_table("materials") as batch:
        batch.add_column(
            sa.Column(
                "status",
                enum(
                    "ready_to_process",
                    "queued",
                    "processing",
                    "paused",
                    "ready",
                    "failed",
                    name="material_state",
                ),
                nullable=False,
                server_default="ready_to_process",
            )
        )
        batch.add_column(
            sa.Column("active_parse_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("parser_mode", enum("fast", "textbook", name="parser_mode"), nullable=True)
        )
        batch.add_column(
            sa.Column("scan_page_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("ocr_low_page_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("estimated_seconds", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("diagnostics", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.execute("UPDATE materials SET updated_at = created_at WHERE updated_at IS NULL")
    with op.batch_alter_table("materials") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)

    with op.batch_alter_table("project_materials") as batch:
        batch.add_column(sa.Column("display_name", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("purposes", sa.JSON(), nullable=False, server_default='["study_source"]')
        )

    op.create_table(
        "material_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("quality", enum("native", "ocr", "ocr_low", name="page_quality"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("elements", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_material_pages_revision_positive"),
        sa.CheckConstraint("page_number > 0", name="ck_material_pages_page_number_positive"),
        sa.CheckConstraint(
            "width > 0 AND height > 0", name="ck_material_pages_dimensions_positive"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_material_pages_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            ondelete="CASCADE",
            name="fk_material_pages_material_id_materials",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_pages"),
        sa.UniqueConstraint(
            "material_id", "revision", "page_number", name="uq_material_pages_revision_page"
        ),
    )
    op.create_index(
        "ix_material_pages_material_revision_page",
        "material_pages",
        ["material_id", "revision", "page_number"],
        unique=False,
    )

    op.create_table(
        "material_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("block_class", enum("content", "service", name="block_class"), nullable=False),
        sa.Column("service_reason", sa.String(), nullable=True),
        sa.Column("page_from", sa.Integer(), nullable=False),
        sa.Column("page_to", sa.Integer(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_material_blocks_revision_positive"),
        sa.CheckConstraint("sort_order >= 0", name="ck_material_blocks_sort_order_nonnegative"),
        sa.CheckConstraint(
            "page_from > 0 AND page_to >= page_from", name="ck_material_blocks_page_range_valid"
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            ondelete="CASCADE",
            name="fk_material_blocks_material_id_materials",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_blocks"),
        sa.UniqueConstraint(
            "material_id", "revision", "sort_order", name="uq_material_blocks_revision_order"
        ),
    )
    op.create_index(
        "ix_material_blocks_material_revision_order",
        "material_blocks",
        ["material_id", "revision", "sort_order"],
        unique=False,
    )

    op.create_table(
        "material_fragments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("element_kind", sa.String(), nullable=False),
        sa.Column("structure_level", sa.Integer(), nullable=True),
        sa.Column("degraded_structure", sa.Boolean(), nullable=False),
        sa.Column(
            "quality", enum("native", "ocr", "ocr_low", name="fragment_quality"), nullable=False
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_material_fragments_sort_order_nonnegative"),
        sa.CheckConstraint(
            "structure_level IS NULL OR structure_level >= 0",
            name="ck_material_fragments_level_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            ondelete="CASCADE",
            name="fk_material_fragments_material_id_materials",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["material_pages.id"],
            ondelete="CASCADE",
            name="fk_material_fragments_page_id_material_pages",
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["material_blocks.id"],
            ondelete="CASCADE",
            name="fk_material_fragments_block_id_material_blocks",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_fragments"),
        sa.UniqueConstraint("page_id", "sort_order", name="uq_material_fragments_page_order"),
    )
    op.create_index(
        "ix_material_fragments_page_order", "material_fragments", ["page_id", "sort_order"]
    )
    op.create_index("ix_material_fragments_block", "material_fragments", ["block_id"])

    op.create_table(
        "processing_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("kind", enum("parse", name="processing_task_kind"), nullable=False),
        sa.Column(
            "state",
            enum(
                "queued", "running", "paused", "failed", "completed", name="processing_task_state"
            ),
            nullable=False,
        ),
        sa.Column(
            "stage",
            enum("queued", "extract", "segment", "complete", name="processing_stage"),
            nullable=False,
        ),
        sa.Column("parser_mode", enum("fast", "textbook", name="task_parser_mode"), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pause_requested", sa.Boolean(), nullable=False),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "done >= 0 AND total >= 0 AND done <= total", name="ck_processing_tasks_progress_valid"
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            ondelete="CASCADE",
            name="fk_processing_tasks_material_id_materials",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_tasks"),
    )
    op.create_index(
        "ix_processing_tasks_state_created", "processing_tasks", ["state", "created_at"]
    )
    op.create_index(
        "ix_processing_tasks_material_created", "processing_tasks", ["material_id", "created_at"]
    )

    with op.batch_alter_table("reference_answers") as batch:
        batch.add_column(sa.Column("source_material_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("source_page_from", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_page_to", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_reference_answers_source_material_id_materials",
            "materials",
            ["source_material_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("reference_answers") as batch:
        batch.drop_constraint(
            "fk_reference_answers_source_material_id_materials", type_="foreignkey"
        )
        batch.drop_column("source_page_to")
        batch.drop_column("source_page_from")
        batch.drop_column("source_material_id")
    op.drop_index("ix_processing_tasks_material_created", table_name="processing_tasks")
    op.drop_index("ix_processing_tasks_state_created", table_name="processing_tasks")
    op.drop_table("processing_tasks")
    op.drop_index("ix_material_fragments_block", table_name="material_fragments")
    op.drop_index("ix_material_fragments_page_order", table_name="material_fragments")
    op.drop_table("material_fragments")
    op.drop_index("ix_material_blocks_material_revision_order", table_name="material_blocks")
    op.drop_table("material_blocks")
    op.drop_index("ix_material_pages_material_revision_page", table_name="material_pages")
    op.drop_table("material_pages")
    with op.batch_alter_table("project_materials") as batch:
        batch.drop_column("purposes")
        batch.drop_column("display_name")
    with op.batch_alter_table("materials") as batch:
        for column in (
            "updated_at",
            "error",
            "diagnostics",
            "estimated_seconds",
            "ocr_low_page_count",
            "scan_page_count",
            "parser_mode",
            "active_parse_revision",
            "status",
        ):
            batch.drop_column(column)
