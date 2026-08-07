"""store project color as a bounded integer

Revision ID: 6c7ad9e40c82
Revises: 34158831e181
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6c7ad9e40c82"
down_revision: str | Sequence[str] | None = "34158831e181"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE projects
        SET color = CASE
            WHEN trim(color) IN ('1', '2', '3', '4', '5', '6', '7', '8')
                THEN CAST(trim(color) AS INTEGER)
            ELSE 1
        END
        WHERE color IS NOT NULL
        """
    )
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "color", existing_type=sa.String(), type_=sa.Integer(), existing_nullable=True
        )
        batch_op.create_check_constraint("ck_projects_color_range", "color BETWEEN 1 AND 8")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("ck_projects_color_range", type_="check")
        batch_op.alter_column(
            "color", existing_type=sa.Integer(), type_=sa.String(), existing_nullable=True
        )
