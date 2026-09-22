"""Persist how much of a stopped retrieval index is usable.

Revision ID: 20260922_0057
Revises: 20260922_0056
"""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0057"
down_revision = "20260922_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("retrieval_indexes") as batch:
        batch.add_column(
            sa.Column("indexed_material_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint(
            op.f("ck_retrieval_indexes_indexed_material_count_nonnegative"),
            "indexed_material_count >= 0",
        )
    # До появления счётчика все сохранённые `ready`/`active` кандидаты могли
    # возникнуть только после полного обхода корпуса. Не показываем их как
    # неполные только потому, что у старой схемы не было отдельного поля.
    op.execute(
        "UPDATE retrieval_indexes "
        "SET indexed_material_count = material_count "
        "WHERE state IN ('ready', 'active')"
    )


def downgrade() -> None:
    with op.batch_alter_table("retrieval_indexes") as batch:
        batch.drop_constraint(
            op.f("ck_retrieval_indexes_indexed_material_count_nonnegative"), type_="check"
        )
        batch.drop_column("indexed_material_count")
