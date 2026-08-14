"""keep only models explicitly added to Tentex

Revision ID: 20260814_0016
Revises: 20260814_0015
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260814_0016"
down_revision: str | Sequence[str] | None = "20260814_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The previous UI saved every model returned by a provider. Those rows are a
    # disposable catalog snapshot, so keep only models the person touched.
    op.execute(
        text(
            """
            DELETE FROM ai_model_catalog AS model
            WHERE model.is_manually_added = 0
              AND model.favorite_order IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM ai_settings AS settings
                WHERE (
                  settings.default_text_provider_id = model.provider_id
                  AND settings.default_text_model_id = model.model_id
                ) OR (
                  settings.default_speech_provider_id = model.provider_id
                  AND settings.default_speech_model_id = model.model_id
                )
              )
              AND NOT EXISTS (
                SELECT 1 FROM ai_role_settings AS role
                WHERE role.provider_override_id = model.provider_id
                  AND role.model_override = model.model_id
              )
            """
        )
    )
    op.execute(text("UPDATE ai_model_catalog SET is_available = 1"))


def downgrade() -> None:
    # Removed catalog snapshots can always be fetched from the provider again.
    pass
