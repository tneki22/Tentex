"""audio input for already added speech-to-text models

Revision ID: 20260920_0051
Revises: 20260920_0050
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260920_0051"
down_revision: str | Sequence[str] | None = "20260920_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Groq и OpenAI не отдают модальности в /models, поэтому Whisper, добавленный
    # из поиска, лежит без «принимает аудио» и не виден в выборе модели для речи.
    # Новые модели дополняет `provider._infer_modalities`; здесь — уже сохранённые.
    op.execute(
        text(
            """
            UPDATE ai_model_catalog
            SET input_modalities = '["audio"]',
                output_modalities = CASE
                  WHEN json_array_length(output_modalities) = 0 THEN '["text"]'
                  ELSE output_modalities
                END
            WHERE json_array_length(input_modalities) = 0
              AND (lower(model_id) LIKE '%whisper%' OR lower(model_id) LIKE '%transcribe%')
            """
        )
    )


def downgrade() -> None:
    # Правка данных, а не схемы: прежнее «пусто» от ручной отметки не отличить.
    pass
