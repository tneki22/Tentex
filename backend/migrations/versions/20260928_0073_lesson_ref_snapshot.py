"""Снимок текста куска и отпечаток материала у ссылки урока.

Урок, перенесённый файлом `.tentex-lessons` в установку без его учебника, держит
кусок как снимок текста (`snapshot_md`), SHA-256 файла материала
(`material_sha256`) и якоря границ по тексту абзацев (`snapshot_anchors`): когда
тот же файл появится в проекте, ссылку можно связать заново, не пересобирая урок.

Revision ID: 20260928_0073
Revises: 20260928_0072
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0073"
down_revision = "20260928_0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет nullable-поля без перестройки SQLite-таблицы."""
    op.add_column("lesson_source_refs", sa.Column("snapshot_md", sa.Text(), nullable=True))
    op.add_column(
        "lesson_source_refs", sa.Column("material_sha256", sa.String(64), nullable=True)
    )
    op.add_column("lesson_source_refs", sa.Column("snapshot_anchors", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Удаляет снимок и отпечаток ссылки."""
    with op.batch_alter_table("lesson_source_refs") as batch:
        batch.drop_column("snapshot_anchors")
        batch.drop_column("material_sha256")
        batch.drop_column("snapshot_md")
