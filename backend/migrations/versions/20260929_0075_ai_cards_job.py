"""Фоновая генерация карточек расширяет допустимые виды задач.

Revision ID: 20260929_0075
Revises: 20260928_0074
"""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0075"
down_revision = "20260928_0074"
branch_labels = None
depends_on = None

OLD_JOB_KINDS = (
    "parse", "typst_compile", "ai_grouping", "ai_import_repair",
    "ai_preparation", "ai_cleanup", "link_answers", "ai_answer_sections",
    "ai_program_build", "coverage_research", "retrieval_index",
    "retrieval_model_install", "retrieval_exhaustive", "backup_create",
    "project_export", "project_import", "storage_verify", "storage_cleanup",
    "image_descriptions", "ai_lesson",
)
NEW_JOB_KINDS = (*OLD_JOB_KINDS, "ai_cards")


def _replace_job_kinds(values: tuple[str, ...]) -> None:
    """Заменить SQLite CHECK вида задачи, сохранив данные таблицы."""
    existing = [
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("background_jobs")
        if constraint["name"] and "kind IN" in (constraint["sqltext"] or "")
    ]
    with op.batch_alter_table("background_jobs") as batch:
        for name in existing:
            batch.drop_constraint(op.f(name), type_="check")
        batch.alter_column(
            "kind",
            type_=sa.Enum(
                *values, name="background_job_kind",
                native_enum=False, create_constraint=False,
            ),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            op.f("ck_background_jobs_background_job_kind"),
            sa.column("kind").in_(values),
        )


def upgrade() -> None:
    """Разрешить задачи предложений карточек."""
    _replace_job_kinds(NEW_JOB_KINDS)


def downgrade() -> None:
    """Вернуть прежний перечень после удаления задач нового вида."""
    op.execute(sa.text("DELETE FROM background_jobs WHERE kind = 'ai_cards'"))
    _replace_job_kinds(OLD_JOB_KINDS)
