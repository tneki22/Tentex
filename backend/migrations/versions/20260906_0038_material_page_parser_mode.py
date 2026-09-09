"""material_pages: which recognition mode actually produced this page

Revision ID: 20260906_0038
Revises: 20260905_0037
Create Date: 2026-09-06

До сих пор «каким режимом распознана страница» читалось из
`material_revisions.parser_mode` — одного значения на всю версию. Частичный
запуск (например, «Переразобрать страницы, которые нужно проверить») ломает
это допущение: непереразобранные страницы копируются в новую версию как есть
(`worker._prepare_revision`), но версия целиком помечается режимом *новой*
задачи, хотя эти страницы распознавала прошлая модель.

`material_pages.parser_mode` хранит режим для конкретной страницы: NULL — у
страниц текстового слоя (`quality=native`, распознавание не требовалось),
иначе — тот режим, что её реально читал. Какой режим читал существующие
страницы построчно — не восстановить без повторного разбора, поэтому им
проставляется режим их же версии из `material_revisions` (то же значение,
что просмотрщик и так показывал раньше): старые версии не регрессируют,
а точность на уровне страницы появляется только у новых частичных запусков.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0038"
down_revision: str | Sequence[str] | None = "20260905_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("material_pages") as batch:
        batch.add_column(
            sa.Column(
                "parser_mode",
                sa.Enum("fast", "cloud", name="material_page_parser_mode", native_enum=False),
                nullable=True,
            )
        )
    op.execute(
        """
        UPDATE material_pages
        SET parser_mode = (
            SELECT mr.parser_mode
            FROM material_revisions mr
            WHERE mr.material_id = material_pages.material_id
              AND mr.revision = material_pages.revision
        )
        WHERE quality != 'native'
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("material_pages") as batch:
        batch.drop_column("parser_mode")
