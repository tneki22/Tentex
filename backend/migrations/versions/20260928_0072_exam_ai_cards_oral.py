"""Происхождение ИИ-карточки и черновики устного ответа.

Revision ID: 20260928_0072
Revises: 20260928_0071
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0072"
down_revision = "20260928_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("generation_run_id", sa.Uuid(), nullable=True))
    op.create_table(
        "oral_recordings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_id", sa.Uuid(), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id", sa.Uuid(), sa.ForeignKey("attempts.id", ondelete="SET NULL"),
            nullable=True, unique=True,
        ),
        sa.Column("audio_path", sa.String(), nullable=True),
        sa.Column("audio_format", sa.String(), nullable=False),
        sa.Column("audio_duration_ms", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("words", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("audio_expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_oral_recordings_expiry", "oral_recordings", ["audio_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_oral_recordings_expiry", table_name="oral_recordings")
    op.drop_table("oral_recordings")
    op.drop_column("cards", "generation_run_id")
