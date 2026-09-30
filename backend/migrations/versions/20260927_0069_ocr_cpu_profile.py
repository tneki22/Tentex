"""Сохраняет профиль нагрузки локального OCR.

Revision ID: 20260927_0069
Revises: 20260927_0068
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0069"
down_revision = "20260927_0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Существующие установки получают сбалансированный профиль."""
    with op.batch_alter_table("ocr_settings") as batch:
        batch.add_column(
            sa.Column("cpu_profile", sa.String(16), nullable=False, server_default="balanced")
        )
        batch.create_check_constraint(
            "ck_ocr_settings_cpu_profile_known",
            "cpu_profile IN ('gentle', 'balanced', 'maximum')",
        )


def downgrade() -> None:
    """Удаляет профиль, сохраняя остальные настройки распознавания."""
    with op.batch_alter_table("ocr_settings") as batch:
        batch.drop_constraint("ck_ocr_settings_cpu_profile_known", type_="check")
        batch.drop_column("cpu_profile")
