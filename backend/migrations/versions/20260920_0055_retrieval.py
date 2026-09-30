"""Общий retrieval-контур: профили embeddings, версионные индексы и benchmark.

Revision ID: 20260920_0055
Revises: 20260920_0054
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0055"
down_revision = "20260920_0054"
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
)
JOB_KINDS = (*OLD_JOB_KINDS, "retrieval_index", "retrieval_model_install", "retrieval_exhaustive")


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
    _replace_job_kind_check(JOB_KINDS)
    op.create_table(
        "embedding_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "backend_kind",
            sa.Enum(
                "local_hf",
                "openai_compatible",
                name="embedding_backend_kind",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("model_revision", sa.String(), nullable=True),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("normalize", sa.Boolean(), nullable=False),
        sa.Column("pooling", sa.String(16), nullable=False),
        sa.Column("query_template", sa.Text(), nullable=False),
        sa.Column("document_template", sa.Text(), nullable=False),
        sa.Column("installed", sa.Boolean(), nullable=False),
        sa.Column("tested_at", sa.DateTime(), nullable=True),
        sa.Column("test_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "backend_kind IN ('local_hf', 'openai_compatible')",
            name=op.f("ck_embedding_profiles_embedding_backend_kind"),
        ),
        sa.CheckConstraint(
            "dimension IS NULL OR dimension > 0",
            name=op.f("ck_embedding_profiles_dimension_positive"),
        ),
        sa.CheckConstraint(
            "batch_size > 0", name=op.f("ck_embedding_profiles_batch_size_positive")
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["ai_provider_connections.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_profiles")),
        sa.UniqueConstraint("label", name=op.f("uq_embedding_profiles_label")),
    )
    op.create_table(
        "retrieval_indexes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(8), nullable=False),
        sa.Column("preset", sa.String(8), nullable=False),
        sa.Column("chunk_target_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_max_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("material_count", sa.Integer(), nullable=False),
        sa.Column("corpus_manifest", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "state IN ('building', 'ready', 'active', 'failed')",
            name=op.f("ck_retrieval_indexes_retrieval_index_state"),
        ),
        sa.CheckConstraint(
            "preset IN ('fast', 'balanced', 'accurate')",
            name=op.f("ck_retrieval_indexes_retrieval_preset"),
        ),
        sa.CheckConstraint(
            "chunk_target_tokens > 0",
            name=op.f("ck_retrieval_indexes_chunk_target_positive"),
        ),
        sa.CheckConstraint(
            "chunk_max_tokens >= chunk_target_tokens",
            name=op.f("ck_retrieval_indexes_chunk_max_valid"),
        ),
        sa.CheckConstraint(
            "chunk_overlap_tokens >= 0",
            name=op.f("ck_retrieval_indexes_chunk_overlap_nonnegative"),
        ),
        sa.CheckConstraint(
            "chunk_count >= 0", name=op.f("ck_retrieval_indexes_chunk_count_nonnegative")
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["embedding_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_indexes")),
    )
    op.create_index(
        "ix_retrieval_indexes_state_created",
        "retrieval_indexes",
        ["state", "created_at"],
    )
    op.create_table(
        "retrieval_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_index_id", sa.Uuid(), nullable=True),
        sa.Column("default_profile_id", sa.Uuid(), nullable=True),
        sa.Column("preset", sa.String(8), nullable=False),
        sa.Column("expert_parameters", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "preset IN ('fast', 'balanced', 'accurate')",
            name=op.f("ck_retrieval_settings_retrieval_settings_preset"),
        ),
        sa.ForeignKeyConstraint(["active_index_id"], ["retrieval_indexes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["default_profile_id"], ["embedding_profiles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_settings")),
    )
    op.create_table(
        "retrieval_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("index_id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("quality", sa.String(7), nullable=True),
        sa.Column("fragment_ids", sa.JSON(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('text', 'typst_source')",
            name=op.f("ck_retrieval_chunks_retrieval_chunk_kind"),
        ),
        sa.CheckConstraint(
            "quality IN ('native', 'ocr', 'ocr_low')",
            name=op.f("ck_retrieval_chunks_retrieval_chunk_quality"),
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_retrieval_chunks_revision_positive")),
        sa.CheckConstraint(
            "sort_order >= 0", name=op.f("ck_retrieval_chunks_sort_order_nonnegative")
        ),
        sa.CheckConstraint(
            "token_count > 0", name=op.f("ck_retrieval_chunks_token_count_positive")
        ),
        sa.CheckConstraint(
            "page_from IS NULL OR (page_from > 0 AND page_to >= page_from)",
            name=op.f("ck_retrieval_chunks_page_range_valid"),
        ),
        sa.ForeignKeyConstraint(["block_id"], ["material_blocks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["index_id"], ["retrieval_indexes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_chunks")),
        sa.UniqueConstraint("index_id", "sort_order", name="uq_retrieval_chunks_index_order"),
    )
    op.create_index(
        "ix_retrieval_chunks_index_material",
        "retrieval_chunks",
        ["index_id", "material_id"],
    )
    op.create_index("ix_retrieval_chunks_index_block", "retrieval_chunks", ["index_id", "block_id"])
    op.create_table(
        "retrieval_benchmark_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("relevant_material_ids", sa.JSON(), nullable=False),
        sa.Column("relevant_locator_ids", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_benchmark_cases")),
    )
    op.create_table(
        "retrieval_benchmark_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("index_id", sa.Uuid(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["index_id"], ["retrieval_indexes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_benchmark_runs")),
    )
    op.create_table(
        "retrieval_exhaustive_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=True),
        sa.Column("final_message_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("corpus_manifest", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["background_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["final_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_exhaustive_runs")),
        sa.UniqueConstraint("job_id", name=op.f("uq_retrieval_exhaustive_runs_job_id")),
    )
    op.create_index(
        "ix_retrieval_exhaustive_session_created",
        "retrieval_exhaustive_runs",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieval_exhaustive_session_created",
        table_name="retrieval_exhaustive_runs",
    )
    op.drop_table("retrieval_exhaustive_runs")
    op.drop_table("retrieval_benchmark_runs")
    op.drop_table("retrieval_benchmark_cases")
    op.drop_index("ix_retrieval_chunks_index_block", table_name="retrieval_chunks")
    op.drop_index("ix_retrieval_chunks_index_material", table_name="retrieval_chunks")
    op.drop_table("retrieval_chunks")
    op.drop_table("retrieval_settings")
    op.drop_index("ix_retrieval_indexes_state_created", table_name="retrieval_indexes")
    op.drop_table("retrieval_indexes")
    op.drop_table("embedding_profiles")
    _replace_job_kind_check(OLD_JOB_KINDS)
