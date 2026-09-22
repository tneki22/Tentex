"""Не поднимать исторические ошибки при добавлении корзины внимания.

Revision ID: 20260922_0056
Revises: 20260920_0055
"""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0056"
down_revision = "20260920_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Считать просмотренными ошибки, созданные до появления новой панели."""
    op.execute(
        sa.text(
            "UPDATE background_jobs "
            "SET reviewed_at = COALESCE(updated_at, created_at) "
            "WHERE state = 'failed' AND reviewed_at IS NULL"
        )
    )


def downgrade() -> None:
    """Не стирать отметки: после обновления они неотличимы от ручного удаления."""
