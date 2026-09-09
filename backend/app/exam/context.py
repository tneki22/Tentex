from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings.service import list_bindings
from app.materials.context import material_context
from app.models import (
    BindingMechanism,
    ChatMessage,
    ChatSession,
    ExamFormat,
    GoalPassport,
    NodeType,
    ProgramNode,
    ReferenceAnswer,
    TargetOutcome,
)
from app.projects.answer_lifecycle import is_reference_answer_available

# Бюджеты зафиксированы константами и не «настраиваются» — см. план вертикали.
TAIL_MESSAGES = 12
MAX_FRAGMENTS = 6
FRAGMENT_CHARS = 1500
CONTEXT_CHARS = 12_000

# Ключи ChatSession.context_flags — AI-CHATS.md §21.4. attempts и
# section_memory зарегистрированы в модели заранее, но контекст их пока не
# заполняет: соответствующая часть не существует до итерации 2.
CONTEXT_FLAG_KEYS = frozenset({"profile", "reference", "fragments", "attempts", "section_memory"})

TARGET_OUTCOME_LABELS = {
    TargetOutcome.AWARENESS: "иметь общее представление",
    TargetOutcome.UNDERSTANDING: "понимать и уметь объяснить",
    TargetOutcome.APPLICATION: "уверенно применять",
    TargetOutcome.MASTERY: "владеть в совершенстве",
}

EXAM_FORMAT_LABELS = {
    ExamFormat.QUESTIONS: "список вопросов",
    ExamFormat.QUESTIONS_TASKS: "вопросы и практические задачи",
    ExamFormat.TICKETS: "билеты",
    ExamFormat.UNKNOWN: "не указан",
}


def build_profile_card(passport: GoalPassport | None) -> dict[str, str]:
    """Компактная карточка профиля — только поля, реально заполненные в проекте.

    Пустые поля не превращаются в догадки (AI-CHATS.md §5.3): их просто нет
    в карточке, и модель должна честно сказать, что этого в профиле нет.
    """
    if passport is None:
        return {}
    card: dict[str, str] = {}
    if passport.subject:
        card["subject"] = passport.subject
    if passport.target_outcome is not None:
        card["target_outcome"] = TARGET_OUTCOME_LABELS[passport.target_outcome]
    if passport.exam_format is not None:
        card["exam_format"] = EXAM_FORMAT_LABELS[passport.exam_format]
    if passport.instructor_requirements:
        card["instructor_requirements"] = passport.instructor_requirements
    if passport.exam_procedure:
        card["exam_procedure"] = passport.exam_procedure
    if passport.important:
        card["important"] = passport.important
    if passport.excluded:
        card["excluded"] = passport.excluded
    return card


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
    profile: dict[str, str]
    manifest: list[dict[str, Any]]
    snapshot: dict[str, Any]
    fingerprint: str


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
    bindings = [
        binding
        for binding in list_bindings(session, project_id, node_id=node_id)
        if binding.mechanism != BindingMechanism.ANSWERS_FILE
    ]
    fragments: list[FragmentSnippet] = []
    for binding in bindings[:MAX_FRAGMENTS]:
        # Для Typst это exact-code с locator, а не испорченная формула из PDF.
        text = material_context(session, binding.material_id, binding.page_number, binding.text)
        text = text[:FRAGMENT_CHARS]
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
    flags = chat.context_flags or {}
    include_reference = flags.get("reference", True)
    include_fragments = flags.get("fragments", True)
    include_profile = flags.get("profile", True)

    answer = session.get(ReferenceAnswer, (chat.project_id, chat.program_node_id))
    reference_available = is_reference_answer_available(answer) and bool(
        answer and answer.text.strip()
    )
    reference_text = answer.text if include_reference and reference_available else None

    all_bound_fragments = bound_fragments(session, chat.project_id, chat.program_node_id)
    all_fragments = all_bound_fragments if include_fragments else []
    # Хвост сообщений судье не передаётся вообще (FR-V7): роль судьи получает
    # тот же вопрос, эталон и фрагменты, но не переписку чата.
    tail = [] if for_judge else _tail(session, chat)

    passport = session.get(GoalPassport, chat.project_id)
    profile = build_profile_card(passport) if include_profile else {}

    budget = CONTEXT_CHARS - len(reference_text or "")
    fragments, fragment_entries = _budget_fragments(all_fragments, max(budget, 0))
    if not include_fragments and all_bound_fragments:
        fragment_entries = [
            {
                "kind": "fragment",
                "id": None,
                "included": False,
                "reason": "excluded_by_user",
                "bytes": 0,
            }
        ]

    manifest: list[dict[str, Any]] = [
        {
            "kind": "program_node",
            "id": str(node.id),
            "sha256": _sha256(node.title),
            "bytes": len(node.title.encode()),
            "included": True,
        },
        {
            "kind": "profile",
            "id": str(chat.project_id),
            "sha256": _sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True)),
            "bytes": len(json.dumps(profile, ensure_ascii=False).encode()),
            "included": include_profile and bool(profile),
            "reason": (
                "excluded_by_user"
                if not include_profile
                else None
                if profile
                else "profile_empty"
            ),
        },
        {
            "kind": "reference_answer",
            "id": f"{chat.project_id}:{chat.program_node_id}",
            "revision": answer.revision if answer is not None else None,
            "sha256": _sha256(reference_text) if reference_text is not None else None,
            "bytes": len(reference_text.encode()) if reference_text is not None else 0,
            "included": reference_text is not None,
            "reason": (
                None
                if reference_text is not None
                else "excluded_by_user"
                if not include_reference
                else "reference_missing"
            ),
        },
        *fragment_entries,
        {
            "kind": "chat_tail",
            "id": str(chat.id),
            "count": len(tail),
            "bytes": sum(len(message.text.encode()) for message in tail),
            "included": bool(tail),
        },
        {
            "kind": "attempts_digest",
            "id": None,
            "included": False,
            "reason": "not_implemented",
        },
        {
            "kind": "section_memory",
            "id": None,
            "included": False,
            "reason": "not_implemented",
        },
    ]
    fingerprint = _sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str))

    snapshot = {
        "question": node.title,
        "reference_included": reference_text is not None,
        "fragment_count": len(fragments),
        "tail_count": len(tail),
        "for_judge": for_judge,
        "profile": profile,
        "persona": chat.persona.value,
        "strictness": chat.strictness.value,
        "manifest": manifest,
        "fingerprint": fingerprint,
    }
    return ChatContext(
        node=node,
        reference_text=reference_text,
        fragments=fragments,
        tail=tail,
        profile=profile,
        manifest=manifest,
        snapshot=snapshot,
        fingerprint=fingerprint,
    )
