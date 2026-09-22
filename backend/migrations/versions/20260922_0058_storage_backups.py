"""Хранилище, переносимые копии и пакеты проектов.

Revision ID: 20260922_0058
Revises: 20260922_0056
"""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0058"
down_revision = "20260922_0057"
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
)
NEW_JOB_KINDS = (
    *OLD_JOB_KINDS,
    "backup_create",
    "project_export",
    "project_import",
    "storage_verify",
    "storage_cleanup",
)


def _replace_job_kind_check(values: tuple[str, ...]) -> None:
    existing = [
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("background_jobs")
        if constraint["name"] and "kind IN" in (constraint["sqltext"] or "")
    ]
    with op.batch_alter_table("background_jobs") as batch:
        for stale in existing:
            batch.drop_constraint(op.f(stale), type_="check")
        batch.alter_column(
            "kind",
            type_=sa.Enum(
                *values,
                name="background_job_kind",
                native_enum=False,
                create_constraint=False,
            ),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            op.f("ck_background_jobs_background_job_kind"), sa.column("kind").in_(values)
        )


def upgrade() -> None:
    """Добавить политику хранения и реестры управляемых архивов."""
    _replace_job_kind_check(NEW_JOB_KINDS)
    op.create_table(
        "storage_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("automatic_enabled", sa.Boolean(), nullable=False),
        sa.Column("daily_time", sa.String(length=5), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("backup_directory", sa.String(), nullable=True),
        sa.Column("last_automatic_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_storage_settings_singleton"),
        sa.CheckConstraint(
            "retention_days BETWEEN 1 AND 365",
            name="ck_storage_settings_retention_days_range",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_settings")),
    )
    op.create_table(
        "backup_archives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=11), nullable=False),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["background_jobs.id"],
            name=op.f("fk_backup_archives_job_id_background_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_archives")),
    )
    op.create_index("ix_backup_archives_created", "backup_archives", ["created_at"])
    op.create_table(
        "transfer_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=7), nullable=False),
        sa.Column("profile", sa.String(length=8), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("imported_project_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["background_jobs.id"],
            name=op.f("fk_transfer_artifacts_job_id_background_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_transfer_artifacts_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transfer_artifacts")),
    )
    op.create_index("ix_transfer_artifacts_expires", "transfer_artifacts", ["expires_at"])
    op.create_index("ix_transfer_artifacts_package_id", "transfer_artifacts", ["package_id"])
    op.execute(
        sa.text(
            "INSERT INTO storage_settings "
            "(id, automatic_enabled, daily_time, retention_days, updated_at) "
            "VALUES (1, 0, '03:00', 7, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    """Удалить только реестры нового домена, не затрагивая файлы архивов."""
    op.drop_index("ix_transfer_artifacts_package_id", table_name="transfer_artifacts")
    op.drop_index("ix_transfer_artifacts_expires", table_name="transfer_artifacts")
    op.drop_table("transfer_artifacts")
    op.drop_index("ix_backup_archives_created", table_name="backup_archives")
    op.drop_table("backup_archives")
    op.drop_table("storage_settings")
    op.execute(
        sa.text(
            "DELETE FROM background_jobs WHERE kind IN "
            "('backup_create', 'project_export', 'project_import', "
            "'storage_verify', 'storage_cleanup')"
        )
    )
    _replace_job_kind_check(OLD_JOB_KINDS)
