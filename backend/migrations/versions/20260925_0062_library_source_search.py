"""Самостоятельные сессии поиска Библиотеки без проекта.

Revision ID: 20260925_0062
Revises: 20260925_0061
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0062"
down_revision = "20260925_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("project_id", existing_type=sa.Uuid(), nullable=True)
        batch.create_check_constraint(
            "ck_chat_sessions_library_search_scope",
            "project_id IS NOT NULL OR mode = 'source_search'",
        )
    with op.batch_alter_table("chat_tool_runs") as batch:
        batch.alter_column("project_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM chat_sessions WHERE project_id IS NULL"))
    with op.batch_alter_table("chat_tool_runs") as batch:
        batch.alter_column("project_id", existing_type=sa.Uuid(), nullable=False)
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_constraint("ck_chat_sessions_library_search_scope", type_="check")
        batch.alter_column("project_id", existing_type=sa.Uuid(), nullable=False)
