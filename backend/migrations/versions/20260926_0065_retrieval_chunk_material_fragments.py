"""Covering index for mapping lexical fragments to retrieval chunks.

`_chunk_lookup` reads `fragment_ids` of the found materials' chunks, and the
readiness checks look for one chunk of the current revision per material.
Without a covering index SQLite read each row with its long text and embedding;
this index answers both from the columns it stores.

Revision ID: 20260926_0065
Revises: 20260926_0064
"""

from alembic import op

revision = "20260926_0065"
down_revision = "20260926_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_retrieval_chunks_material_fragments",
        "retrieval_chunks",
        ["index_id", "material_id", "revision", "sort_order", "fragment_ids", "id"],
        # Индекс мог появиться раньше слияния ветки: проверочный стенд работал
        # на той же базе, что и основной.
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_chunks_material_fragments", table_name="retrieval_chunks")
