"""ocr settings and engine registry

Revision ID: 20260825_0022
Revises: 20260825_0021
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0022"
down_revision: str | Sequence[str] | None = "20260825_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "ocr_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "default_mode", enum("fast", "textbook", name="ocr_default_mode"), nullable=False
        ),
        sa.Column("quality_threshold", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("raster_scale", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_ocr_settings_singleton")),
        sa.CheckConstraint(
            "quality_threshold >= 0 AND quality_threshold <= 1",
            name=op.f("ck_ocr_settings_threshold_range"),
        ),
        sa.CheckConstraint(
            "raster_scale IN (1.5, 2.0, 3.0)", name=op.f("ck_ocr_settings_raster_scale_known")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ocr_settings")),
    )
    op.create_table(
        "ocr_engine_configs",
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("device", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("executor", sa.String(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("mode", name=op.f("pk_ocr_engine_configs")),
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        sa.table(
            "ocr_settings",
            sa.column("id", sa.Integer()),
            sa.column("default_mode", sa.String()),
            sa.column("quality_threshold", sa.Float()),
            sa.column("raster_scale", sa.Float()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [
            {
                "id": 1,
                "default_mode": "fast",
                "quality_threshold": 0.75,
                "raster_scale": 2.0,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "ocr_engine_configs",
            sa.column("mode", sa.String()),
            sa.column("enabled", sa.Boolean()),
            sa.column("model_id", sa.String()),
            sa.column("device", sa.String()),
            sa.column("language", sa.String()),
            sa.column("executor", sa.String()),
            sa.column("extra", sa.JSON()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [
            {
                "mode": "fast",
                "enabled": True,
                "model_id": "PP-OCRv5",
                "device": None,
                "language": "ru",
                "executor": None,
                "extra": {},
                "updated_at": now,
            },
            {
                "mode": "textbook",
                "enabled": True,
                "model_id": "PaddleOCR-VL-1.6-0.9B",
                "device": "gpu",
                "language": None,
                "executor": "auto",
                "extra": {},
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("ocr_engine_configs")
    op.drop_table("ocr_settings")
