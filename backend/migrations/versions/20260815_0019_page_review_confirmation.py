"""store OCR page review confirmations

Revision ID: 20260815_0019
Revises: 20260814_0018
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0019"
down_revision: str | Sequence[str] | None = "20260814_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("material_pages", sa.Column("reviewed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("material_pages") as batch:
        batch.drop_column("reviewed_at")
