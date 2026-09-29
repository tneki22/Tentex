"""Чтение опубликованных опор и атомарные пользовательские решения И5."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.coverage import passages, queries
from app.coverage.schemas import DecisionWrite
from app.coverage.snapshots import fingerprint, require_project
from app.db import project_write_transaction
from app.materials.naming import project_material_display_name
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    CoverageDecision,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    NodeType,
    ProgramNode,
    ProjectActionLog,
    ProjectMaterial,
    utc_now,
)
from app.projects.errors import (
    ProjectConflictError,
    ProjectDomainError,
    ProjectNotFoundError,
)

ACTIVE_STATUSES = {BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE}
STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}
SOURCE_ROLE_RANK = {"main": 0, "additional": 1, "reference": 2}


def _active_nodes(session: Session, project_id: UUID) -> list[ProgramNode]:
    return list(
        session.scalars(
            select(ProgramNode)
            .where(
                ProgramNode.project_id == project_id,
                ProgramNode.node_type.in_(STUDY_NODE_TYPES),
                ProgramNode.is_in_current_program.is_(True),
                ProgramNode.is_archived.is_(False),
            )
            .order_by(ProgramNode.sort_order, ProgramNode.id)
        )
    )


def _binding_rows(
    session: Session,
    project_id: UUID,
    node_id: UUID | None = None,
):
    """Загрузить полные строки одной темы без ленивых N+1."""
    statement = (
        select(
            Binding,
            MaterialFragment,
            MaterialPage,
            Material,
            ProjectMaterial,
            MaterialBlock,
        )
        .join(MaterialFragment, MaterialFragment.id == Binding.fragment_id)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(Material, Material.id == Binding.material_id)
        .join(
            ProjectMaterial,
            (ProjectMaterial.project_id == Binding.project_id)
            & (ProjectMaterial.material_id == Binding.material_id),
        )
        .outerjoin(MaterialBlock, MaterialBlock.id == Binding.block_id)
        .where(Binding.project_id == project_id, Binding.status.in_(ACTIVE_STATUSES))
        # Страница несёт весь свой текст, разметку и элементы, а материал — оглавление:
        # на теме в 455 опор полные строки стоили 2,3 с из 3.
        .options(
            load_only(MaterialPage.id, MaterialPage.page_number, MaterialPage.revision),
            load_only(Material.id, Material.display_name, Material.active_parse_revision),
            load_only(MaterialBlock.id, MaterialBlock.page_from, MaterialBlock.page_to),
        )
    )
    if node_id is not None:
        statement = statement.where(Binding.program_node_id == node_id)
    return list(session.execute(statement))


def _binding_summaries(session: Session, project_id: UUID) -> list[Binding]:
    """Список тем читает только поля связи; текст и геометрию берёт уже выбранная тема."""
    return list(
        session.scalars(
            select(Binding)
            .options(
                load_only(
                    Binding.id,
                    Binding.program_node_id,
                    Binding.material_id,
                    Binding.status,
                    Binding.roles,
                    Binding.semantic_kind,
                    Binding.evidence_ref,
                )
            )
            .where(
                Binding.project_id == project_id,
                Binding.status.in_(ACTIVE_STATUSES),
            )
        )
    )


def _decision_map(session: Session, project_id: UUID, kind: str) -> dict[str, CoverageDecision]:
    return {
        row.target_key: row
        for row in session.scalars(
            select(CoverageDecision).where(
                CoverageDecision.project_id == project_id,
                CoverageDecision.kind == kind,
            )
        )
    }


def _evidence_id(binding: Binding) -> str:
    ref = binding.evidence_ref or {}
    if all(ref.get(key) for key in ("task_id", "target_id", "key")):
        return f"{ref['task_id']}:{ref['target_id']}:{ref['key']}"
    return f"binding:{binding.id}"


def _fresh_binding_ids(session: Session, project_id: UUID, bindings) -> set[UUID]:
    return queries.fresh_binding_ids(
        session,
        project_id,
        bindings,
    )


def _binding_summary_rank(binding: Binding, preferred_binding_id: str | None) -> tuple:
    """До открытия темы достаточно личного приоритета и роли; полный ранг считает тема."""
    roles = set(binding.roles or [])
    return (
        str(binding.id) != preferred_binding_id,
        not bool(roles & {"definition", "explanation"}),
        _evidence_id(binding),
    )


def _parent_chain(session: Session, project_id: UUID) -> dict:
    """Родители всех узлов программы: цепочка не рвётся на разделах вне изучения."""
    return {
        row.id: row.parent_id
        for row in session.execute(
            select(ProgramNode.id, ProgramNode.parent_id).where(
                ProgramNode.project_id == project_id,
                ProgramNode.is_archived.is_(False),
            )
        )
    }


def _covered_subtrees(parent_of: dict, own_content: set) -> set:
    """Тема обеспечена, если содержание есть у неё самой или у её подтем.

    Проход 2 привязывает блок к самой узкой подходящей теме, поэтому глава «ТЕМА 3»
    с 272 опорами у детей не получает ни одной своей и попадала в Пробелы рядом с
    темами, по которым материала действительно нет.
    """
    covered = set()
    for node_id in own_content:
        current = node_id
        while current is not None and current not in covered:
            covered.add(current)
            current = parent_of.get(current)
    return covered


def topics_page(
    session: Session, project_id: UUID, view: str, offset: int, limit: int
) -> dict:
    """Вернуть темы для чтения или честные пробелы одной ревизии."""
    project = require_project(session, project_id)
    nodes = _active_nodes(session, project_id)
    node_by_id = {node.id: node for node in nodes}
    bindings = _binding_summaries(session, project_id)
    fresh_ids = _fresh_binding_ids(session, project_id, bindings)
    hidden = _decision_map(session, project_id, "hide_evidence")
    preferred = _decision_map(session, project_id, "prefer_reading")
    grouped: dict[UUID, list] = defaultdict(list)
    for binding in bindings:
        grouped[binding.program_node_id].append(binding)
    content_by_node = {
        node.id: [
            binding
            for binding in grouped[node.id]
            if binding.id in fresh_ids and binding.semantic_kind == "content"
        ]
        for node in nodes
    }
    covered = _covered_subtrees(
        _parent_chain(session, project_id) if view == "gaps" else {},
        {node_id for node_id, items in content_by_node.items() if items},
    )
    result = []
    for node in nodes:
        node_bindings = grouped[node.id]
        content_bindings = content_by_node[node.id]
        if view == "readable" and not content_bindings:
            continue
        if view == "gaps" and node.id in covered:
            continue
        legacy = [item for item in node_bindings if item.semantic_kind in {None, "unknown"}]
        mentions = [item for item in node_bindings if item.semantic_kind == "mention"]
        hidden_count = sum(
            bool(hidden.get(str(item.id)) and hidden[str(item.id)].payload.get("hidden"))
            for item in node_bindings
        )
        preferred_row = preferred.get(str(node.id))
        preferred_id = (preferred_row.payload or {}).get("binding_id") if preferred_row else None
        best = next(
            (
                binding
                for binding in sorted(
                    content_bindings,
                    key=lambda item: _binding_summary_rank(item, preferred_id),
                )
                if not (
                    hidden.get(str(binding.id))
                    and hidden[str(binding.id)].payload.get("hidden")
                )
            ),
            None,
        )
        parent = node_by_id.get(node.parent_id)
        result.append(
            {
                "node_id": str(node.id),
                "title": node.title,
                "parent_title": parent.title if parent else None,
                "evidence_count": len(content_bindings),
                "mention_count": len(mentions),
                "hidden_count": hidden_count,
                "legacy_count": len(legacy),
                "best_evidence_id": _evidence_id(best) if best else None,
            }
        )
    return {
        "coverage_revision": project.coverage_revision,
        "items": result[offset : offset + limit],
        "total": len(result),
        "next_offset": offset + limit if offset + limit < len(result) else None,
    }


def blocks_page(
    session: Session, project_id: UUID, view: str, offset: int, limit: int
) -> dict:
    """Развести результат `outside_program` и технически требующие решения блоки."""
    project = require_project(session, project_id)
    blocks, _ = queries.current_map(session, project_id)
    if view == "outside_program":
        rows = [item for item in blocks if item["bucket"] == "outside_program"]
    else:
        rows = [item for item in blocks if item["bucket"] in queries.ISSUE_BUCKETS]
        rows.sort(key=lambda item: queries.ISSUE_BUCKETS.index(item["bucket"]))
    return {
        "coverage_revision": project.coverage_revision,
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "distribution": dict(
            (bucket, sum(item["bucket"] == bucket for item in rows))
            for bucket in {item["bucket"] for item in rows}
        ),
    }


def _evidence_summary(
    row,
    *,
    fresh_ids: set[UUID],
    hidden: dict[str, CoverageDecision],
    preferred_binding_id: str | None,
) -> dict:
    """Собрать одну карточку без протекания служебного ранга в API."""
    binding, fragment, page, material, project_material, block = row
    hidden_row = hidden.get(str(binding.id))
    stale = binding.id not in fresh_ids or page.revision != material.active_parse_revision
    return {
        "id": _evidence_id(binding),
        "binding_id": str(binding.id),
        "topic_id": str(binding.program_node_id),
        "material_id": str(binding.material_id),
        "material_name": project_material_display_name(material, project_material),
        "page_from": block.page_from if block else page.page_number,
        "page_to": block.page_to if block else page.page_number,
        "fragment_ids": [str(fragment.id)],
        "quote": fragment.text,
        "description": "",
        "roles": binding.roles or [],
        "semantic_kind": binding.semantic_kind,
        "status": binding.status.value,
        "mechanism": binding.mechanism.value,
        "quality": fragment.quality.value,
        "available": page.revision == material.active_parse_revision,
        "stale": stale,
        "hidden": bool(hidden_row and hidden_row.payload.get("hidden")),
        "preferred": str(binding.id) == preferred_binding_id,
        "legacy": binding.semantic_kind in {None, "unknown"},
        "_priority": project_material.priority,
        "_source_role": project_material.source_role.value,
        "_material": binding.material_id,
        "_revision": page.revision,
        "_page": page.page_number,
    }


def _passage_rank(item: dict) -> tuple:
    """Порядок чтения: основной источник, приоритет, затем место в материале.

    Прежний ранг ставил текстовый слой выше OCR и сравнивал строковые ID опор, и
    пример СДНФ читался «II. Аналитический способ…» раньше «Решение.».
    """
    return (
        SOURCE_ROLE_RANK.get(item["_source_role"], 9),
        item["_priority"],
        item["material_name"].casefold(),
        item["_position"],
    )


def _starter(content: list[dict]) -> dict | None:
    """С чего начать: личный выбор, иначе первое определение, иначе первое объяснение."""
    readable = [item for item in content if not item["stale"] and item["available"]]
    return next(
        (item for item in readable if item["preferred"]),
        next(
            (item for item in readable if "definition" in item["roles"]),
            next(
                (item for item in readable if item["group"] == "explanations"),
                readable[0] if readable else None,
            ),
        ),
    )


def _public(item: dict, *, detail: bool = False) -> dict:
    """Служебный ранг и полный текст не протекают в список."""
    hidden_keys = {"category", "group"} | (set() if detail else {"text"})
    return {
        key: value
        for key, value in item.items()
        if not key.startswith("_") and key not in hidden_keys
    }


def _topic_passages(session: Session, project_id: UUID, node_id: UUID) -> list[dict]:
    """Все опоры темы, свёрнутые в куски чтения, в порядке чтения."""
    rows = _binding_rows(session, project_id, node_id)
    fresh_ids = _fresh_binding_ids(session, project_id, [row[0] for row in rows])
    hidden = _decision_map(session, project_id, "hide_evidence")
    preferred = _decision_map(session, project_id, "prefer_reading").get(str(node_id))
    preferred_id = (preferred.payload or {}).get("binding_id") if preferred else None
    # Цитата куска берётся из текста фрагментов, поэтому тяжёлый JSON задач модели
    # (десятки килобайт на пакет) списку не нужен: он один давал секунды на тему.
    items = [
        _evidence_summary(
            row,
            fresh_ids=fresh_ids,
            hidden=hidden,
            preferred_binding_id=preferred_id,
        )
        for row in rows
    ]
    result = passages.build(session, project_id, node_id, items)
    result.sort(key=_passage_rank)
    return result


def _require_study_node(session: Session, project_id: UUID, node_id: UUID) -> ProgramNode:
    node = session.get(ProgramNode, node_id)
    if node is None or node.project_id != project_id or node.node_type not in STUDY_NODE_TYPES:
        raise ProjectNotFoundError("Тема программы не найдена")
    return node


def topic_evidence(session: Session, project_id: UUID, node_id: UUID) -> dict:
    """Опоры темы кусками чтения, сгруппированные по назначению.

    Единица выдачи — кусок (`passages.py`), а не фрагмент: одна карточка раньше
    была одной строкой, и урок приходилось собирать из десятков вставок.
    """
    project = require_project(session, project_id)
    node = _require_study_node(session, project_id, node_id)
    found = _topic_passages(session, project_id, node_id)
    content = [item for item in found if item["category"] == "content"]
    best = _starter(content)
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in found:
        if item["category"] != "content":
            group = item["category"]
        elif item is best:
            group = "starter"
        else:
            group = item["group"]
        groups[group].append(_public(item))
    return {
        "coverage_revision": project.coverage_revision,
        "topic_id": str(node.id),
        "topic_title": node.title,
        "best_evidence_id": best["id"] if best else None,
        **{name: groups[name] for name in (
            "starter", "explanations", "practice", "depth", "mentions", "hidden", "legacy"
        )},
    }


def _binding_for_evidence(session: Session, project_id: UUID, evidence_id: str) -> Binding:
    if evidence_id.startswith("binding:"):
        try:
            binding = session.get(Binding, UUID(evidence_id.removeprefix("binding:")))
        except ValueError:
            binding = None
        if binding is not None and binding.project_id == project_id:
            return binding
        raise ProjectNotFoundError("Опора не найдена")
    try:
        task_id, target_id, key = evidence_id.split(":")
        UUID(task_id)
        UUID(target_id)
    except (TypeError, ValueError):
        raise ProjectNotFoundError("Опора не найдена") from None
    binding = session.scalar(
        select(Binding).where(
            Binding.project_id == project_id,
            Binding.evidence_ref["task_id"].as_string() == task_id,
            Binding.evidence_ref["target_id"].as_string() == target_id,
            Binding.evidence_ref["key"].as_string() == key,
        )
    )
    if binding is not None:
        return binding
    raise ProjectNotFoundError("Опора не найдена")


def evidence_detail(session: Session, project_id: UUID, evidence_id: str) -> dict:
    """Вернуть исходный текст, границы и происхождение выбранной опоры."""
    require_project(session, project_id)
    binding = _binding_for_evidence(session, project_id, evidence_id)
    fragment = session.get(MaterialFragment, binding.fragment_id)
    page = session.get(MaterialPage, fragment.page_id) if fragment else None
    material = session.get(Material, binding.material_id)
    project_material = session.get(ProjectMaterial, (project_id, binding.material_id))
    node = session.get(ProgramNode, binding.program_node_id)
    if not fragment or not page or not material or not project_material or not node:
        raise ProjectNotFoundError("Опора больше недоступна")
    if evidence_id.startswith("binding:"):
        base = {
            "id": evidence_id,
            "key": str(binding.id),
            "ref": str(fragment.id),
            "quote": fragment.text,
            "description": "Ручная или прежняя привязка без семантической разметки.",
            "repair": "legacy",
            "start": 0,
            "end": len(fragment.text),
            "original_ref": None,
            "available": page.revision == material.active_parse_revision,
            "stale": page.revision != material.active_parse_revision,
            "origin": binding.mechanism.value,
            "applied": binding.status in ACTIVE_STATUSES,
            "locator": {},
        }
    else:
        base = queries.evidence_read(session, project_id, evidence_id)
    hidden = _decision_map(session, project_id, "hide_evidence").get(str(binding.id))
    preferred = _decision_map(session, project_id, "prefer_reading").get(str(node.id))
    single = {
        **base,
        "binding_id": str(binding.id),
        "binding_ids": [str(binding.id)],
        "member_ids": [evidence_id],
        "topic_id": str(node.id),
        "topic_title": node.title,
        "material_id": str(material.id),
        "material_name": project_material_display_name(material, project_material),
        "title": "",
        "page_from": page.page_number,
        "page_to": page.page_number,
        "from_fragment_id": str(fragment.id),
        "to_fragment_id": str(fragment.id),
        "fragment_ids": [str(fragment.id)],
        "fragment_count": 1,
        "text": base["quote"] or fragment.text,
        "roles": binding.roles or [],
        "semantic_kind": binding.semantic_kind,
        "status": binding.status.value,
        "mechanism": binding.mechanism.value,
        "quality": fragment.quality.value,
        "hidden": bool(hidden and hidden.payload.get("hidden")),
        "preferred": bool(preferred and preferred.payload.get("binding_id") == str(binding.id)),
        "legacy": binding.semantic_kind in {None, "unknown"},
    }
    # Снятая связь и тема-раздел кусков не образуют: инспектор показывает её одну.
    passage = None
    if binding.status in ACTIVE_STATUSES and node.node_type in STUDY_NODE_TYPES:
        passage = next(
            (
                item
                for item in _topic_passages(session, project_id, node.id)
                if str(binding.id) in item["binding_ids"]
            ),
            None,
        )
    detail = {**single, **_public(passage, detail=True)} if passage else single
    if passage:
        # Модельные поля опоры относятся к её первому фрагменту, а не ко всему куску.
        detail.update({key: base[key] for key in ("key", "ref", "repair", "start", "end")})
        detail["id"] = passage["id"]
    detail["linked_topics"] = _linked_topics(session, project_id, node.id, detail["fragment_ids"])
    return detail


def _linked_topics(
    session: Session, project_id: UUID, node_id: UUID, fragment_ids: list[str]
) -> list[dict]:
    """Другие темы, которые раскрывает тот же текст: кусок бывает общим для двух тем."""
    return [
        {"topic_id": str(other_id), "title": other_title}
        for other_id, other_title, _ in session.execute(
            select(ProgramNode.id, ProgramNode.title, ProgramNode.sort_order)
            .join(Binding, Binding.program_node_id == ProgramNode.id)
            .where(
                Binding.project_id == project_id,
                Binding.fragment_id.in_([UUID(item) for item in fragment_ids]),
                Binding.program_node_id != node_id,
                Binding.status.in_(ACTIVE_STATUSES),
                Binding.semantic_kind == "content",
            )
            .distinct()
            .order_by(ProgramNode.sort_order)
        )
    ]


def _request_hash(command: DecisionWrite) -> str:
    body = command.model_dump(mode="json", exclude={"request_key"})
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _decision(session: Session, project_id: UUID, kind: str, target_key: str):
    return session.scalar(
        select(CoverageDecision).where(
            CoverageDecision.project_id == project_id,
            CoverageDecision.kind == kind,
            CoverageDecision.target_key == target_key,
        )
    )


def _decision_snapshot(row: CoverageDecision | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "kind": row.kind,
        "target_key": row.target_key,
        "source_revision": row.source_revision,
        "anchor_fingerprint": row.anchor_fingerprint,
        "goal_fingerprint": row.goal_fingerprint,
        "payload": row.payload,
        "version": row.version,
        "action_id": row.action_id,
    }


def _binding_snapshot(row: Binding | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "program_node_id": str(row.program_node_id),
        "fragment_id": str(row.fragment_id),
        "material_id": str(row.material_id),
        "block_id": str(row.block_id) if row.block_id else None,
        "status": row.status.value,
        "roles": row.roles,
        "semantic_kind": row.semantic_kind,
        "evidence_ref": row.evidence_ref,
        "semantic_revision": row.semantic_revision,
        "mechanism": row.mechanism.value,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _target_fingerprint(
    session: Session,
    project_id: UUID,
    binding_ids: list[str],
    decision_keys: list[tuple[str, str]],
) -> str:
    return fingerprint(
        {
            "bindings": [
                _binding_snapshot(session.get(Binding, UUID(binding_id)))
                for binding_id in sorted(binding_ids)
            ],
            "decisions": [
                _decision_snapshot(_decision(session, project_id, kind, key))
                for kind, key in sorted(decision_keys)
            ],
        }
    )


def _put_decision(
    session: Session,
    project_id: UUID,
    kind: str,
    target_key: str,
    payload: dict,
) -> CoverageDecision:
    row = _decision(session, project_id, kind, target_key)
    if row is None:
        row = CoverageDecision(
            project_id=project_id,
            kind=kind,
            target_key=target_key,
            payload={},
            version=0,
        )
        session.add(row)
    row.payload = payload
    row.version += 1
    return row


def _put_reject_decision(
    session: Session, project_id: UUID, binding: Binding, rejected: bool
) -> CoverageDecision:
    """Запрет переносится по точному тексту, а не на весь изменившийся материал."""
    fragment = session.get(MaterialFragment, binding.fragment_id)
    page = session.get(MaterialPage, fragment.page_id) if fragment else None
    row = _put_decision(
        session,
        project_id,
        "reject_link",
        f"{binding.program_node_id}:{binding.fragment_id}",
        {
            "rejected": rejected,
            "topic_id": str(binding.program_node_id),
            "material_id": str(binding.material_id),
            "fragment_id": str(binding.fragment_id),
        },
    )
    row.source_revision = page.revision if page else None
    row.anchor_fingerprint = fingerprint(fragment.text) if fragment else None
    return row


def _require_binding(session: Session, project_id: UUID, command: DecisionWrite) -> Binding:
    if command.binding_id:
        binding = session.get(Binding, command.binding_id)
    elif command.evidence_id:
        binding = _binding_for_evidence(session, project_id, command.evidence_id)
    else:
        binding = None
    if binding is None or binding.project_id != project_id:
        raise ProjectNotFoundError("Связь не найдена")
    return binding


def _require_bindings(session: Session, project_id: UUID, command: DecisionWrite) -> list[Binding]:
    """Все привязки команды: кусок чтения передаёт их списком, одиночная — одну."""
    if not command.binding_ids:
        return [_require_binding(session, project_id, command)]
    ids = list(dict.fromkeys(command.binding_ids))
    found = {
        row.id: row
        for row in session.scalars(
            select(Binding).where(Binding.project_id == project_id, Binding.id.in_(ids))
        )
    }
    if len(found) != len(ids):
        raise ProjectNotFoundError("Связь не найдена")
    return [found[binding_id] for binding_id in ids]


def _has_link_target(command: DecisionWrite) -> bool:
    return bool(command.binding_ids or command.binding_id or command.evidence_id)


def _require_topics(session: Session, project_id: UUID, topic_ids: list[UUID]) -> list[ProgramNode]:
    if not topic_ids:
        raise ProjectDomainError(
            "Выберите хотя бы одну тему", status=422, code="coverage_topics_required"
        )
    nodes = [session.get(ProgramNode, node_id) for node_id in dict.fromkeys(topic_ids)]
    if any(
        node is None
        or node.project_id != project_id
        or node.node_type not in STUDY_NODE_TYPES
        or node.is_archived
        or not node.is_in_current_program
        for node in nodes
    ):
        raise ProjectNotFoundError("Тема программы не найдена")
    return nodes


def _block_fragments(session: Session, project_id: UUID, block_id: UUID) -> list[MaterialFragment]:
    block = session.get(MaterialBlock, block_id)
    if block is None or session.get(ProjectMaterial, (project_id, block.material_id)) is None:
        raise ProjectNotFoundError("Блок материала не найден")
    material = session.get(Material, block.material_id)
    if material is None or block.revision != material.active_parse_revision:
        raise ProjectConflictError(
            "Блок относится к прежней версии материала", code="coverage_block_stale"
        )
    return list(
        session.scalars(
            select(MaterialFragment)
            .where(MaterialFragment.block_id == block_id)
            .order_by(MaterialFragment.sort_order)
        )
    )


def _upsert_manual_binding(
    session: Session, project_id: UUID, topic_id: UUID, fragment: MaterialFragment
) -> Binding:
    binding = session.scalar(
        select(Binding).where(
            Binding.project_id == project_id,
            Binding.program_node_id == topic_id,
            Binding.fragment_id == fragment.id,
        )
    )
    if binding is None:
        binding = Binding(
            project_id=project_id,
            program_node_id=topic_id,
            fragment_id=fragment.id,
            material_id=fragment.material_id,
            block_id=fragment.block_id,
            status=BindingStatus.MANUAL,
            mechanism=BindingMechanism.MANUAL,
        )
        session.add(binding)
        session.flush()
    else:
        binding.status = BindingStatus.MANUAL
        binding.mechanism = BindingMechanism.MANUAL
    binding.semantic_kind = "content"
    binding.roles = ["explanation"]
    binding.semantic_revision = (binding.semantic_revision or 0) + 1
    binding.updated_at = utc_now()
    return binding


def _apply_link_action(
    session: Session,
    project_id: UUID,
    command: DecisionWrite,
    binding: Binding,
) -> tuple[list[Binding], list[tuple[str, str]], str]:
    """Изменить только выбранную связь и записать долговечное решение рядом."""
    keys: list[tuple[str, str]] = []
    if binding.status == BindingStatus.REMOVED and command.action in {
        "confirm",
        "change_role",
        "prefer",
    }:
        raise ProjectDomainError(
            "Сначала восстановите снятую связь",
            status=409,
            code="coverage_binding_removed",
        )
    if command.action == "confirm":
        binding.status = BindingStatus.CONFIRMED
        keys.append(("confirm_link", str(binding.id)))
        _put_decision(session, project_id, *keys[-1], {"confirmed": True})
        message = "Связь подтверждена."
    elif command.action in {"remove", "restore"}:
        removed = command.action == "remove"
        binding.status = BindingStatus.REMOVED if removed else BindingStatus.MANUAL
        keys.append(("reject_link", f"{binding.program_node_id}:{binding.fragment_id}"))
        _put_reject_decision(session, project_id, binding, removed)
        message = "Связь снята." if removed else "Связь восстановлена вручную."
    elif command.action == "change_role":
        if command.role is None:
            raise ProjectDomainError(
                "Выберите роль опоры", status=422, code="coverage_role_required"
            )
        binding.roles = [command.role]
        if command.semantic_kind is not None:
            binding.semantic_kind = command.semantic_kind
        binding.status = BindingStatus.CONFIRMED
        binding.semantic_revision = (binding.semantic_revision or 0) + 1
        keys.append(("link_role", str(binding.id)))
        _put_decision(
            session,
            project_id,
            *keys[-1],
            {"roles": binding.roles, "semantic_kind": binding.semantic_kind},
        )
        message = "Роль опоры изменена."
    elif command.action in {"hide", "show"}:
        keys.append(("hide_evidence", str(binding.id)))
        hidden = command.action == "hide"
        _put_decision(session, project_id, *keys[-1], {"hidden": hidden})
        message = "Опора скрыта из рекомендаций." if hidden else "Опора снова видна."
    elif command.action in {"prefer", "clear_prefer"}:
        keys.append(("prefer_reading", str(binding.program_node_id)))
        preferred = command.action == "prefer"
        _put_decision(
            session,
            project_id,
            *keys[-1],
            {"binding_id": str(binding.id) if preferred else None},
        )
        message = "Опора будет открываться первой." if preferred else "Личный приоритет снят."
    else:
        raise ProjectDomainError(
            "Действие не подходит для связи", status=422, code="coverage_decision_target"
        )
    binding.updated_at = utc_now()
    return [binding], keys, message


def _apply_reassign(
    session: Session, project_id: UUID, command: DecisionWrite
) -> tuple[list[Binding], list[tuple[str, str]], str]:
    """Переназначить точные фрагменты всем выбранным темам без частичного результата."""
    topics = _require_topics(session, project_id, command.topic_ids)
    olds = _require_bindings(session, project_id, command) if _has_link_target(command) else []
    fragments = (
        [session.get(MaterialFragment, old.fragment_id) for old in olds]
        if olds
        else _block_fragments(session, project_id, command.block_id)
        if command.block_id
        else []
    )
    if not fragments or any(fragment is None for fragment in fragments):
        raise ProjectNotFoundError("Точный фрагмент для переназначения не найден")
    touched: list[Binding] = []
    keys: list[tuple[str, str]] = []
    for old in olds:
        old.status = BindingStatus.REMOVED
        old.updated_at = utc_now()
        touched.append(old)
        keys.append(("reject_link", f"{old.program_node_id}:{old.fragment_id}"))
        _put_reject_decision(session, project_id, old, True)
    for topic in topics:
        for fragment in fragments:
            assert fragment is not None
            touched.append(_upsert_manual_binding(session, project_id, topic.id, fragment))
    return touched, keys, "Материал привязан к выбранным темам."


def _apply_block_action(
    session: Session, project_id: UUID, command: DecisionWrite
) -> tuple[list[Binding], list[tuple[str, str]], str]:
    if command.block_id is None:
        raise ProjectDomainError(
            "Не указан блок материала", status=422, code="coverage_block_required"
        )
    _block_fragments(session, project_id, command.block_id)
    disposition = "service" if command.action == "service" else "outside_program"
    key = ("block_disposition", str(command.block_id))
    _put_decision(session, project_id, *key, {"disposition": disposition})
    message = (
        "Блок отмечен как служебный."
        if disposition == "service"
        else "Блок отмечен как вне цели."
    )
    return [], [key], message


def _snapshots_for_keys(
    session: Session, project_id: UUID, keys: list[tuple[str, str]]
) -> dict[str, dict | None]:
    return {
        f"{kind}:{key}": _decision_snapshot(_decision(session, project_id, kind, key))
        for kind, key in keys
    }


def _prepare_reassign(
    session: Session, project_id: UUID, command: DecisionWrite
) -> tuple[dict[str, dict | None], dict[str, dict | None]]:
    """Зафиксировать все существующие связи диапазона до атомарного переназначения."""
    if _has_link_target(command):
        sources = _require_bindings(session, project_id, command)
        fragment_ids = [source.fragment_id for source in sources]
        decision_keys = [
            ("reject_link", f"{source.program_node_id}:{source.fragment_id}")
            for source in sources
        ]
    elif command.block_id:
        fragment_ids = [
            item.id for item in _block_fragments(session, project_id, command.block_id)
        ]
        decision_keys = []
    else:
        fragment_ids = []
        decision_keys = []
    candidate_ids = []
    if fragment_ids:
        candidate_ids = [
            str(item.id)
            for item in session.scalars(
                select(Binding).where(
                    Binding.project_id == project_id,
                    Binding.fragment_id.in_(fragment_ids),
                )
            )
        ]
    bindings = {
        binding_id: _binding_snapshot(session.get(Binding, UUID(binding_id)))
        for binding_id in candidate_ids
    }
    return bindings, _snapshots_for_keys(session, project_id, decision_keys)


def _apply_command(
    session: Session, project_id: UUID, command: DecisionWrite
) -> tuple[
    dict[str, dict | None],
    dict[str, dict | None],
    list[Binding],
    list[tuple[str, str]],
    str,
]:
    """Разрешить цель команды до изменения и вернуть единый набор данных для undo."""
    if command.action == "reassign":
        before_bindings, before_decisions = _prepare_reassign(
            session, project_id, command
        )
        touched, decision_keys, message = _apply_reassign(
            session, project_id, command
        )
        for row in touched:
            before_bindings.setdefault(str(row.id), None)
        return before_bindings, before_decisions, touched, decision_keys, message

    if command.action in {"service", "outside_goal"}:
        decision_keys = [("block_disposition", str(command.block_id))]
        before_decisions = _snapshots_for_keys(session, project_id, decision_keys)
        touched, decision_keys, message = _apply_block_action(
            session, project_id, command
        )
        return {}, before_decisions, touched, decision_keys, message

    bindings = _require_bindings(session, project_id, command)
    if command.action in {"prefer", "clear_prefer"}:
        # «Читать первой» — одна опора темы; кусок узнаётся по своей первой связи.
        bindings = bindings[:1]
    decision_keys = list(dict.fromkeys(_link_key(command.action, row) for row in bindings))
    before_bindings = {str(row.id): _binding_snapshot(row) for row in bindings}
    before_decisions = _snapshots_for_keys(session, project_id, decision_keys)
    touched: list[Binding] = []
    message = ""
    for row in bindings:
        changed, _, message = _apply_link_action(session, project_id, command, row)
        touched += changed
    if len(bindings) > 1:
        message = PASSAGE_MESSAGES.get(command.action, message)
    return before_bindings, before_decisions, touched, decision_keys, message


PASSAGE_MESSAGES = {
    "confirm": "Кусок подтверждён.",
    "remove": "Кусок снят с темы.",
    "restore": "Кусок снова привязан к теме.",
    "change_role": "Роль куска изменена.",
    "hide": "Кусок скрыт из рекомендаций.",
    "show": "Кусок снова виден.",
}


def _link_key(action: str, binding: Binding) -> tuple[str, str]:
    """Ключ долговечного решения, которое пишет действие над одной связью."""
    return {
        "confirm": ("confirm_link", str(binding.id)),
        "remove": ("reject_link", f"{binding.program_node_id}:{binding.fragment_id}"),
        "restore": ("reject_link", f"{binding.program_node_id}:{binding.fragment_id}"),
        "change_role": ("link_role", str(binding.id)),
        "hide": ("hide_evidence", str(binding.id)),
        "show": ("hide_evidence", str(binding.id)),
        "prefer": ("prefer_reading", str(binding.program_node_id)),
        "clear_prefer": ("prefer_reading", str(binding.program_node_id)),
    }[action]


def apply_decision(session: Session, project_id: UUID, command: DecisionWrite) -> dict:
    """Применить одну идемпотентную команду и записать один общий undo."""
    request_hash = _request_hash(command)
    with project_write_transaction(session, project_id):
        project = require_project(session, project_id, writable=True)
        receipt_row = _decision(session, project_id, "command_receipt", command.request_key)
        if receipt_row is not None:
            if receipt_row.payload.get("request_hash") != request_hash:
                raise ProjectConflictError(
                    "Ключ запроса уже использован для другой команды",
                    code="coverage_request_key_conflict",
                )
            return receipt_row.payload["receipt"]
        if project.coverage_revision != command.expected_coverage_revision:
            raise ProjectConflictError(
                "Покрытие уже изменилось; обновите данные",
                code="stale_coverage_revision",
                context={"coverage_revision": project.coverage_revision},
            )

        before_by_id, before_decisions, touched, decision_keys, message = _apply_command(
            session, project_id, command
        )

        session.flush()
        binding_ids = sorted({*before_by_id, *(str(row.id) for row in touched)})
        project.coverage_revision += 1
        action = ProjectActionLog(
            project_id=project_id,
            action_type="coverage_decision",
            phase="active",
            payload_version=1,
            target_title=message.rstrip("."),
            inverse_data={},
        )
        session.add(action)
        session.flush()
        for kind, key in decision_keys:
            row = _decision(session, project_id, kind, key)
            if row is not None:
                row.action_id = action.sequence
        session.flush()
        action.inverse_data = {
            "bindings": before_by_id,
            "decisions": before_decisions,
            "decision_keys": [[kind, key] for kind, key in decision_keys],
            "binding_ids": binding_ids,
            "after_fingerprint": _target_fingerprint(
                session, project_id, binding_ids, decision_keys
            ),
        }
        receipt = {
            "request_key": command.request_key,
            "action": command.action,
            "coverage_revision": project.coverage_revision,
            "action_sequence": action.sequence,
            "binding_ids": binding_ids,
            "message": message,
        }
        _put_decision(
            session,
            project_id,
            "command_receipt",
            command.request_key,
            {"request_hash": request_hash, "receipt": receipt},
        )
        session.flush()
        return receipt


def _restore_binding(session: Session, snapshot: dict | None, binding_id: str) -> None:
    """Восстановить снимок связи либо удалить созданную командой строку."""
    current = session.get(Binding, UUID(binding_id))
    if snapshot is None:
        if current is not None:
            session.delete(current)
        return
    if current is None:
        current = Binding(id=UUID(snapshot["id"]))
        session.add(current)
    current.project_id = UUID(snapshot["project_id"])
    current.program_node_id = UUID(snapshot["program_node_id"])
    current.fragment_id = UUID(snapshot["fragment_id"])
    current.material_id = UUID(snapshot["material_id"])
    current.block_id = UUID(snapshot["block_id"]) if snapshot["block_id"] else None
    current.status = BindingStatus(snapshot["status"])
    current.roles = snapshot["roles"]
    current.semantic_kind = snapshot["semantic_kind"]
    current.evidence_ref = snapshot["evidence_ref"]
    current.semantic_revision = snapshot["semantic_revision"]
    current.mechanism = BindingMechanism(snapshot["mechanism"])
    current.created_at = datetime.fromisoformat(snapshot["created_at"])
    current.updated_at = datetime.fromisoformat(snapshot["updated_at"])


def _restore_decision(
    session: Session, project_id: UUID, kind: str, key: str, snapshot: dict | None
) -> None:
    current = _decision(session, project_id, kind, key)
    if snapshot is None:
        if current is not None:
            session.delete(current)
        return
    if current is None:
        current = CoverageDecision(id=UUID(snapshot["id"]), project_id=project_id)
        session.add(current)
    current.kind = snapshot["kind"]
    current.target_key = snapshot["target_key"]
    current.source_revision = snapshot["source_revision"]
    current.anchor_fingerprint = snapshot["anchor_fingerprint"]
    current.goal_fingerprint = snapshot["goal_fingerprint"]
    current.payload = snapshot["payload"]
    current.version = snapshot["version"]
    current.action_id = snapshot["action_id"]


def apply_undo(session: Session, project_id: UUID, data: dict) -> None:
    """Отменить решение, только если затронутые строки не менялись после него."""
    decision_keys = [tuple(item) for item in data["decision_keys"]]
    current = _target_fingerprint(session, project_id, data["binding_ids"], decision_keys)
    if current != data["after_fingerprint"]:
        raise ProjectConflictError(
            "Связи уже изменились; автоматическая отмена небезопасна",
            code="coverage_undo_conflict",
        )
    for binding_id, snapshot in data["bindings"].items():
        _restore_binding(session, snapshot, binding_id)
    for kind, key in decision_keys:
        _restore_decision(
            session,
            project_id,
            kind,
            key,
            data["decisions"].get(f"{kind}:{key}"),
        )
    require_project(session, project_id).coverage_revision += 1
