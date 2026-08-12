"""answers_file binding mechanism

Файл эталонных ответов привязывается к вопросам сам, по совпадению заголовка
раздела с формулировкой вопроса. Это не ручная привязка и не проход 2, поэтому
у механизма появляется собственное значение.

Revision ID: 20260812_0008
Revises: 20260811_0007
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0008"
down_revision: str | Sequence[str] | None = "20260811_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_MECHANISMS = ("manual", "search", "pass_two")
NEW_MECHANISMS = ("manual", "search", "answers_file", "pass_two")


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _rewrite_mechanism(values: tuple[str, ...]) -> None:
    # SQLite хранит перечисление как CHECK-ограничение: расширить его можно
    # только пересборкой таблицы, поэтому batch_alter_table.
    with op.batch_alter_table("bindings") as batch:
        batch.alter_column(
            "mechanism",
            existing_type=sa.String(),
            type_=enum(*values, name="binding_mechanism"),
            existing_nullable=False,
        )


def upgrade() -> None:
    _rewrite_mechanism(NEW_MECHANISMS)


def downgrade() -> None:
    op.execute("UPDATE bindings SET mechanism = 'manual' WHERE mechanism = 'answers_file'")
    _rewrite_mechanism(OLD_MECHANISMS)
