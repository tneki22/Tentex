"""record answers linked by verified numbering

Revision ID: 20260814_0017
Revises: 20260814_0016
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0017"
down_revision: str | Sequence[str] | None = "20260814_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_METHODS = ("manual", "exact_title", "fuzzy_title", "resolved_title")
NEW_METHODS = (*OLD_METHODS, "numbered_order")


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _rewrite_method(values: tuple[str, ...]) -> None:
    # SQLite хранит перечисление как CHECK-ограничение и расширяет его пересборкой.
    with op.batch_alter_table("reference_answers") as batch:
        batch.alter_column(
            "match_method",
            existing_type=sa.String(),
            type_=enum(*values, name="reference_answer_match_method"),
            existing_nullable=False,
        )


def upgrade() -> None:
    _rewrite_method(NEW_METHODS)


def downgrade() -> None:
    op.execute(
        "UPDATE reference_answers SET match_method = 'exact_title' "
        "WHERE match_method = 'numbered_order'"
    )
    _rewrite_method(OLD_METHODS)
