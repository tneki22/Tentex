"""Параметры модели на сессии чата и липкий выбор модели для новых чатов."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0054"
down_revision = "20260920_0053"
branch_labels = None
depends_on = None


def upgrade():
    # Параметры живут отдельной колонкой, а не внутри `model_override`: снимок
    # выбора модели читают валидация чата и судья, и подмешивать в него поля,
    # которые им не нужны, значит ломать их разбор.
    op.add_column("chat_sessions", sa.Column("model_parameters", sa.JSON(), nullable=True))
    # {"provider_id": "...", "model_id": "...", "parameters": {...}} — последний
    # выбор в композере. Засевается в каждый новый чат, чтобы не переключать заново.
    op.add_column("ai_settings", sa.Column("chat_model_preset", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("ai_settings", "chat_model_preset")
    op.drop_column("chat_sessions", "model_parameters")
