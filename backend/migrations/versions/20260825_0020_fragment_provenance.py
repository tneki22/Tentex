"""store fragment recognition provenance and allow source-only imported answers

Revision ID: 20260825_0020
Revises: 20260815_0019
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0020"
down_revision: str | Sequence[str] | None = "20260815_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recognition_source() -> sa.Enum:
    return sa.Enum(
        "native",
        "ocr",
        "vl",
        "manual",
        name="fragment_recognition_source",
        native_enum=False,
        create_constraint=False,
    )


def upgrade() -> None:
    with op.batch_alter_table("material_fragments") as batch:
        batch.add_column(
            sa.Column(
                "recognition_source",
                _recognition_source(),
                nullable=False,
                server_default="native",
            )
        )
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch.create_check_constraint(
            "ck_material_fragments_recognition_source",
            "recognition_source IN ('native', 'ocr', 'vl', 'manual')",
        )
    with op.batch_alter_table("reference_answers") as batch:
        batch.drop_constraint("ck_reference_answers_text_nonblank", type_="check")


def downgrade() -> None:
    op.execute("DELETE FROM reference_answers WHERE length(trim(text)) = 0")
    with op.batch_alter_table("reference_answers") as batch:
        batch.create_check_constraint(
            "ck_reference_answers_text_nonblank", "length(trim(text)) > 0"
        )
    with op.batch_alter_table("material_fragments") as batch:
        batch.drop_constraint(
            "ck_material_fragments_recognition_source", type_="check"
        )
        batch.drop_column("confidence")
        batch.drop_column("recognition_source")
