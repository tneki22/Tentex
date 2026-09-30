"""Индекс FK к блоку для быстрой финализации разбора материала.

Revision ID: 20260927_0068
Revises: 20260926_0067
"""

from alembic import op

revision = "20260927_0068"
down_revision = "20260926_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_retrieval_chunks_block", "retrieval_chunks", ["block_id"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_chunks_block", table_name="retrieval_chunks")
