"""provider-aware AI settings

Revision ID: 20260814_0015
Revises: 20260812_0014
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0015"
down_revision: str | Sequence[str] | None = "20260812_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(24, 12)


def _profile(base_url: str) -> str:
    return (
        "openrouter"
        if base_url.strip().rstrip("/") == "https://openrouter.ai/api/v1"
        else "openai_compatible"
    )


def upgrade() -> None:
    op.rename_table("ai_connections", "ai_connections_legacy")
    op.rename_table("ai_model_catalog", "ai_model_catalog_legacy")

    op.create_table(
        "ai_provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("catalog_profile", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("api_key_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("last_test_status", sa.String(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("last_catalog_refresh_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "catalog_profile IN ('openrouter', 'openai_compatible')",
            name=op.f("ck_ai_provider_connections_catalog_profile"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_provider_connections")),
        sa.UniqueConstraint("label", name=op.f("uq_ai_provider_connections_label")),
    )
    op.create_table(
        "ai_model_catalog",
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("max_completion_tokens", sa.Integer(), nullable=True),
        sa.Column("supported_parameters", sa.JSON(), nullable=False),
        sa.Column("input_modalities", sa.JSON(), nullable=False),
        sa.Column("output_modalities", sa.JSON(), nullable=False),
        sa.Column("reasoning", sa.JSON(), nullable=False),
        sa.Column("default_parameters", sa.JSON(), nullable=False),
        sa.Column("manual_overrides", sa.JSON(), nullable=False),
        sa.Column("prompt_price_usd", MONEY, nullable=True),
        sa.Column("completion_price_usd", MONEY, nullable=True),
        sa.Column("knowledge_cutoff", sa.String(), nullable=True),
        sa.Column("expiration_date", sa.String(), nullable=True),
        sa.Column("pricing_snapshot_at", sa.DateTime(), nullable=False),
        sa.Column("catalog_snapshot_at", sa.DateTime(), nullable=False),
        sa.Column("is_manually_added", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("favorite_order", sa.Integer(), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ai_provider_connections.id"],
            ondelete="CASCADE",
            name=op.f("fk_ai_model_catalog_provider_id_ai_provider_connections"),
        ),
        sa.PrimaryKeyConstraint("provider_id", "model_id", name=op.f("pk_ai_model_catalog")),
    )
    op.create_index(
        "ix_ai_model_catalog_provider_available",
        "ai_model_catalog",
        ["provider_id", "is_available"],
    )

    with op.batch_alter_table("ai_settings") as batch:
        batch.add_column(sa.Column("confirm_cost_usd", MONEY, nullable=True))
        batch.add_column(sa.Column("default_text_provider_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("default_text_model_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("default_speech_provider_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("default_speech_model_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_ai_settings_default_text_provider_id_ai_provider_connections",
            "ai_provider_connections",
            ["default_text_provider_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ai_settings_default_speech_provider_id_ai_provider_connections",
            "ai_provider_connections",
            ["default_speech_provider_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("ai_role_settings") as batch:
        batch.add_column(sa.Column("provider_override_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_ai_role_settings_provider_override_id_ai_provider_connections",
            "ai_provider_connections",
            ["provider_override_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("ai_runs") as batch:
        batch.add_column(sa.Column("provider_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column(
                "provider_label_snapshot",
                sa.String(),
                nullable=False,
                server_default="Неизвестный провайдер",
            )
        )
        batch.create_foreign_key(
            "fk_ai_runs_provider_id_ai_provider_connections",
            "ai_provider_connections",
            ["provider_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    metadata = sa.MetaData()
    legacy_connections = sa.Table("ai_connections_legacy", metadata, autoload_with=bind)
    legacy_models = sa.Table("ai_model_catalog_legacy", metadata, autoload_with=bind)
    providers = sa.Table("ai_provider_connections", metadata, autoload_with=bind)
    models = sa.Table("ai_model_catalog", metadata, autoload_with=bind)
    settings = sa.Table("ai_settings", metadata, autoload_with=bind)
    roles = sa.Table("ai_role_settings", metadata, autoload_with=bind)
    runs = sa.Table("ai_runs", metadata, autoload_with=bind)

    legacy_model_rows = list(bind.execute(sa.select(legacy_models)).mappings())
    model_counts: dict[str, int] = {}
    for row in legacy_model_rows:
        model_counts[row["modality"]] = model_counts.get(row["modality"], 0) + 1

    provider_by_modality: dict[str, str] = {}
    provider_label_by_modality: dict[str, str] = {}
    connection_rows = list(bind.execute(sa.select(legacy_connections)).mappings())
    for connection in connection_rows:
        modality = connection["modality"]
        meaningful = bool(
            connection["base_url"]
            or connection["api_key_ciphertext"]
            or connection["default_model_id"]
            or model_counts.get(modality)
        )
        if not meaningful:
            continue
        provider_id = uuid4().hex
        provider_by_modality[modality] = provider_id
        provider_label_by_modality[modality] = connection["label"]
        bind.execute(
            providers.insert().values(
                id=provider_id,
                label=connection["label"],
                catalog_profile=_profile(connection["base_url"]),
                base_url=connection["base_url"],
                api_key_ciphertext=connection["api_key_ciphertext"],
                is_favorite=modality == "text",
                last_test_status=connection["last_test_status"],
                last_tested_at=connection["last_tested_at"],
                last_catalog_refresh_at=connection["last_catalog_refresh_at"],
                updated_at=connection["updated_at"],
            )
        )

    favorite_order: dict[str, int] = {}
    for legacy in legacy_model_rows:
        provider_id = provider_by_modality.get(legacy["modality"])
        if provider_id is None:
            continue
        order = None
        if legacy["is_favorite"]:
            favorite_order[provider_id] = favorite_order.get(provider_id, 0) + 1
            order = favorite_order[provider_id]
        bind.execute(
            models.insert().values(
                provider_id=provider_id,
                model_id=legacy["model_id"],
                display_name=legacy["display_name"],
                context_length=legacy["context_length"],
                max_completion_tokens=None,
                supported_parameters=legacy["supported_parameters"],
                input_modalities=legacy["input_modalities"],
                output_modalities=legacy["output_modalities"],
                reasoning={},
                default_parameters={},
                manual_overrides={},
                prompt_price_usd=legacy["prompt_price_usd"],
                completion_price_usd=legacy["completion_price_usd"],
                knowledge_cutoff=None,
                expiration_date=None,
                pricing_snapshot_at=legacy["pricing_snapshot_at"],
                catalog_snapshot_at=legacy["catalog_snapshot_at"],
                is_manually_added=False,
                favorite_order=order,
                is_available=legacy["is_available"],
            )
        )

    defaults = {row["modality"]: row["default_model_id"] for row in connection_rows}
    bind.execute(
        settings.update()
        .where(settings.c.id == 1)
        .values(
            default_text_provider_id=provider_by_modality.get("text"),
            default_text_model_id=defaults.get("text"),
            default_speech_provider_id=provider_by_modality.get("speech"),
            default_speech_model_id=defaults.get("speech"),
        )
    )
    for role in bind.execute(sa.select(roles.c.role, roles.c.model_override)).mappings():
        if not role["model_override"]:
            continue
        modality = "speech" if role["role"] == "speech_transcription" else "text"
        bind.execute(
            roles.update()
            .where(roles.c.role == role["role"])
            .values(provider_override_id=provider_by_modality.get(modality))
        )
    for modality, provider_id in provider_by_modality.items():
        bind.execute(
            runs.update()
            .where(runs.c.modality == modality)
            .values(
                provider_id=provider_id,
                provider_label_snapshot=provider_label_by_modality[modality],
            )
        )

    op.drop_table("ai_model_catalog_legacy")
    op.drop_table("ai_connections_legacy")


def downgrade() -> None:
    op.rename_table("ai_model_catalog", "ai_model_catalog_provider_aware")
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

    bind = op.get_bind()
    metadata = sa.MetaData()
    providers = sa.Table("ai_provider_connections", metadata, autoload_with=bind)
    provider_models = sa.Table(
        "ai_model_catalog_provider_aware", metadata, autoload_with=bind
    )
    legacy_connections = sa.Table("ai_connections", metadata, autoload_with=bind)
    legacy_models = sa.Table("ai_model_catalog", metadata, autoload_with=bind)
    settings = sa.Table("ai_settings", metadata, autoload_with=bind)
    settings_row = bind.execute(sa.select(settings)).mappings().first()
    provider_rows = {
        row["id"]: row for row in bind.execute(sa.select(providers)).mappings()
    }
    for modality in ("text", "speech"):
        provider_id = settings_row[f"default_{modality}_provider_id"] if settings_row else None
        provider = provider_rows.get(provider_id)
        if provider is None:
            bind.execute(
                legacy_connections.insert().values(
                    modality=modality,
                    label="Текстовые модели" if modality == "text" else "Распознавание речи",
                    base_url="",
                    api_key_ciphertext=None,
                    default_model_id=None,
                    last_test_status=None,
                    last_tested_at=None,
                    last_catalog_refresh_at=None,
                    updated_at=settings_row["updated_at"],
                )
            )
            continue
        bind.execute(
            legacy_connections.insert().values(
                modality=modality,
                label=provider["label"],
                base_url=provider["base_url"],
                api_key_ciphertext=provider["api_key_ciphertext"],
                default_model_id=settings_row[f"default_{modality}_model_id"],
                last_test_status=provider["last_test_status"],
                last_tested_at=provider["last_tested_at"],
                last_catalog_refresh_at=provider["last_catalog_refresh_at"],
                updated_at=provider["updated_at"],
            )
        )
        for model in bind.execute(
            sa.select(provider_models).where(provider_models.c.provider_id == provider_id)
        ).mappings():
            bind.execute(
                legacy_models.insert().values(
                    modality=modality,
                    model_id=model["model_id"],
                    display_name=model["display_name"],
                    context_length=model["context_length"],
                    supported_parameters=model["supported_parameters"],
                    input_modalities=model["input_modalities"],
                    output_modalities=model["output_modalities"],
                    prompt_price_usd=model["prompt_price_usd"],
                    completion_price_usd=model["completion_price_usd"],
                    pricing_snapshot_at=model["pricing_snapshot_at"],
                    catalog_snapshot_at=model["catalog_snapshot_at"],
                    is_favorite=model["favorite_order"] is not None,
                    is_available=model["is_available"],
                )
            )

    with op.batch_alter_table("ai_runs") as batch:
        batch.drop_constraint(
            "fk_ai_runs_provider_id_ai_provider_connections", type_="foreignkey"
        )
        batch.drop_column("provider_label_snapshot")
        batch.drop_column("provider_id")
    with op.batch_alter_table("ai_role_settings") as batch:
        batch.drop_constraint(
            "fk_ai_role_settings_provider_override_id_ai_provider_connections",
            type_="foreignkey",
        )
        batch.drop_column("provider_override_id")
    with op.batch_alter_table("ai_settings") as batch:
        batch.drop_constraint(
            "fk_ai_settings_default_text_provider_id_ai_provider_connections",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_ai_settings_default_speech_provider_id_ai_provider_connections",
            type_="foreignkey",
        )
        batch.drop_column("default_speech_model_id")
        batch.drop_column("default_speech_provider_id")
        batch.drop_column("default_text_model_id")
        batch.drop_column("default_text_provider_id")
        batch.drop_column("confirm_cost_usd")
    op.drop_table("ai_model_catalog_provider_aware")
    op.drop_table("ai_provider_connections")
