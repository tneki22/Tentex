"""lessons: lessons, lesson_topics, lesson_blocks, lesson_source_refs

Этап 1 вертикали «Уроки» (docs/superpowers/plans/2026-09-14-lessons-vertical.md §3.5):
четыре таблицы заводятся сразу целиком, чтобы этапы 2–3 обошлись без миграций.
`binding_mechanism` получает `lesson` и `outline` в конце перечисления — порядок
в CHECK совпадает с объявлением в модели (см. 20260909_0044).

Revision ID: 20260914_0047
Revises: 20260912_0046
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0047"
down_revision: str | Sequence[str] | None = "20260912_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_MECHANISMS = ("manual", "search", "answers_file", "pass_two")
NEW_MECHANISMS = (*OLD_MECHANISMS, "lesson", "outline")


def _rewrite_mechanism(values: tuple[str, ...]) -> None:
    with op.batch_alter_table("bindings") as batch:
        batch.alter_column(
            "mechanism",
            existing_type=sa.String(),
            type_=sa.Enum(
                *values, name="binding_mechanism", native_enum=False, create_constraint=True
            ),
            existing_nullable=False,
        )


def upgrade() -> None:
    _rewrite_mechanism(NEW_MECHANISMS)
    op.create_table(
        "lessons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "ready",
                "archived",
                name="lesson_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_block_id", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name=op.f("ck_lessons_duration_nonnegative"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_lessons_revision_positive")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_lessons_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lessons")),
    )
    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.create_index("ix_lessons_project", ["project_id"], unique=False)

    op.create_table(
        "lesson_topics",
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("program_node_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("topic_title_snapshot", sa.String(), nullable=False),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_lesson_topics_sort_order_nonnegative")),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_lesson_topics_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "program_node_id"],
            ["program_nodes.project_id", "program_nodes.id"],
            name=op.f("fk_lesson_topics_project_id_program_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("lesson_id", "program_node_id", name=op.f("pk_lesson_topics")),
    )
    with op.batch_alter_table("lesson_topics", schema=None) as batch_op:
        batch_op.create_index(
            "ix_lesson_topics_project_node", ["project_id", "program_node_id"], unique=False
        )

    op.create_table(
        "lesson_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "source",
                "note",
                "media",
                "activity",
                name="lesson_block_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "variant",
            sa.Enum(
                "text",
                "heading",
                "explanation",
                "important",
                "example",
                "definition",
                "warning",
                name="lesson_note_variant",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("body_md", sa.Text(), nullable=True),
        sa.Column(
            "origin",
            sa.Enum(
                "manual",
                "outline",
                "model",
                "mixed",
                name="lesson_block_origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "basis",
            sa.Enum(
                "sources",
                "sources_and_model",
                "model_only",
                name="lesson_basis",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("ai_run_id", sa.Uuid(), nullable=True),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column("media_path", sa.String(), nullable=True),
        sa.Column("bound_program_node_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_lesson_blocks_sort_order_nonnegative")),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name=op.f("fk_lesson_blocks_activity_id_activities"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ai_run_id"],
            ["ai_runs.id"],
            name=op.f("fk_lesson_blocks_ai_run_id_ai_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_lesson_blocks_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_blocks")),
    )
    with op.batch_alter_table("lesson_blocks", schema=None) as batch_op:
        batch_op.create_index("ix_lesson_blocks_activity", ["activity_id"], unique=False)
        batch_op.create_index("ix_lesson_blocks_ai_run", ["ai_run_id"], unique=False)
        batch_op.create_index(
            "ix_lesson_blocks_lesson_order", ["lesson_id", "sort_order"], unique=False
        )

    op.create_table(
        "lesson_source_refs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "content",
                "support",
                name="lesson_ref_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("material_id", sa.Uuid(), nullable=True),
        sa.Column("source_name_snapshot", sa.String(), nullable=False),
        sa.Column("material_revision", sa.Integer(), nullable=True),
        sa.Column("page_from", sa.Integer(), nullable=False),
        sa.Column("page_to", sa.Integer(), nullable=False),
        sa.Column("from_fragment_id", sa.Uuid(), nullable=True),
        sa.Column("to_fragment_id", sa.Uuid(), nullable=True),
        sa.Column("region_bbox", sa.JSON(), nullable=True),
        sa.Column("always_pages", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "page_from > 0 AND page_to >= page_from",
            name=op.f("ck_lesson_source_refs_page_range_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["lesson_blocks.id"],
            name=op.f("fk_lesson_source_refs_block_id_lesson_blocks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_fragment_id"],
            ["material_fragments.id"],
            name=op.f("fk_lesson_source_refs_from_fragment_id_material_fragments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            name=op.f("fk_lesson_source_refs_material_id_materials"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_fragment_id"],
            ["material_fragments.id"],
            name=op.f("fk_lesson_source_refs_to_fragment_id_material_fragments"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_source_refs")),
    )
    with op.batch_alter_table("lesson_source_refs", schema=None) as batch_op:
        batch_op.create_index("ix_lesson_source_refs_block", ["block_id"], unique=False)
        batch_op.create_index(
            "ix_lesson_source_refs_from_fragment", ["from_fragment_id"], unique=False
        )
        batch_op.create_index("ix_lesson_source_refs_material", ["material_id"], unique=False)
        batch_op.create_index("ix_lesson_source_refs_to_fragment", ["to_fragment_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("lesson_source_refs", schema=None) as batch_op:
        batch_op.drop_index("ix_lesson_source_refs_to_fragment")
        batch_op.drop_index("ix_lesson_source_refs_material")
        batch_op.drop_index("ix_lesson_source_refs_from_fragment")
        batch_op.drop_index("ix_lesson_source_refs_block")

    op.drop_table("lesson_source_refs")
    with op.batch_alter_table("lesson_blocks", schema=None) as batch_op:
        batch_op.drop_index("ix_lesson_blocks_lesson_order")
        batch_op.drop_index("ix_lesson_blocks_ai_run")
        batch_op.drop_index("ix_lesson_blocks_activity")

    op.drop_table("lesson_blocks")
    with op.batch_alter_table("lesson_topics", schema=None) as batch_op:
        batch_op.drop_index("ix_lesson_topics_project_node")

    op.drop_table("lesson_topics")
    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.drop_index("ix_lessons_project")

    op.drop_table("lessons")
    op.execute("UPDATE bindings SET mechanism = 'manual' WHERE mechanism IN ('lesson', 'outline')")
    _rewrite_mechanism(OLD_MECHANISMS)
