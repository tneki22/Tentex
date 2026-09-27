"""Ход пользователя без дублей, предел контекста чата и снимок полного обзора.

Revision ID: 20260927_0070
Revises: 20260927_0069
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0070"
down_revision = "20260927_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Колонки добавляются по одной: батч SQLite терял бы CHECK у Enum (см. 0026)."""
    op.add_column("chat_messages", sa.Column("client_turn_id", sa.String(64), nullable=True))
    op.create_index(
        "uq_chat_messages_session_client_turn",
        "chat_messages",
        ["session_id", "client_turn_id"],
        unique=True,
    )
    op.add_column("chat_sessions", sa.Column("context_budget_tokens", sa.Integer(), nullable=True))
    op.add_column("retrieval_exhaustive_runs", sa.Column("settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Удаляет идентификатор хода, предел и снимок обзора; переписка остаётся."""
    op.drop_column("retrieval_exhaustive_runs", "settings")
    op.drop_column("chat_sessions", "context_budget_tokens")
    op.drop_index("uq_chat_messages_session_client_turn", table_name="chat_messages")
    op.drop_column("chat_messages", "client_turn_id")
