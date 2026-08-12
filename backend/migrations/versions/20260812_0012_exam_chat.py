"""exam chat sessions and messages

Revision ID: 20260812_0012
Revises: 20260812_0011
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0012"
down_revision: str | Sequence[str] | None = "20260812_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("section_scope_node_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "persona",
            enum("calm_teacher", "neutral_examiner", "strict_reviewer", name="examiner_persona"),
            nullable=False,
        ),
        sa.Column(
            "strictness",
            enum("soft", "normal", "strict", name="examiner_strictness"),
            nullable=False,
        ),
        sa.Column("draft_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_chat_sessions_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
            name=op.f("fk_chat_sessions_project_id_program_node_id_program_nodes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
    )
    op.create_index(
        "ix_chat_sessions_node_updated",
        "chat_sessions",
        ["project_id", "program_node_id", "updated_at"],
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "role", enum("user", "examiner", "system", name="chat_message_role"), nullable=False
        ),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "stream_state",
            enum("complete", "stopped", "failed", name="chat_stream_state"),
            nullable=False,
            server_default="complete",
        ),
        sa.Column(
            "payload_kind",
            enum(
                "none",
                "answer_form",
                "verdict",
                "task",
                "interactive",
                name="chat_payload_kind",
            ),
            nullable=False,
            server_default="none",
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("ai_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_chat_messages_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            ondelete="CASCADE",
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["ai_run_id"],
            ["ai_runs.id"],
            ondelete="SET NULL",
            name=op.f("fk_chat_messages_ai_run_id_ai_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint(
            "session_id", "sequence", name=op.f("uq_chat_messages_session_id_sequence")
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_node_updated", table_name="chat_sessions")
    op.drop_table("chat_sessions")
