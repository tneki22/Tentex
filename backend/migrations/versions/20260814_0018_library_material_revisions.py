"""register material revisions and timed fragments

Revision ID: 20260814_0018
Revises: 20260814_0017
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0018"
down_revision: str | Sequence[str] | None = "20260814_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORIGINS = (
    "imported",
    "parse",
    "manual_edit",
    "ai_cleanup",
    "source_refresh",
    "restore",
)


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "material_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "material_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("origin", enum(*ORIGINS, name="material_revision_origin"), nullable=False),
        sa.Column(
            "parser_mode",
            enum("fast", "textbook", name="revision_parser_mode"),
            nullable=True,
        ),
        sa.Column("parent_revision", sa.Integer(), nullable=True),
        # Без FK на processing_tasks: задача живёт короче ревизии и вычищается
        # вместе с материалом, а ON DELETE SET NULL на SQLite потребовал бы
        # пересборки таблицы при каждой чистке журнала задач.
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_storage_path", sa.String(), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("material_id", "revision", name="uq_material_revision"),
        sa.CheckConstraint("revision > 0", name="revision_positive"),
        sa.CheckConstraint(
            "parent_revision IS NULL OR parent_revision > 0", name="parent_revision_positive"
        ),
    )
    op.create_index(
        "ix_material_revisions_material_revision",
        "material_revisions",
        ["material_id", "revision"],
    )

    with op.batch_alter_table("material_fragments") as batch:
        batch.add_column(sa.Column("time_from", sa.Float(), nullable=True))
        batch.add_column(sa.Column("time_to", sa.Float(), nullable=True))
        batch.create_check_constraint(
            "time_from_nonnegative", "time_from IS NULL OR time_from >= 0"
        )
        batch.create_check_constraint("time_to_nonnegative", "time_to IS NULL OR time_to >= 0")
        batch.create_check_constraint(
            "time_range_valid",
            "time_to IS NULL OR time_from IS NULL OR time_to >= time_from",
        )

    # Уже разобранные материалы получают историю: каждая существующая пара
    # (material_id, revision) становится записью «Первичная обработка».
    op.execute(
        """
        INSERT INTO material_revisions (
            id, material_id, revision, origin, parser_mode, parent_revision,
            task_id, source_storage_path, source_hash, scope, summary, created_at
        )
        SELECT
            lower(hex(randomblob(16))),
            pages.material_id,
            pages.revision,
            'imported',
            materials.parser_mode,
            CASE WHEN pages.revision > 1 THEN pages.revision - 1 END,
            NULL,
            materials.storage_path,
            materials.sha256,
            '{}',
            '{}',
            COALESCE(MIN(pages.created_at), materials.created_at)
        FROM material_pages AS pages
        JOIN materials ON materials.id = pages.material_id
        GROUP BY pages.material_id, pages.revision
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("material_fragments") as batch:
        batch.drop_constraint("time_range_valid", type_="check")
        batch.drop_constraint("time_to_nonnegative", type_="check")
        batch.drop_constraint("time_from_nonnegative", type_="check")
        batch.drop_column("time_to")
        batch.drop_column("time_from")
    op.drop_index("ix_material_revisions_material_revision", table_name="material_revisions")
    op.drop_table("material_revisions")
