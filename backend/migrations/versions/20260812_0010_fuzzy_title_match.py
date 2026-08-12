"""fuzzy and resolved title match methods

Заголовок раздела ответов может разойтись с формулировкой вопроса по написанию
(«о индексах» против «об индексах»). Такое совпадение ставится нечётким подбором
и обязано быть отличимо от точного, а указанное пользователем — от обоих.

Revision ID: 20260812_0010
Revises: 20260812_0009
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0010"
down_revision: str | Sequence[str] | None = "20260812_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_METHODS = ("manual", "exact_title")
NEW_METHODS = ("manual", "exact_title", "fuzzy_title", "resolved_title")


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _rewrite_method(values: tuple[str, ...]) -> None:
    # SQLite держит перечисление CHECK-ограничением: расширяется только пересборкой.
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
        "WHERE match_method IN ('fuzzy_title', 'resolved_title')"
    )
    _rewrite_method(OLD_METHODS)
