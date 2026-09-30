"""ИИ-вертикаль Уроков: сборка, свёрнутый материал, опорные S-ID и задания урока.

`lessons.build_meta` помнит, как собран модельный урок; `lesson_blocks.collapsed`
сворачивает кусок материала под пояснением; `lesson_source_refs.citation_label`
связывает `[S3]` в тексте пояснения с его опорой. Задания урока — Активности
`study_task` со своей строкой в `study_tasks`. Новый вид фоновой задачи
`ai_lesson` и происхождение Активности `lesson` расширяют CHECK перечислений.

Revision ID: 20260928_0071
Revises: 20260927_0070
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0071"
down_revision = "20260927_0070"
branch_labels = None
depends_on = None

OLD_JOB_KINDS = (
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
    "image_descriptions",
)
NEW_JOB_KINDS = (*OLD_JOB_KINDS, "ai_lesson")

OLD_ACTIVITY_KINDS = ("free_answer", "card")
NEW_ACTIVITY_KINDS = (*OLD_ACTIVITY_KINDS, "study_task")

OLD_ACTIVITY_ORIGINS = ("manual", "fragment", "exam_chat")
NEW_ACTIVITY_ORIGINS = (*OLD_ACTIVITY_ORIGINS, "lesson")

TASK_FORMS = (
    "single_choice",
    "multiple_choice",
    "fill_blanks",
    "numeric",
    "ordering",
    "matching",
    "open_answer",
)


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _replace_check(table: str, column: str, enum_name: str, values: tuple[str, ...]) -> None:
    """Пересоздать CHECK перечисления: старое ограничение ищется по тексту, как в 0067."""
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
    """Колонки добавляются по одной: батч SQLite терял бы CHECK у Enum (см. 0026)."""
    op.add_column("lessons", sa.Column("build_meta", sa.JSON(), nullable=True))
    op.add_column(
        "lesson_blocks",
        sa.Column("collapsed", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "lesson_source_refs", sa.Column("citation_label", sa.String(16), nullable=True)
    )
    _replace_check("background_jobs", "kind", "background_job_kind", NEW_JOB_KINDS)
    _replace_check("activities", "kind", "activity_kind", NEW_ACTIVITY_KINDS)
    _replace_check("activities", "origin", "activity_origin", NEW_ACTIVITY_ORIGINS)
    op.create_table(
        "study_tasks",
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column("form", enum(*TASK_FORMS, name="study_task_form"), nullable=False),
        sa.Column("prompt_md", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("answer_key", sa.JSON(), nullable=False),
        sa.Column("reference_md", sa.Text(), nullable=True),
        sa.Column("explanation_md", sa.Text(), nullable=True),
        sa.Column("hint_md", sa.Text(), nullable=True),
        sa.Column(
            "difficulty",
            enum("remember", "understand", "apply", name="study_task_difficulty"),
            nullable=False,
        ),
        sa.Column(
            "basis",
            enum("sources", "sources_and_model", "model_only", name="study_task_basis"),
            nullable=False,
        ),
        sa.Column("supporting_fragment_ids", sa.JSON(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("ai_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            ondelete="CASCADE",
            name=op.f("fk_study_tasks_activity_id_activities"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_study_tasks_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            ondelete="SET NULL",
            name=op.f("fk_study_tasks_lesson_id_lessons"),
        ),
        sa.ForeignKeyConstraint(
            ["ai_run_id"],
            ["ai_runs.id"],
            ondelete="SET NULL",
            name=op.f("fk_study_tasks_ai_run_id_ai_runs"),
        ),
        sa.PrimaryKeyConstraint("activity_id", name=op.f("pk_study_tasks")),
    )
    op.create_index("ix_study_tasks_lesson", "study_tasks", ["lesson_id"])
    op.create_index("ix_study_tasks_project", "study_tasks", ["project_id"])


def downgrade() -> None:
    """Задания урока уходят вместе с их Активностями и попытками; уроки остаются."""
    op.drop_index("ix_study_tasks_project", table_name="study_tasks")
    op.drop_index("ix_study_tasks_lesson", table_name="study_tasks")
    op.drop_table("study_tasks")
    # Внешние ключи на время миграции выключены (`env.py`), поэтому каскады
    # от Активностей к попыткам и оценкам проходятся здесь явно.
    lesson_activities = "SELECT id FROM activities WHERE kind = 'study_task' OR origin = 'lesson'"
    lesson_attempts = f"SELECT id FROM attempts WHERE activity_id IN ({lesson_activities})"
    for statement in (
        f"DELETE FROM grades WHERE attempt_id IN ({lesson_attempts})",
        f"DELETE FROM preparation_qualities WHERE attempt_id IN ({lesson_attempts})",
        f"UPDATE chat_messages SET attempt_id = NULL WHERE attempt_id IN ({lesson_attempts})",
        "UPDATE chat_messages SET grade_attempt_id = NULL "
        f"WHERE grade_attempt_id IN ({lesson_attempts})",
        f"DELETE FROM attempts WHERE activity_id IN ({lesson_activities})",
        f"UPDATE lesson_blocks SET activity_id = NULL WHERE activity_id IN ({lesson_activities})",
        "DELETE FROM activities WHERE kind = 'study_task' OR origin = 'lesson'",
    ):
        op.execute(sa.text(statement))
    op.execute(sa.text("DELETE FROM background_jobs WHERE kind = 'ai_lesson'"))
    _replace_check("activities", "origin", "activity_origin", OLD_ACTIVITY_ORIGINS)
    _replace_check("activities", "kind", "activity_kind", OLD_ACTIVITY_KINDS)
    _replace_check("background_jobs", "kind", "background_job_kind", OLD_JOB_KINDS)
    op.drop_column("lesson_source_refs", "citation_label")
    op.drop_column("lesson_blocks", "collapsed")
    op.drop_column("lessons", "build_meta")
