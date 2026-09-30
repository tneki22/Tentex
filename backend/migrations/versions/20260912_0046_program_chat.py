"""program chat: project-scoped chat mode, assistant role, program diff payload

Часть 2 вертикали «Программа учебника» (TEXTBOOK_MODE.md §3): чат построения
программы с дифами. `chat_sessions.program_node_id` становится nullable —
такой чат привязан к проекту целиком, а не к одному узлу. Три CHECK-enum
получают новые значения: `chat_mode.program`, `chat_message_role.assistant`,
`chat_payload_kind.program_diff`; `background_jobs.kind` — `ai_program_build`.

Revision ID: 20260912_0046
Revises: 20260911_0045
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0046"
down_revision: str | Sequence[str] | None = "20260911_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CHAT_MODES = ("exam", "study")
NEW_CHAT_MODES = (*OLD_CHAT_MODES, "program")

OLD_MESSAGE_ROLES = ("user", "examiner", "system")
NEW_MESSAGE_ROLES = (*OLD_MESSAGE_ROLES, "assistant")

OLD_PAYLOAD_KINDS = ("none", "answer_form", "verdict", "task", "interactive", "tool_result")
NEW_PAYLOAD_KINDS = (*OLD_PAYLOAD_KINDS, "program_diff")

OLD_JOB_KINDS = (
    "parse",
    "typst_compile",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
    "ai_answer_sections",
)
NEW_JOB_KINDS = (*OLD_JOB_KINDS, "ai_program_build")


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    # Один op на вызов — см. пояснение в 20260829_0026: групповой batch с
    # несколькими enum-колонками теряет привязку CHECK → колонка в SQLite.

    # Чат построения программы привязан к проекту целиком, а не к одному
    # узлу program_nodes — составной FK (project_id, program_node_id) с NULL
    # просто не проверяется (SQLite MATCH SIMPLE), отдельной правки FK не нужно.
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("program_node_id", existing_type=sa.Uuid(), nullable=True)

    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column(
            "mode",
            existing_type=sa.String(),
            type_=enum(*NEW_CHAT_MODES, name="chat_mode"),
            existing_nullable=False,
            existing_server_default="exam",
        )

    with op.batch_alter_table("chat_messages") as batch:
        batch.alter_column(
            "role",
            existing_type=sa.String(),
            type_=enum(*NEW_MESSAGE_ROLES, name="chat_message_role"),
            existing_nullable=False,
        )

    with op.batch_alter_table("chat_messages") as batch:
        batch.alter_column(
            "payload_kind",
            existing_type=sa.String(),
            type_=enum(*NEW_PAYLOAD_KINDS, name="chat_payload_kind"),
            existing_nullable=False,
            existing_server_default="none",
        )

    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(),
            type_=enum(*NEW_JOB_KINDS, name="background_job_kind"),
            existing_nullable=False,
            existing_server_default="parse",
        )


def downgrade() -> None:
    # Даунгрейд — best-effort реклассификация, как и в 0026: строки со
    # значением, которого больше нет в перечислении, переносятся на ближайший
    # безопасный старый вариант, иначе CHECK новой (узкой) схемы их отбивает.
    op.execute(
        "UPDATE background_jobs SET kind = 'ai_grouping' WHERE kind = 'ai_program_build'"
    )
    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(),
            type_=enum(*OLD_JOB_KINDS, name="background_job_kind"),
            existing_nullable=False,
            existing_server_default="parse",
        )

    op.execute(
        "UPDATE chat_messages SET payload_kind = 'none' WHERE payload_kind = 'program_diff'"
    )
    with op.batch_alter_table("chat_messages") as batch:
        batch.alter_column(
            "payload_kind",
            existing_type=sa.String(),
            type_=enum(*OLD_PAYLOAD_KINDS, name="chat_payload_kind"),
            existing_nullable=False,
            existing_server_default="none",
        )

    op.execute(
        "UPDATE chat_messages SET role = 'examiner' WHERE role = 'assistant'"
    )
    with op.batch_alter_table("chat_messages") as batch:
        batch.alter_column(
            "role",
            existing_type=sa.String(),
            type_=enum(*OLD_MESSAGE_ROLES, name="chat_message_role"),
            existing_nullable=False,
        )

    # Чат построения программы не существует в старой схеме: его сессии
    # (program_node_id IS NULL) удаляются каскадом их сообщений/tool_runs
    # перед тем, как колонка снова станет NOT NULL.
    op.execute("DELETE FROM chat_sessions WHERE program_node_id IS NULL")
    op.execute(
        "UPDATE chat_sessions SET mode = 'exam' WHERE mode = 'program'"
    )
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column(
            "mode",
            existing_type=sa.String(),
            type_=enum(*OLD_CHAT_MODES, name="chat_mode"),
            existing_nullable=False,
            existing_server_default="exam",
        )
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("program_node_id", existing_type=sa.Uuid(), nullable=False)
