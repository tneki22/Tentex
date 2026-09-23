"""Подсказка поиска материала у узла программы: запросы и вид источника от ИИ."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0059"
down_revision = "20260922_0058"
branch_labels = None
depends_on = None


def upgrade():
    # server_default нужен уже существующим строкам; новые пишет ORM.
    op.add_column(
        "program_nodes",
        sa.Column("material_search_queries", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("program_nodes", sa.Column("material_kind", sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table("program_nodes") as batch:
        batch.drop_column("material_kind")
        batch.drop_column("material_search_queries")
