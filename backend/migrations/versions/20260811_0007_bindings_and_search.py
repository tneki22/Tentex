"""fragment search index (fts5) and manual bindings

Revision ID: 20260811_0007
Revises: 20260810_0006
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0007"
down_revision: str | Sequence[str] | None = "20260810_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.execute(
        "CREATE VIRTUAL TABLE fragment_search USING fts5("
        "text, lemmas, fragment_id UNINDEXED, material_id UNINDEXED, "
        'tokenize = "unicode61 remove_diacritics 2")'
    )
    op.create_table(
        "fragment_search_map",
        sa.Column("fragment_id", sa.String(), nullable=False),
        sa.Column("material_id", sa.String(), nullable=False),
        sa.Column("rowid", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("fragment_id", name="pk_fragment_search_map"),
    )
    op.create_index(
        "ix_fragment_search_map_material", "fragment_search_map", ["material_id"], unique=False
    )

    from app.materials.lexicon import index_text

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT f.id, f.material_id, f.text FROM material_fragments f "
            "JOIN material_pages p ON p.id = f.page_id "
            "JOIN materials m ON m.id = f.material_id "
            "WHERE p.revision = m.active_parse_revision"
        )
    ).fetchall()
    for fragment_id, material_id, fragment_text in rows:
        lemmas = index_text(fragment_text)
        bind.execute(
            sa.text(
                "INSERT INTO fragment_search(text, lemmas, fragment_id, material_id) "
                "VALUES (:text, :lemmas, :fragment_id, :material_id)"
            ),
            {
                "text": fragment_text,
                "lemmas": lemmas,
                "fragment_id": fragment_id,
                "material_id": material_id,
            },
        )
        new_rowid = bind.execute(sa.text("SELECT last_insert_rowid()")).scalar()
        bind.execute(
            sa.text(
                "INSERT INTO fragment_search_map(fragment_id, material_id, rowid) "
                "VALUES (:fragment_id, :material_id, :rowid)"
            ),
            {"fragment_id": fragment_id, "material_id": material_id, "rowid": new_rowid},
        )

    op.create_table(
        "bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("fragment_id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            enum("manual", "confirmed", "machine", "removed", "orphaned", name="binding_status"),
            nullable=False,
        ),
        sa.Column(
            "mechanism",
            enum("manual", "search", "pass_two", name="binding_mechanism"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
            name="fk_bindings_program_node",
        ),
        sa.ForeignKeyConstraint(
            ["fragment_id"],
            ["material_fragments.id"],
            ondelete="CASCADE",
            name="fk_bindings_fragment_id_material_fragments",
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            ondelete="CASCADE",
            name="fk_bindings_material_id_materials",
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["material_blocks.id"],
            ondelete="CASCADE",
            name="fk_bindings_block_id_material_blocks",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bindings"),
        sa.UniqueConstraint(
            "project_id", "program_node_id", "fragment_id", name="uq_bindings_node_fragment"
        ),
    )
    op.create_index(
        "ix_bindings_project_node", "bindings", ["project_id", "program_node_id"], unique=False
    )
    op.create_index(
        "ix_bindings_project_fragment", "bindings", ["project_id", "fragment_id"], unique=False
    )
    op.create_index("ix_bindings_material", "bindings", ["material_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bindings_material", table_name="bindings")
    op.drop_index("ix_bindings_project_fragment", table_name="bindings")
    op.drop_index("ix_bindings_project_node", table_name="bindings")
    op.drop_table("bindings")
    op.drop_index("ix_fragment_search_map_material", table_name="fragment_search_map")
    op.drop_table("fragment_search_map")
    op.execute("DROP TABLE IF EXISTS fragment_search")
