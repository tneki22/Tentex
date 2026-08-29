"""persist validated AI proposals for reopening

Revision ID: 20260829_0027
Revises: 20260829_0026
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0027"
down_revision: str | Sequence[str] | None = "20260829_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Локальная рабочая БД могла получить эту колонку из прежней незакоммиченной
    # ревизии с тем же id 0026. После объединения чат занял 0026, поэтому 0027
    # должна одновременно работать как обычная миграция для чистой установки и
    # как stamp-переход для уже обновлённой локальной схемы.
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("ai_runs")}
    if "response_payload" not in columns:
        op.add_column("ai_runs", sa.Column("response_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("ai_runs")}
    if "response_payload" in columns:
        op.drop_column("ai_runs", "response_payload")
