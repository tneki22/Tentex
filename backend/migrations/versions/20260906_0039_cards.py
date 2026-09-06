"""common activities, cards and resumable card sessions

Revision ID: 20260906_0039
Revises: 20260906_0038
Create Date: 2026-09-06
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0039"
down_revision: str | Sequence[str] | None = "20260906_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    """Create the SQLite check-backed enums used by runtime models."""
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _activity_id(project_id: object, node_id: object) -> str:
    """Stable ids make the backfill safe if a copied database is retried."""
    return uuid5(NAMESPACE_URL, f"tentex:free-answer:{project_id}:{node_id}").hex


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=True),
        sa.Column("kind", enum("free_answer", "card", name="activity_kind"), nullable=False),
        sa.Column("evidence_strength", sa.Float(), nullable=False, server_default="1"),
        sa.Column(
            "origin",
            enum("manual", "fragment", "exam_chat", name="activity_origin"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "evidence_strength >= 0 AND evidence_strength <= 1",
            name=op.f("ck_activities_strength_range"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_activities_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            ondelete="CASCADE",
            name=op.f("fk_activities_project_id_program_nodes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activities")),
    )
    op.create_index(
        "ix_activities_project_node",
        "activities",
        ["project_id", "program_node_id"],
    )
    op.create_index(
        "uq_activities_free_answer_node",
        "activities",
        ["project_id", "program_node_id"],
        unique=True,
        sqlite_where=sa.text("kind = 'free_answer'"),
    )

    with op.batch_alter_table("attempts") as batch:
        batch.add_column(sa.Column("activity_id", sa.Uuid(), nullable=True))

    bind = op.get_bind()
    metadata = sa.MetaData()
    attempts = sa.Table("attempts", metadata, autoload_with=bind)
    activities = sa.Table("activities", metadata, autoload_with=bind)
    pairs = bind.execute(
        sa.select(
            attempts.c.project_id,
            attempts.c.program_node_id,
            sa.func.min(attempts.c.created_at).label("created_at"),
        ).group_by(attempts.c.project_id, attempts.c.program_node_id)
    ).mappings()
    for row in pairs:
        activity_id = _activity_id(row["project_id"], row["program_node_id"])
        bind.execute(
            activities.insert()
            .prefix_with("OR IGNORE")
            .values(
                id=activity_id,
                project_id=row["project_id"],
                program_node_id=row["program_node_id"],
                kind="free_answer",
                evidence_strength=1.0,
                origin="exam_chat",
                created_at=row["created_at"],
            )
        )
        bind.execute(
            attempts.update()
            .where(
                attempts.c.project_id == row["project_id"],
                attempts.c.program_node_id == row["program_node_id"],
            )
            .values(activity_id=activity_id)
        )

    with op.batch_alter_table("attempts", recreate="always") as batch:
        batch.drop_constraint(
            "fk_attempts_project_id_program_node_id_program_nodes", type_="foreignkey"
        )
        batch.drop_index("ix_attempts_node_created")
        batch.alter_column("activity_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("text", existing_type=sa.Text(), nullable=True)
        batch.alter_column("persona", existing_type=sa.String(), nullable=True)
        batch.alter_column("strictness", existing_type=sa.String(), nullable=True)
        batch.create_foreign_key(
            op.f("fk_attempts_activity_id_activities"),
            "activities",
            ["activity_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_attempts_activity_created", ["activity_id", "created_at"])
        batch.drop_column("program_node_id")

    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column(
            "source_kind",
            enum("none", "fragment", "reference", name="card_source_kind"),
            nullable=False,
        ),
        sa.Column("source_fragment_id", sa.Uuid(), nullable=True),
        sa.Column("source_reference_revision", sa.Integer(), nullable=True),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("state", enum("active", "suspended", name="card_state"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_fragment_id"], ["material_fragments.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id"),
    )
    op.create_index("ix_cards_project_state", "cards", ["project_id", "state", "deleted_at"])
    op.create_index("ix_cards_source_fragment", "cards", ["source_fragment_id"])

    op.create_table(
        "card_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope",
            enum("today", "hard", "selected", "all", name="card_session_scope"),
            nullable=False,
        ),
        sa.Column("selected_unit_ids", sa.JSON(), nullable=False),
        sa.Column("pace", enum("calm", "fast", name="card_session_pace"), nullable=False),
        sa.Column("limit_minutes", sa.Integer(), nullable=True),
        sa.Column("queue", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("active_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            enum("active", "completed", "cancelled", name="card_session_state"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_card_sessions_active_project",
        "card_sessions",
        ["project_id"],
        unique=True,
        sqlite_where=sa.text("state = 'active'"),
    )
    with op.batch_alter_table("grades") as batch:
        batch.add_column(sa.Column("confidence", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "confidence_range", "confidence IS NULL OR confidence BETWEEN 1 AND 4"
        )


def downgrade() -> None:
    with op.batch_alter_table("grades") as batch:
        batch.drop_constraint(op.f("ck_grades_confidence_range"), type_="check")
        batch.drop_column("confidence")
    op.drop_index("uq_card_sessions_active_project", table_name="card_sessions")
    op.drop_table("card_sessions")
    op.drop_index("ix_cards_source_fragment", table_name="cards")
    op.drop_index("ix_cards_project_state", table_name="cards")
    op.drop_table("cards")
    with op.batch_alter_table("attempts", recreate="always") as batch:
        batch.add_column(sa.Column("program_node_id", sa.Uuid(), nullable=True))
        batch.drop_index("ix_attempts_activity_created")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE attempts SET program_node_id = "
            "(SELECT program_node_id FROM activities WHERE activities.id = attempts.activity_id)"
        )
    )
    with op.batch_alter_table("attempts", recreate="always") as batch:
        batch.alter_column("program_node_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_constraint(op.f("fk_attempts_activity_id_activities"), type_="foreignkey")
        batch.create_foreign_key(
            op.f("fk_attempts_project_id_program_node_id_program_nodes"),
            "program_nodes",
            ["project_id", "program_node_id"],
            ["project_id", "id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_attempts_node_created",
            ["project_id", "program_node_id", "created_at"],
        )
        batch.alter_column("text", existing_type=sa.Text(), nullable=False)
        batch.alter_column("persona", existing_type=sa.String(), nullable=False)
        batch.alter_column("strictness", existing_type=sa.String(), nullable=False)
        batch.drop_column("activity_id")
    op.drop_index("uq_activities_free_answer_node", table_name="activities")
    op.drop_index("ix_activities_project_node", table_name="activities")
    op.drop_table("activities")
