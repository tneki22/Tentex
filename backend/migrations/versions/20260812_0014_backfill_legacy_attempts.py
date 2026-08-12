"""backfill attempts saved by the iteration 1a answer form

Revision ID: 20260812_0014
Revises: 20260812_0013
Create Date: 2026-08-12
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0014"
down_revision: str | Sequence[str] | None = "20260812_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    messages = sa.Table("chat_messages", metadata, autoload_with=bind)
    chats = sa.Table("chat_sessions", metadata, autoload_with=bind)
    attempts = sa.Table("attempts", metadata, autoload_with=bind)
    nodes = sa.Table("program_nodes", metadata, autoload_with=bind)
    references = sa.Table("reference_answers", metadata, autoload_with=bind)

    legacy_rows = bind.execute(
        sa.select(
            messages.c.id.label("message_id"),
            messages.c.payload,
            messages.c.context_snapshot,
            messages.c.created_at,
            chats.c.project_id,
            chats.c.program_node_id,
            chats.c.persona,
            chats.c.strictness,
            nodes.c.title.label("question"),
        )
        .join(chats, chats.c.id == messages.c.session_id)
        .join(nodes, nodes.c.id == chats.c.program_node_id)
        .where(
            messages.c.payload_kind == "answer_form",
            messages.c.attempt_id.is_(None),
        )
        .order_by(chats.c.program_node_id, messages.c.created_at, messages.c.sequence)
    ).mappings()

    fallback_ordinals: dict[object, int] = {}
    for row in legacy_rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        text = str(payload.get("text", "")).strip()
        if not text:
            continue
        node_id = row["program_node_id"]
        fallback_ordinals[node_id] = fallback_ordinals.get(node_id, 0) + 1
        raw_ordinal = payload.get("ordinal")
        ordinal = (
            raw_ordinal
            if isinstance(raw_ordinal, int) and raw_ordinal >= 1
            else fallback_ordinals[node_id]
        )

        reference = bind.execute(
            sa.select(references.c.text, references.c.revision).where(
                references.c.project_id == row["project_id"],
                references.c.program_node_id == node_id,
                references.c.is_active.is_(True),
            )
        ).mappings().first()
        reference_text = reference["text"] if reference is not None else None
        reference_revision = reference["revision"] if reference is not None else None
        question = str(row["question"])
        snapshot = {
            "question": question,
            "reference_included": reference_text is not None,
            "reference_text": reference_text,
            "reference_revision": reference_revision,
            "fragment_count": 0,
            "fragments": [],
            "tail_count": 0,
            "for_judge": True,
            "legacy_backfill": True,
            "manifest": [
                {
                    "kind": "program_node",
                    "id": str(node_id),
                    "sha256": _sha256(question),
                    "bytes": len(question.encode()),
                    "included": True,
                },
                {
                    "kind": "reference_answer",
                    "id": f'{row["project_id"]}:{node_id}',
                    "revision": reference_revision,
                    "sha256": _sha256(reference_text) if reference_text is not None else None,
                    "bytes": len(reference_text.encode()) if reference_text is not None else 0,
                    "included": reference_text is not None,
                },
                {
                    "kind": "chat_tail",
                    "count": 0,
                    "bytes": 0,
                    "included": False,
                },
            ],
        }
        # SQLite reflection sees Uuid columns as CHAR(32), so bind the on-disk
        # representation explicitly instead of handing sqlite3 a UUID object.
        attempt_id = uuid4().hex
        bind.execute(
            attempts.insert().values(
                id=attempt_id,
                project_id=row["project_id"],
                program_node_id=node_id,
                parent_attempt_id=None,
                ordinal=ordinal,
                text=text,
                persona=row["persona"],
                strictness=row["strictness"],
                context_snapshot=snapshot,
                created_at=row["created_at"],
            )
        )
        bind.execute(
            messages.update()
            .where(messages.c.id == row["message_id"])
            .values(attempt_id=attempt_id, context_snapshot=snapshot)
        )


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    messages = sa.Table("chat_messages", metadata, autoload_with=bind)
    attempts = sa.Table("attempts", metadata, autoload_with=bind)
    legacy_ids = [
        row.id
        for row in bind.execute(sa.select(attempts.c.id, attempts.c.context_snapshot))
        if isinstance(row.context_snapshot, dict)
        and row.context_snapshot.get("legacy_backfill") is True
    ]
    if not legacy_ids:
        return
    bind.execute(
        messages.update()
        .where(messages.c.attempt_id.in_(legacy_ids))
        .values(attempt_id=None)
    )
    bind.execute(attempts.delete().where(attempts.c.id.in_(legacy_ids)))
