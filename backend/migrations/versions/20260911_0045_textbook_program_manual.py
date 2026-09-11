"""Добавляет основу узла программы и диапазоны страниц оглавления.

Revision ID: 20260911_0045
Revises: 20260909_0044
"""

import sqlalchemy as sa
from alembic import op

revision = "20260911_0045"
down_revision = "20260909_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Считать старые узлы собственными и создать таблицу доказательств оглавления."""
    with op.batch_alter_table("program_nodes") as batch:
        batch.add_column(
            sa.Column("basis_kind", sa.String(length=7), nullable=False, server_default="custom")
        )
        batch.create_check_constraint(
            op.f("ck_program_nodes_program_basis_kind"),
            sa.column("basis_kind").in_(("outline", "custom")),
        )
    op.create_table(
        "program_node_source_page_ranges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("source_name_snapshot", sa.String(), nullable=False),
        sa.Column("outline_item_key", sa.String(length=200), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=False),
        sa.Column("page_to", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "page_from > 0",
            name=op.f("ck_program_node_source_page_ranges_page_from_positive"),
        ),
        sa.CheckConstraint(
            "page_to >= page_from",
            name=op.f("ck_program_node_source_page_ranges_page_range_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            name=op.f("fk_program_node_source_page_ranges_material_id_materials"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            name=op.f("fk_program_node_source_page_ranges_project_node_program_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_program_node_source_page_ranges")),
        sa.UniqueConstraint(
            "project_id",
            "program_node_id",
            "material_id",
            "outline_item_key",
            name="uq_program_node_source_page_range",
        ),
    )
    op.create_index(
        "ix_program_node_source_ranges_project_material",
        "program_node_source_page_ranges",
        ["project_id", "material_id"],
        unique=False,
    )


def downgrade() -> None:
    """Удалить диапазоны и признак основы программы."""
    op.drop_index(
        "ix_program_node_source_ranges_project_material",
        table_name="program_node_source_page_ranges",
    )
    op.drop_table("program_node_source_page_ranges")
    checks = [
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("program_nodes")
        if constraint["name"] and "basis_kind IN" in (constraint["sqltext"] or "")
    ]
    with op.batch_alter_table("program_nodes") as batch:
        for check in checks:
            batch.drop_constraint(op.f(check), type_="check")
        batch.drop_column("basis_kind")
