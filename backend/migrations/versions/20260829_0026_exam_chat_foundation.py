"""exam chat foundation: session controls, tool runs

Первая итерация ИИ-чата (AI-CHATS.md §21): режим сессии, override модели,
context flags, навык сообщения и общий журнал Tools.

Revision ID: 20260829_0026
Revises: 20260828_0025
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0026"
down_revision: str | Sequence[str] | None = "20260828_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_CONTEXT_FLAGS = (
    '{"profile": true, "reference": true, "fragments": true, '
    '"attempts": false, "section_memory": false}'
)

OLD_PAYLOAD_KINDS = ("none", "answer_form", "verdict", "task", "interactive")
NEW_PAYLOAD_KINDS = (*OLD_PAYLOAD_KINDS, "tool_result")


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    # Один op на вызов (не сгруппированы в один batch_alter_table): у SQLite
    # реконструкция таблицы при групповом drop_column вместе с колонкой,
    # несущей CHECK от Enum, теряет привязку constraint → колонка. env.py уже
    # включает render_as_batch=True глобально, поэтому каждый вызов ниже сам
    # по себе безопасно идёт через batch-пересборку — как в 0006/0018.
    op.add_column(
        "chat_sessions",
        sa.Column(
            "mode", enum("exam", "study", name="chat_mode"),
            nullable=False, server_default="exam",
        ),
    )
    op.add_column("chat_sessions", sa.Column("model_override", sa.JSON(), nullable=True))
    op.add_column(
        "chat_sessions",
        sa.Column("context_flags", sa.JSON(), nullable=False, server_default=DEFAULT_CONTEXT_FLAGS),
    )
    op.add_column("chat_messages", sa.Column("skill", sa.String(), nullable=True))
    with op.batch_alter_table("chat_messages") as batch:
        batch.alter_column(
            "payload_kind",
            existing_type=sa.String(),
            type_=enum(*NEW_PAYLOAD_KINDS, name="chat_payload_kind"),
            existing_nullable=False,
            existing_server_default="none",
        )
    op.create_table(
        "chat_tool_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("tool_key", sa.String(), nullable=False),
        sa.Column(
            "state",
            enum("queued", "running", "succeeded", "failed", name="chat_tool_run_state"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("tool_input", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE",
            name=op.f("fk_chat_tool_runs_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE",
            name=op.f("fk_chat_tool_runs_session_id_chat_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.id"], ondelete="SET NULL",
            name=op.f("fk_chat_tool_runs_message_id_chat_messages"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_tool_runs")),
        sa.UniqueConstraint("message_id", name=op.f("uq_chat_tool_runs_message_id")),
    )
    op.create_index(
        "ix_chat_tool_runs_session_created", "chat_tool_runs", ["session_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_tool_runs_session_created", table_name="chat_tool_runs")
    op.drop_table("chat_tool_runs")
    op.execute("UPDATE chat_messages SET payload_kind = 'none' WHERE payload_kind = 'tool_result'")
    with op.batch_alter_table("chat_messages") as batch:
        batch.alter_column(
            "payload_kind",
            existing_type=sa.String(),
            type_=enum(*OLD_PAYLOAD_KINDS, name="chat_payload_kind"),
            existing_nullable=False,
            existing_server_default="none",
        )
    op.drop_column("chat_messages", "skill")
    op.drop_column("chat_sessions", "context_flags")
    op.drop_column("chat_sessions", "model_override")
    op.drop_column("chat_sessions", "mode")
