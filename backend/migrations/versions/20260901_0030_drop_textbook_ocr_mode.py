"""drop the textbook GPU OCR mode from parser mode enums

Revision ID: 20260901_0030
Revises: 20260831_0029
Create Date: 2026-09-01

Блок 2.5 плана резки: GPU-контур распознавания «Учебник» — отдельный сервис
и запись движка `textbook` в реестре — убран из кода. Здесь та же операция на
уровне базы: значение "textbook" пропадает из CHECK-ограничений режима
разбора у `materials.parser_mode`, `processing_tasks.parser_mode`,
`material_revisions.parser_mode` и `ocr_settings.default_mode`, и чистятся
засеянные строки `ocr_engine_configs` для удалённых движков (`textbook` — из
0022, `maximum`/`expert` никогда не сеялись, но на случай ручных правок в базе
чистим и их).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0030"
down_revision: str | Sequence[str] | None = "20260831_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.execute("DELETE FROM ocr_engine_configs WHERE mode IN ('textbook', 'maximum', 'expert')")

    with op.batch_alter_table("materials") as batch:
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", "textbook", name="parser_mode"),
            type_=enum("fast", name="parser_mode"),
            existing_nullable=True,
        )
    with op.batch_alter_table("processing_tasks") as batch:
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", "textbook", name="task_parser_mode"),
            type_=enum("fast", name="task_parser_mode"),
            existing_nullable=False,
        )
    with op.batch_alter_table("material_revisions") as batch:
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", "textbook", name="revision_parser_mode"),
            type_=enum("fast", name="revision_parser_mode"),
            existing_nullable=True,
        )
    with op.batch_alter_table("ocr_settings") as batch:
        batch.alter_column(
            "default_mode",
            existing_type=enum("fast", "textbook", name="ocr_default_mode"),
            type_=enum("fast", name="ocr_default_mode"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ocr_settings") as batch:
        batch.alter_column(
            "default_mode",
            existing_type=enum("fast", name="ocr_default_mode"),
            type_=enum("fast", "textbook", name="ocr_default_mode"),
            existing_nullable=False,
        )
    with op.batch_alter_table("material_revisions") as batch:
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", name="revision_parser_mode"),
            type_=enum("fast", "textbook", name="revision_parser_mode"),
            existing_nullable=True,
        )
    with op.batch_alter_table("processing_tasks") as batch:
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", name="task_parser_mode"),
            type_=enum("fast", "textbook", name="task_parser_mode"),
            existing_nullable=False,
        )
    with op.batch_alter_table("materials") as batch:
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", name="parser_mode"),
            type_=enum("fast", "textbook", name="parser_mode"),
            existing_nullable=True,
        )
    # Заводскую строку движка «Учебник» восстанавливаем тем же значением,
    # каким её поправила 0024 — 0022 засеяла её устаревшим model_id.
    op.execute(
        "INSERT INTO ocr_engine_configs "
        "(mode, enabled, model_id, device, language, executor, extra, updated_at) "
        "SELECT 'textbook', 1, 'PP-StructureV3 + PP-FormulaNet Plus M', 'gpu', NULL, "
        "'formulas', '{}', CURRENT_TIMESTAMP "
        "WHERE NOT EXISTS (SELECT 1 FROM ocr_engine_configs WHERE mode = 'textbook')"
    )
