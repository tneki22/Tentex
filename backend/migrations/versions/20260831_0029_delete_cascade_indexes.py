"""indexes for material cascades and the library summary

Revision ID: 20260831_0029
Revises: 20260829_0028
Create Date: 2026-08-31

Удаление материала стоило секунды: у `bindings.fragment_id` и `bindings.block_id`
нет индексов, поэтому SQLite сканировал всю таблицу привязок на каждый удаляемый
фрагмент и каждый блок — O(фрагменты × привязки). У `material_fragments.material_id`
индекса тоже не было: полный скан и при удалении, и на каждой загрузке Библиотеки.

Плюс покрывающие индексы под сводку Библиотеки: строки `material_pages` тяжёлые
(`elements`, `markdown`, `text`), и подсчёт качества с подсчётом фрагментов читали
всю таблицу целиком — 5 секунд на `GET /api/materials` через bind-mount с хоста.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0029"
down_revision: str | Sequence[str] | None = "20260829_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_material_fragments_material", "material_fragments", ["material_id"])
    op.create_index("ix_bindings_fragment", "bindings", ["fragment_id"])
    op.create_index("ix_bindings_block", "bindings", ["block_id"])
    op.create_index(
        "ix_reference_answers_source_material", "reference_answers", ["source_material_id"]
    )
    op.create_index(
        "ix_material_pages_material_revision_quality",
        "material_pages",
        ["material_id", "revision", "quality", "reviewed_at"],
    )
    op.create_index("ix_material_pages_revision_lookup", "material_pages", ["id", "revision"])
    op.create_index(
        "ix_material_fragments_material_page", "material_fragments", ["material_id", "page_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_material_fragments_material_page", table_name="material_fragments")
    op.drop_index("ix_material_pages_revision_lookup", table_name="material_pages")
    op.drop_index("ix_material_pages_material_revision_quality", table_name="material_pages")
    op.drop_index("ix_reference_answers_source_material", table_name="reference_answers")
    op.drop_index("ix_bindings_block", table_name="bindings")
    op.drop_index("ix_bindings_fragment", table_name="bindings")
    op.drop_index("ix_material_fragments_material", table_name="material_fragments")
