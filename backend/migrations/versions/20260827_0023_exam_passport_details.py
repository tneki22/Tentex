"""store exam time and procedure in goal passports

Revision ID: 20260827_0023
Revises: 20260825_0022
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0023"
down_revision: str | Sequence[str] | None = "20260825_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("goal_passports", sa.Column("exam_time", sa.Time(), nullable=True))
    op.add_column("goal_passports", sa.Column("exam_procedure", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("goal_passports") as batch:
        batch.drop_column("exam_procedure")
        batch.drop_column("exam_time")
