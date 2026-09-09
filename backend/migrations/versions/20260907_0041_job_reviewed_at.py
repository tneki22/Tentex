"""mark background jobs whose result still waits for the user

Revision ID: 20260907_0041
Revises: 20260907_0040
Create Date: 2026-09-07

Задача с предложением модели не заканчивается тем, что модель замолчала: пока
пользователь не принял или не убрал результат, работа не доведена до конца. До
этой правки такая задача просто исчезала из списка (панель показывает только
активные), и вернуться к готовому плану было неоткуда.

`reviewed_at` — отметка «разобрано». Пусто у всего, что применяется само
(`parse`, `link_answers`) и никогда в корзину не попадает; у видов из
`background.registry.REVIEW_REQUIRED_KINDS` пусто ровно до тех пор, пока
результат ждёт человека.

Уже завершённые задачи помечаются разобранными прямо в миграции: их результат
посчитан по старому состоянию файла или программы, и поднимать его сейчас как
«ждёт проверки» значило бы предлагать применить заведомо устаревший план.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0041"
down_revision: str | Sequence[str] | None = "20260907_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE background_jobs SET reviewed_at = completed_at WHERE state = 'completed'"
    )


def downgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_column("reviewed_at")
