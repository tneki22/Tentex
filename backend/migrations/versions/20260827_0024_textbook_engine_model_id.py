"""correct stale seeded textbook engine model id

Revision ID: 20260827_0024
Revises: 20260827_0023
Create Date: 2026-08-27

Миграция 0022 засеяла движок «Учебник» строкой model_id "PaddleOCR-VL-1.6-0.9B",
хотя сервис давно поднимает связку PP-StructureV3 + PP-FormulaNet. Значение
пользователю не показывается, но хранить в базе неправдивое имя незачем —
приводим его и `executor` к текущим константам `app.ocr.engines`. Правим только
нетронутую заводскую строку: если пользователь уже задал что-то своё, не трогаем.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_0024"
down_revision: str | Sequence[str] | None = "20260827_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_MODEL_ID = "PP-StructureV3 + PP-FormulaNet Plus M"
NEW_EXECUTOR = "formulas"
OLD_MODEL_ID = "PaddleOCR-VL-1.6-0.9B"
OLD_EXECUTOR = "auto"


def upgrade() -> None:
    op.execute(
        "UPDATE ocr_engine_configs "
        f"SET model_id = '{NEW_MODEL_ID}', executor = '{NEW_EXECUTOR}' "
        f"WHERE mode = 'textbook' AND model_id = '{OLD_MODEL_ID}'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ocr_engine_configs "
        f"SET model_id = '{OLD_MODEL_ID}', executor = '{OLD_EXECUTOR}' "
        f"WHERE mode = 'textbook' AND model_id = '{NEW_MODEL_ID}'"
    )
