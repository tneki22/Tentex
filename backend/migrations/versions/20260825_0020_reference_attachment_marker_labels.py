"""backfill safe, unique reference-answer attachment marker labels

Revision ID: 20260825_0020
Revises: 20260815_0019
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0020"
down_revision: str | Sequence[str] | None = "20260815_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _marker_label(value: str) -> str:
    normalized = " ".join(value.replace("[", "［").replace("]", "］").split())
    return normalized or "файл"


def _unique_file_name(file_name: str, existing_names: set[str]) -> str:
    if file_name not in existing_names:
        return file_name
    path = Path(file_name)
    index = 2
    while True:
        candidate = f"{path.stem} ({index}){path.suffix}"
        if candidate not in existing_names:
            return candidate
        index += 1


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    attachments = sa.Table("reference_answer_attachments", metadata, autoload_with=bind)
    existing_by_answer: dict[tuple[object, object], set[str]] = {}
    rows = bind.execute(
        sa.select(
            attachments.c.id,
            attachments.c.project_id,
            attachments.c.program_node_id,
            attachments.c.file_name,
        ).order_by(
            attachments.c.project_id,
            attachments.c.program_node_id,
            attachments.c.created_at,
            attachments.c.id,
        )
    ).mappings()
    for row in rows:
        answer_key = (row["project_id"], row["program_node_id"])
        existing_names = existing_by_answer.setdefault(answer_key, set())
        file_name = _unique_file_name(_marker_label(str(row["file_name"])), existing_names)
        existing_names.add(file_name)
        if file_name != row["file_name"]:
            bind.execute(
                attachments.update()
                .where(attachments.c.id == row["id"])
                .values(file_name=file_name)
            )


def downgrade() -> None:
    # Original attachment names cannot be reconstructed after normalization.
    pass
