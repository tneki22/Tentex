"""add ai_answer_sections job kind and ai_section match method

Revision ID: 20260907_0040
Revises: 20260906_0039
Create Date: 2026-09-07

Срез F (разметка файла эталонных ответов моделью): фоновая задача роли
`exam_answer_sections` встаёт в общую очередь, а применённый план помечает
привязку новым методом сопоставления — отдельным от `numbered_order` и
`fuzzy_title`, потому что границу указала модель по скелету документа, а не
локальное сравнение строк.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0040"
down_revision: str | Sequence[str] | None = "20260906_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = (
    "parse",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
)
NEW_JOB_KINDS = (*OLD_JOB_KINDS, "ai_answer_sections")

OLD_MATCH_METHODS = (
    "manual",
    "exact_title",
    "fuzzy_title",
    "resolved_title",
    "numbered_order",
)
NEW_MATCH_METHODS = (*OLD_MATCH_METHODS, "ai_section")


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column(
            "kind",
            existing_type=enum(*OLD_JOB_KINDS, name="background_job_kind"),
            type_=enum(*NEW_JOB_KINDS, name="background_job_kind"),
            existing_nullable=False,
        )
    with op.batch_alter_table("reference_answers") as batch:
        batch.alter_column(
            "match_method",
            existing_type=enum(*OLD_MATCH_METHODS, name="reference_answer_match_method"),
            type_=enum(*NEW_MATCH_METHODS, name="reference_answer_match_method"),
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute(
        "UPDATE reference_answers SET match_method = 'fuzzy_title' "
        "WHERE match_method = 'ai_section'"
    )
    with op.batch_alter_table("reference_answers") as batch:
        batch.alter_column(
            "match_method",
            existing_type=enum(*NEW_MATCH_METHODS, name="reference_answer_match_method"),
            type_=enum(*OLD_MATCH_METHODS, name="reference_answer_match_method"),
            existing_nullable=False,
        )
    op.execute("DELETE FROM background_jobs WHERE kind = 'ai_answer_sections'")
    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column(
            "kind",
            existing_type=enum(*NEW_JOB_KINDS, name="background_job_kind"),
            type_=enum(*OLD_JOB_KINDS, name="background_job_kind"),
            existing_nullable=False,
        )
