"""Чат «Поиск в интернете» вместо фоновой задачи поиска.

Сессии нового чата — режим `chat_mode.source_search`. Прежний поиск через плагин
OpenRouter жил задачей `ai_source_search`; он удалён, а его строки — непринятые
списки найденных ссылок — удаляются вместе с видом задачи: показать их больше негде.

Revision ID: 20260925_0061
Revises: 20260924_0060
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0061"
down_revision = "20260924_0060"
branch_labels = None
depends_on = None

OLD_CHAT_MODES = ("exam", "study", "program")
NEW_CHAT_MODES = (*OLD_CHAT_MODES, "source_search")

NEW_JOB_KINDS = (
    "parse",
    "typst_compile",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
    "ai_answer_sections",
    "ai_program_build",
    "coverage_research",
    "retrieval_index",
    "retrieval_model_install",
    "retrieval_exhaustive",
    "backup_create",
    "project_export",
    "project_import",
    "storage_verify",
    "storage_cleanup",
)
OLD_JOB_KINDS = (*NEW_JOB_KINDS, "ai_source_search")


def _replace_check(table: str, column: str, enum_name: str, values: tuple[str, ...]) -> None:
    """Пересоздать CHECK перечисления: старое ограничение ищется по тексту, как в 0060."""
    existing = [
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
        if constraint["name"] and f"{column} IN" in (constraint["sqltext"] or "")
    ]
    with op.batch_alter_table(table) as batch:
        for stale in existing:
            batch.drop_constraint(op.f(stale), type_="check")
        batch.alter_column(
            column,
            type_=sa.Enum(*values, name=enum_name, native_enum=False, create_constraint=False),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            op.f(f"ck_{table}_{enum_name}"), sa.column(column).in_(values)
        )


def upgrade() -> None:
    _replace_check("chat_sessions", "mode", "chat_mode", NEW_CHAT_MODES)
    op.execute(sa.text("DELETE FROM background_jobs WHERE kind = 'ai_source_search'"))
    _replace_check("background_jobs", "kind", "background_job_kind", NEW_JOB_KINDS)


def downgrade() -> None:
    _replace_check("background_jobs", "kind", "background_job_kind", OLD_JOB_KINDS)
    # Сессий поиска в старой схеме нет: они удаляются каскадом сообщений и запусков.
    op.execute(sa.text("DELETE FROM chat_sessions WHERE mode = 'source_search'"))
    _replace_check("chat_sessions", "mode", "chat_mode", OLD_CHAT_MODES)
