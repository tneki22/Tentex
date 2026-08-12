"""finish stage 5 material sources and program provenance

Revision ID: 20260810_0006
Revises: 20260810_0005
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0006"
down_revision: str | Sequence[str] | None = "20260810_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.add_column(
        "materials",
        sa.Column(
            "source_kind",
            enum("file", "text", "url", "youtube", "audio", name="material_source_kind"),
            nullable=False,
            server_default="file",
        )
    )
    op.add_column("materials", sa.Column("source_url", sa.String(), nullable=True))
    op.add_column("materials", sa.Column("retrieved_at", sa.DateTime(), nullable=True))
    op.add_column(
        "materials",
        sa.Column("outline", sa.JSON(), nullable=False, server_default="[]"),
    )

    op.execute(
        "UPDATE materials SET source_kind = 'text' "
        "WHERE media_type IN ('text/plain', 'text/markdown')"
    )

    op.add_column("program_nodes", sa.Column("origin_material_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_program_nodes_origin_material_id", "program_nodes", ["origin_material_id"]
    )
    op.execute(
        "CREATE TRIGGER tr_material_delete_program_origin "
        "AFTER DELETE ON materials BEGIN "
        "UPDATE program_nodes SET origin_material_id = NULL WHERE origin_material_id = OLD.id; "
        "END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tr_material_delete_program_origin")
    op.drop_index("ix_program_nodes_origin_material_id", table_name="program_nodes")
    op.drop_column("program_nodes", "origin_material_id")
    op.drop_column("materials", "retrieved_at")
    op.drop_column("materials", "source_url")
    op.drop_column("materials", "outline")
    op.drop_column("materials", "source_kind")
