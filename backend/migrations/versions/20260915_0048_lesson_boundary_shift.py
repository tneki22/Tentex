"""lesson_source_refs.boundary_shifted

Итерация 2.2 вертикали «Уроки»: граница куска, не нашедшая пары в новой ревизии
материала, деградирует до границы страницы. Без флага такая граница неотличима от
исходной постраничной, и «Разрез сдвинут» показать нечем.

Revision ID: 20260915_0048
Revises: 20260914_0047
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0048"
down_revision: str | Sequence[str] | None = "20260914_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("lesson_source_refs") as batch_op:
        batch_op.add_column(
            sa.Column("boundary_shifted", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("lesson_source_refs") as batch_op:
        batch_op.drop_column("boundary_shifted")
