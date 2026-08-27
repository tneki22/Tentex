"""store exam time and procedure in goal passports

Revision ID: 20260825_0020
Revises: 20260815_0019
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0020"
down_revision: str | Sequence[str] | None = "20260815_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("goal_passports", sa.Column("exam_time", sa.Time(), nullable=True))
    op.add_column("goal_passports", sa.Column("exam_procedure", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("goal_passports") as batch:
        batch.drop_column("exam_procedure")
        batch.drop_column("exam_time")
