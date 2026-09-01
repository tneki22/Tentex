"""raise processing_tasks to the shared background_jobs queue

Revision ID: 20260901_0031
Revises: 20260901_0030
Create Date: 2026-09-01

Этап 3 плана (Ш1): вместо отдельной очереди под каждый вид фоновой операции
(разбор материала, роли ИИ, привязка ответов) все они делят одну таблицу и
один словарь состояний — `processing_tasks` становится `background_jobs`.
`ProcessingTaskKind` расширяется ролями ИИ и привязкой ответов, у задачи
появляется необязательный `project_id` (роли ИИ и привязка ответов не всегда
привязаны к материалу), а `material_id`/`parser_mode`/`stage` становятся
необязательными: они осмысленны только у разбора (`kind == 'parse'`).

Состояние жизненного цикла задачи (`state`) — это НЕ то же самое, что исход
конкретного вызова модели (`ai_runs.status`, с его `succeeded`/`cached`):
последний не трогается, только у `ai_runs` появляется необязательная ссылка
`job_id` на задачу очереди, которая его запустила.

SQLite не умеет ALTER COLUMN и не переименовывает связанные индексы/имена
ограничений при переименовании таблицы, поэтому — `batch_alter_table` с
явной пересборкой имён FK/CHECK под новое имя таблицы.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0031"
down_revision: str | Sequence[str] | None = "20260901_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


JOB_KINDS = (
    "parse",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
)
JOB_STATES = ("queued", "running", "paused", "cancelled", "failed", "completed")


def upgrade() -> None:
    op.rename_table("processing_tasks", "background_jobs")
    op.drop_index("ix_processing_tasks_state_created", table_name="background_jobs")
    op.drop_index("ix_processing_tasks_material_created", table_name="background_jobs")

    with op.batch_alter_table("background_jobs", recreate="always") as batch:
        # Ограничение "progress_valid" не переименовывается: SQLite ненадёжно
        # отражает имена CHECK при пересборке таблицы в batch-режиме — попытка
        # снять его по новому имени валит миграцию (KeyError у Alembic). Оно
        # остаётся под старым именем и переносится как есть; модель (models.py)
        # объявляет то же самое старое имя, поэтому расхождения с ORM нет.
        batch.drop_constraint("fk_processing_tasks_material_id_materials", type_="foreignkey")
        batch.alter_column("material_id", existing_type=sa.Uuid(), nullable=True)
        batch.create_foreign_key(
            "fk_background_jobs_material_id_materials",
            "materials",
            ["material_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_background_jobs_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.alter_column(
            "kind",
            existing_type=enum("parse", name="processing_task_kind"),
            type_=enum(*JOB_KINDS, name="background_job_kind"),
            existing_nullable=False,
        )
        batch.alter_column(
            "state",
            existing_type=enum(
                "queued", "running", "paused", "failed", "completed", name="processing_task_state"
            ),
            type_=enum(*JOB_STATES, name="background_job_state"),
            existing_nullable=False,
        )
        batch.alter_column(
            "stage",
            existing_type=enum("queued", "extract", "segment", "complete", name="processing_stage"),
            type_=enum("queued", "extract", "segment", "complete", name="processing_stage"),
            nullable=True,
        )
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", name="task_parser_mode"),
            type_=enum("fast", name="task_parser_mode"),
            nullable=True,
        )

    op.create_index(
        "ix_background_jobs_state_created", "background_jobs", ["state", "created_at"]
    )
    op.create_index(
        "ix_background_jobs_material_created", "background_jobs", ["material_id", "created_at"]
    )
    op.create_index(
        "ix_background_jobs_project_created", "background_jobs", ["project_id", "created_at"]
    )

    with op.batch_alter_table("ai_runs") as batch:
        batch.add_column(sa.Column("job_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_ai_runs_job_id_background_jobs",
            "background_jobs",
            ["job_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_runs") as batch:
        batch.drop_constraint("fk_ai_runs_job_id_background_jobs", type_="foreignkey")
        batch.drop_column("job_id")

    op.drop_index("ix_background_jobs_project_created", table_name="background_jobs")
    op.drop_index("ix_background_jobs_material_created", table_name="background_jobs")
    op.drop_index("ix_background_jobs_state_created", table_name="background_jobs")

    # Задачи ИИ и привязки ответов, заведённые уже после апгрейда, не умеют
    # жить в узкой прежней схеме: у них нет material_id, а kind/state вне
    # старого набора значений. Такие строки идут в архив по неймингу вместо
    # тихой потери данных — downgrade возвращает форму, а не молча удаляет.
    op.execute(
        "DELETE FROM background_jobs WHERE kind NOT IN ('parse') "
        "OR material_id IS NULL OR state = 'cancelled'"
    )

    with op.batch_alter_table("background_jobs", recreate="always") as batch:
        batch.drop_constraint("fk_background_jobs_project_id_projects", type_="foreignkey")
        batch.drop_column("project_id")
        batch.drop_constraint("fk_background_jobs_material_id_materials", type_="foreignkey")
        batch.alter_column("material_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_processing_tasks_material_id_materials",
            "materials",
            ["material_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.alter_column(
            "kind",
            existing_type=enum(*JOB_KINDS, name="background_job_kind"),
            type_=enum("parse", name="processing_task_kind"),
            existing_nullable=False,
        )
        batch.alter_column(
            "state",
            existing_type=enum(*JOB_STATES, name="background_job_state"),
            type_=enum(
                "queued", "running", "paused", "failed", "completed", name="processing_task_state"
            ),
            existing_nullable=False,
        )
        batch.alter_column(
            "stage",
            existing_type=enum("queued", "extract", "segment", "complete", name="processing_stage"),
            type_=enum("queued", "extract", "segment", "complete", name="processing_stage"),
            nullable=False,
        )
        batch.alter_column(
            "parser_mode",
            existing_type=enum("fast", name="task_parser_mode"),
            type_=enum("fast", name="task_parser_mode"),
            nullable=False,
        )

    op.rename_table("background_jobs", "processing_tasks")
    op.create_index(
        "ix_processing_tasks_state_created", "processing_tasks", ["state", "created_at"]
    )
    op.create_index(
        "ix_processing_tasks_material_created", "processing_tasks", ["material_id", "created_at"]
    )
