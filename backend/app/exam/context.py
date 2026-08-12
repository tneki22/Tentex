from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings.service import list_bindings
from app.models import ChatMessage, ChatSession, NodeType, ProgramNode, ReferenceAnswer

# Бюджеты зафиксированы константами и не «настраиваются» — см. план вертикали.
TAIL_MESSAGES = 12
MAX_FRAGMENTS = 6
FRAGMENT_CHARS = 1500
CONTEXT_CHARS = 12_000


@dataclass(frozen=True)
class FragmentSnippet:
    fragment_id: UUID
    material_id: UUID
    material_name: str
    page_number: int
    text: str


@dataclass(frozen=True)
class ChatContext:
    node: ProgramNode
    reference_text: str | None
    fragments: list[FragmentSnippet]
    tail: list[ChatMessage]
    manifest: list[dict[str, Any]]
    snapshot: dict[str, Any]


def section_scope(session: Session, node: ProgramNode) -> UUID | None:
    """Ближайший узел-раздел на пути к корню; None — плоский список."""
    current = node
    while current.parent_id is not None:
        parent = session.get(ProgramNode, current.parent_id)
        if parent is None:
            return None
        if parent.node_type == NodeType.SECTION:
            return parent.id
        current = parent
    return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def bound_fragments(session: Session, project_id: UUID, node_id: UUID) -> list[FragmentSnippet]:
    bindings = list_bindings(session, project_id, node_id=node_id)
    fragments: list[FragmentSnippet] = []
    for binding in bindings[:MAX_FRAGMENTS]:
        text = binding.text[:FRAGMENT_CHARS]
        fragments.append(
            FragmentSnippet(
                fragment_id=binding.fragment_id,
                material_id=binding.material_id,
                material_name=binding.material_name,
                page_number=binding.page_number,
                text=text,
            )
        )
    return fragments


def _tail(session: Session, chat: ChatSession) -> list[ChatMessage]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == chat.id)
        .order_by(ChatMessage.sequence.desc())
        .limit(TAIL_MESSAGES)
    )
    return list(reversed(list(rows)))


def _budget_fragments(
    fragments: list[FragmentSnippet], budget: int
) -> tuple[list[FragmentSnippet], list[dict[str, Any]]]:
    """Урезает список фрагментов под CONTEXT_CHARS, обрезая с конца.

    Фрагменты, целиком помещающиеся в бюджет, идут как есть. Первый, который
    не помещается, обрезается по символам и помечается truncated=true;
    следующие за ним в контекст не идут вовсе (included=false).
    """
    kept: list[FragmentSnippet] = []
    entries: list[dict[str, Any]] = []
    remaining = budget
    exhausted = False
    for fragment in fragments:
        size = len(fragment.text)
        entry: dict[str, Any] = {
            "kind": "fragment",
            "id": str(fragment.fragment_id),
            "material_id": str(fragment.material_id),
            "page_number": fragment.page_number,
            "sha256": _sha256(fragment.text),
            "bytes": len(fragment.text.encode()),
        }
        if exhausted:
            entry["included"] = False
            entries.append(entry)
            continue
        if size <= remaining:
            kept.append(fragment)
            remaining -= size
            entry["included"] = True
            entries.append(entry)
            continue
        truncated_text = fragment.text[:remaining]
        if truncated_text.strip():
            kept.append(
                FragmentSnippet(
                    fragment.fragment_id,
                    fragment.material_id,
                    fragment.material_name,
                    fragment.page_number,
                    truncated_text,
                )
            )
            entry["included"] = True
            entry["truncated"] = True
        else:
            entry["included"] = False
        entries.append(entry)
        remaining = 0
        exhausted = True
    return kept, entries


def build_context(session: Session, chat: ChatSession, *, for_judge: bool) -> ChatContext:
    node = session.get(ProgramNode, chat.program_node_id)
    assert node is not None
    answer = session.get(ReferenceAnswer, (chat.project_id, chat.program_node_id))
    reference_text = answer.text if answer is not None and answer.is_active else None
    all_fragments = bound_fragments(session, chat.project_id, chat.program_node_id)
    # Хвост сообщений судье не передаётся вообще (FR-V7): роль судьи получает
    # тот же вопрос, эталон и фрагменты, но не переписку чата.
    tail = [] if for_judge else _tail(session, chat)

    budget = CONTEXT_CHARS - len(reference_text or "")
    fragments, fragment_entries = _budget_fragments(all_fragments, max(budget, 0))

    manifest: list[dict[str, Any]] = [
        {"kind": "program_node", "id": str(node.id), "included": True},
        {
            "kind": "reference_answer",
            "id": f"{chat.project_id}:{chat.program_node_id}",
            "revision": answer.revision if answer is not None else None,
            "included": reference_text is not None,
        },
        *fragment_entries,
        {"kind": "chat_tail", "count": len(tail), "included": bool(tail)},
    ]

    snapshot = {
        "question": node.title,
        "reference_included": reference_text is not None,
        "fragment_count": len(fragments),
        "tail_count": len(tail),
        "for_judge": for_judge,
    }
    return ChatContext(
        node=node,
        reference_text=reference_text,
        fragments=fragments,
        tail=tail,
        manifest=manifest,
        snapshot=snapshot,
    )
