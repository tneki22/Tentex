"""Частичный индекс заголовков фрагмента: «есть ли оглавление» без чтения 88 тысяч строк."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0053"
down_revision = "20260920_0052"
branch_labels = None
depends_on = None

INDEX = "ix_material_fragments_headings"


def upgrade():
    # Заголовки — пятая часть фрагментов, поэтому индекс частичный: он покрывает
    # ровно тот вопрос, который Библиотека задаёт про каждый материал.
    op.create_index(
        INDEX,
        "material_fragments",
        ["material_id", "page_id"],
        sqlite_where=sa.column("structure_level").is_not(None),
    )


def downgrade():
    op.drop_index(INDEX, table_name="material_fragments")
