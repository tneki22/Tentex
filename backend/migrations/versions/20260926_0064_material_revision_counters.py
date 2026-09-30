"""Store immutable material counts in the active revision summary.

Revision ID: 20260926_0064
Revises: 20260926_0063
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260926_0064"
down_revision = "20260926_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    active = connection.execute(sa.text("""
        SELECT r.id, m.id AS material_id, r.summary
        FROM materials AS m
        JOIN material_revisions AS r
          ON r.material_id = m.id AND r.revision = m.active_parse_revision
    """)).all()
    block_counts = dict(connection.execute(sa.text("""
        SELECT b.material_id, count(*)
        FROM material_blocks AS b
        JOIN materials AS m
          ON m.id = b.material_id AND m.active_parse_revision = b.revision
        GROUP BY b.material_id
    """)).all())
    fragment_counts = dict(connection.execute(sa.text("""
        SELECT f.material_id, count(*)
        FROM material_fragments AS f
        JOIN material_pages AS p ON p.id = f.page_id
        JOIN materials AS m
          ON m.id = f.material_id AND m.active_parse_revision = p.revision
        GROUP BY f.material_id
    """)).all())
    headings = set(connection.execute(sa.text("""
        SELECT DISTINCT f.material_id
        FROM material_fragments AS f
        JOIN material_pages AS p ON p.id = f.page_id
        JOIN materials AS m
          ON m.id = f.material_id AND m.active_parse_revision = p.revision
        WHERE f.structure_level IS NOT NULL
    """)).scalars())
    for row_id, material_id, raw_summary in active:
        summary = json.loads(raw_summary or "{}")
        summary.update(
            block_count=block_counts.get(material_id, 0),
            fragment_count=fragment_counts.get(material_id, 0),
            has_headings=material_id in headings,
        )
        connection.execute(
            sa.text("UPDATE material_revisions SET summary = :summary WHERE id = :id"),
            {"summary": json.dumps(summary, ensure_ascii=False), "id": row_id},
        )


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE material_revisions
        SET summary = json_remove(summary, '$.block_count', '$.fragment_count', '$.has_headings')
        WHERE EXISTS (
            SELECT 1 FROM materials AS m
            WHERE m.id = material_revisions.material_id
              AND m.active_parse_revision = material_revisions.revision
        )
    """))
