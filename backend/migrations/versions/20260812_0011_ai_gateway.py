"""external model gateway

Revision ID: 20260812_0011
Revises: 20260812_0010
Create Date: 2026-08-12
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0011"
down_revision: str | Sequence[str] | None = "20260812_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(24, 12)


def upgrade() -> None:
    op.create_table(
        "ai_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_models_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("daily_limit_usd", MONEY, nullable=True),
        sa.Column("operation_limit_usd", MONEY, nullable=True),
        sa.Column("confirm_input_tokens", sa.Integer(), nullable=False, server_default="20000"),
        sa.Column("usd_rub_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("usd_rub_rate_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_ai_settings_singleton")),
        sa.CheckConstraint(
            "confirm_input_tokens >= 0", name=op.f("ck_ai_settings_confirm_tokens_nonnegative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_settings")),
    )
    op.create_table(
        "ai_connections",
        sa.Column("modality", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("api_key_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("default_model_id", sa.String(), nullable=True),
        sa.Column("last_test_status", sa.String(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("last_catalog_refresh_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "modality IN ('text', 'speech')", name=op.f("ck_ai_connections_modality")
        ),
        sa.PrimaryKeyConstraint("modality", name=op.f("pk_ai_connections")),
    )
    op.create_table(
        "ai_role_settings",
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("model_override", sa.String(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("role", name=op.f("pk_ai_role_settings")),
    )
    op.create_table(
        "ai_model_catalog",
        sa.Column("modality", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("supported_parameters", sa.JSON(), nullable=False),
        sa.Column("input_modalities", sa.JSON(), nullable=False),
        sa.Column("output_modalities", sa.JSON(), nullable=False),
        sa.Column("prompt_price_usd", MONEY, nullable=True),
        sa.Column("completion_price_usd", MONEY, nullable=True),
        sa.Column("pricing_snapshot_at", sa.DateTime(), nullable=False),
        sa.Column("catalog_snapshot_at", sa.DateTime(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "modality IN ('text', 'speech')", name=op.f("ck_ai_model_catalog_modality")
        ),
        sa.PrimaryKeyConstraint("modality", "model_id", name=op.f("pk_ai_model_catalog")),
    )
    op.create_index(
        "ix_ai_model_catalog_modality_available",
        "ai_model_catalog",
        ["modality", "is_available"],
    )
    op.create_table(
        "ai_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("modality", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_model_id", sa.String(), nullable=False),
        sa.Column("actual_model_id", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("context_manifest", sa.JSON(), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", MONEY, nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("provider_cached_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_cost_usd", MONEY, nullable=True),
        sa.Column("usd_rub_rate_snapshot", sa.Numeric(18, 6), nullable=True),
        sa.Column("usd_rub_rate_date", sa.Date(), nullable=True),
        sa.Column("actual_cost_rub", MONEY, nullable=True),
        sa.Column("pricing_snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("provider_request_id", sa.String(), nullable=True),
        sa.Column("cached_from_run_id", sa.Uuid(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'cached')",
            name=op.f("ck_ai_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["cached_from_run_id"],
            ["ai_runs.id"],
            ondelete="SET NULL",
            name=op.f("fk_ai_runs_cached_from_run_id_ai_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_ai_runs_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_runs")),
    )
    op.create_index("ix_ai_runs_created_role", "ai_runs", ["created_at", "role"])
    op.create_index("ix_ai_runs_project_created", "ai_runs", ["project_id", "created_at"])
    op.create_index("ix_ai_runs_request_hash", "ai_runs", ["request_hash"])
    op.create_table(
        "ai_cache_entries",
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_ai_cache_entries_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["ai_runs.id"],
            ondelete="CASCADE",
            name=op.f("fk_ai_cache_entries_source_run_id_ai_runs"),
        ),
        sa.PrimaryKeyConstraint("request_hash", name=op.f("pk_ai_cache_entries")),
    )
    op.create_index("ix_ai_cache_project_role", "ai_cache_entries", ["project_id", "role"])
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        sa.table(
            "ai_settings",
            sa.column("id", sa.Integer()),
            sa.column("external_models_enabled", sa.Boolean()),
            sa.column("confirm_input_tokens", sa.Integer()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [
            {
                "id": 1,
                "external_models_enabled": False,
                "confirm_input_tokens": 20000,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "ai_connections",
            sa.column("modality", sa.String()),
            sa.column("label", sa.String()),
            sa.column("base_url", sa.String()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [
            {
                "modality": "text",
                "label": "Текстовые модели",
                "base_url": "https://openrouter.ai/api/v1",
                "updated_at": now,
            },
            {
                "modality": "speech",
                "label": "Распознавание речи",
                "base_url": "",
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_cache_project_role", table_name="ai_cache_entries")
    op.drop_table("ai_cache_entries")
    op.drop_index("ix_ai_runs_request_hash", table_name="ai_runs")
    op.drop_index("ix_ai_runs_project_created", table_name="ai_runs")
    op.drop_index("ix_ai_runs_created_role", table_name="ai_runs")
    op.drop_table("ai_runs")
    op.drop_index("ix_ai_model_catalog_modality_available", table_name="ai_model_catalog")
    op.drop_table("ai_model_catalog")
    op.drop_table("ai_role_settings")
    op.drop_table("ai_connections")
    op.drop_table("ai_settings")
