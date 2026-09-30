"""Drop the covering fragment index of retrieval chunks.

`0065` let `_chunk_lookup` read `fragment_ids` without the chunk text and
vector. The lookup now lives in the in-memory index snapshot
(`app/retrieval/snapshot.py`), which also serves the vector search, so the
index is no longer read. It stored the JSON list of fragment ids of every
chunk and grew each index build.

Revision ID: 20260926_0066
Revises: 20260926_0065
"""

from alembic import op

revision = "20260926_0066"
down_revision = "20260926_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_retrieval_chunks_material_fragments",
        table_name="retrieval_chunks",
        if_exists=True,
    )


def downgrade() -> None:
    op.create_index(
        "ix_retrieval_chunks_material_fragments",
        "retrieval_chunks",
        ["index_id", "material_id", "revision", "sort_order", "fragment_ids", "id"],
        if_not_exists=True,
    )
