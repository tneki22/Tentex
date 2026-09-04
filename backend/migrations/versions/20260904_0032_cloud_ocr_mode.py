"""add the cloud recognition mode and the vision model default

Revision ID: 20260904_0032
Revises: 20260901_0031
Create Date: 2026-09-04

Режим распознавания «Облако» перестаёт быть заглушкой. На уровне базы это две
вещи. Первая — значение `cloud` в перечислении режимов разбора: его хранят
`materials.parser_mode`, `background_jobs.parser_mode`,
`material_revisions.parser_mode` и `ocr_settings.default_mode`, и без
расширения CHECK-ограничений материал, разобранный облаком, не сохранить.

Вторая — модель по умолчанию для новой модальности `vision` в
`ai_settings`. Она заводится рядом с текстовой и речевой, а не в настройках
распознавания: выбор модели, ключ провайдера, лимиты и учёт стоимости живут в
шлюзе моделей, и раздваивать этот факт нельзя. Экран «Распознавание» пишет
именно сюда.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0032"
down_revision: str | Sequence[str] | None = "20260901_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Таблица, столбец, имя перечисления и допускает ли столбец NULL.
PARSER_MODE_COLUMNS = (
    ("materials", "parser_mode", "parser_mode", True),
    ("background_jobs", "parser_mode", "task_parser_mode", True),
    ("material_revisions", "parser_mode", "revision_parser_mode", True),
    ("ocr_settings", "default_mode", "ocr_default_mode", False),
)


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _retype(*, allowed: tuple[str, ...], previous: tuple[str, ...]) -> None:
    for table, column, name, nullable in PARSER_MODE_COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                column,
                existing_type=enum(*previous, name=name),
                type_=enum(*allowed, name=name),
                existing_nullable=nullable,
            )


def upgrade() -> None:
    _retype(allowed=("fast", "cloud"), previous=("fast",))
    with op.batch_alter_table("ai_settings") as batch:
        batch.add_column(sa.Column("default_vision_provider_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("default_vision_model_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_ai_settings_default_vision_provider_id_ai_provider_connections",
            "ai_provider_connections",
            ["default_vision_provider_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    # Материалы, разобранные облаком, под старое ограничение не пройдут:
    # переводим их на единственный оставшийся режим, как это делала 0030.
    for table, column, _, _ in PARSER_MODE_COLUMNS:
        op.execute(f"UPDATE {table} SET {column} = 'fast' WHERE {column} = 'cloud'")
    with op.batch_alter_table("ai_settings") as batch:
        batch.drop_constraint(
            "fk_ai_settings_default_vision_provider_id_ai_provider_connections",
            type_="foreignkey",
        )
        batch.drop_column("default_vision_model_id")
        batch.drop_column("default_vision_provider_id")
    _retype(allowed=("fast",), previous=("fast", "cloud"))
