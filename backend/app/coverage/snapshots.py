"""Семантическая актуальность, manifest и чтение конкретной ревизии."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select

from app.coverage.validation import Unit
from app.models import (
    Binding,
    BindingStatus,
    CoverageDecision,
    GoalPassport,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialRevision,
    MaterialState,
    ProgramNode,
    Project,
    ProjectMaterial,
    ProjectStatus,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError

GOAL_FIELDS = (
    "subject",
    "purpose",
    "scope",
    "starting_level",
    "current_knowledge",
    "target_outcome",
    "goal",
    "success_criterion",
    "important",
    "excluded",
    "study_format",
    "instructor_requirements",
    "tree_detail",
)
NODE_FIELDS = (
    "id",
    "title",
    "node_type",
    "section_purpose",
    "goal_role",
    "target_level",
    "is_in_current_program",
    "is_archived",
)


def fingerprint(value) -> str:
    """Стабильный хеш значений, без display order и случайного порядка SQL."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def require_project(session, project_id, *, writable=False):
    """Единая граница принадлежности и доступности проекта."""
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError()
    if writable and project.status != ProjectStatus.ACTIVE:
        raise ProjectConflictError(
            "Исследование доступно активному проекту", code="coverage_project_not_active"
        )
    return project


def semantic_snapshot(session, project_id) -> dict:
    """Цель и программа сохраняются для объяснения исторического результата."""
    goal = session.get(GoalPassport, project_id)
    nodes = list(
        session.scalars(
            select(ProgramNode).where(ProgramNode.project_id == project_id).order_by(ProgramNode.id)
        )
    )
    return {
        "goal": {name: getattr(goal, name) for name in GOAL_FIELDS} if goal else {},
        "program": [
            {
                name: str(getattr(n, name)) if name == "id" else getattr(n, name)
                for name in NODE_FIELDS
            }
            for n in nodes
        ],
    }


def decisions_fingerprint(session, project_id) -> str:
    """Машинные публикации не инвалидируют собственный запуск, личные действия — да."""
    bindings = session.scalars(
        select(Binding)
        .where(
            Binding.project_id == project_id,
            Binding.status.in_(
                [BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.REMOVED]
            ),
        )
        .order_by(Binding.id)
    )
    decisions = session.scalars(
        select(CoverageDecision)
        .where(CoverageDecision.project_id == project_id)
        .order_by(CoverageDecision.id)
    )
    return fingerprint(
        {
            "bindings": [
                (
                    str(b.id),
                    str(b.fragment_id),
                    b.status,
                    b.roles,
                    b.semantic_kind,
                    str(b.updated_at),
                )
                for b in bindings
            ],
            "decisions": [(str(d.id), d.version, d.payload) for d in decisions],
        }
    )


def source_snapshot(session, project_id, ids, *, require_ready=True) -> list[dict]:
    """Только подключённые готовые версии, включая отдельно выбранный контекст."""
    result = []
    for material_id in sorted(set(ids), key=str):
        material = session.get(Material, material_id)
        link = session.get(ProjectMaterial, (project_id, material_id))
        if not material or not link:
            raise ProjectConflictError("Источник не подключён", code="coverage_scope_denied")
        if (
            require_ready and material.status != MaterialState.READY
        ) or not material.active_parse_revision:
            raise ProjectConflictError("Источник ещё не готов", code="coverage_source_not_ready")
        revision = session.scalar(
            select(MaterialRevision).where(
                MaterialRevision.material_id == material_id,
                MaterialRevision.revision == material.active_parse_revision,
            )
        )
        diagnostics = revision.summary if revision else {}
        result.append(
            {
                "id": str(material_id),
                "name": link.display_name or material.original_name,
                "source_role": link.source_role,
                "purposes": link.purposes,
                "revision": material.active_parse_revision,
                "diagnostics": diagnostics,
                "diagnostics_fingerprint": fingerprint(diagnostics),
            }
        )
    return result


def build_snapshot(session, project_id, plan) -> tuple[dict, dict]:
    """Один снимок для preflight и запуска; models-disabled ему не мешает."""
    project = require_project(session, project_id, writable=True)
    if project.program_revision != plan.expected_program_revision:
        raise ProjectConflictError("Программа изменилась", code="coverage_snapshot_changed")
    snapshot = semantic_snapshot(session, project_id)
    snapshot["sources"] = source_snapshot(session, project_id, plan.material_ids)
    snapshot["context_sources"] = source_snapshot(session, project_id, plan.context_material_ids)
    fingerprints = {
        "semantic": fingerprint({k: snapshot[k] for k in ("goal", "program")}),
        "sources": fingerprint(snapshot["sources"] + snapshot["context_sources"]),
        "decisions": decisions_fingerprint(session, project_id),
    }
    return snapshot, fingerprints


def snapshot_current(session, run) -> bool:
    """Консервативная инвалидизация: неизвестное влияние требует нового запуска."""
    project = session.get(Project, run.project_id)
    if project is None or project.status != ProjectStatus.ACTIVE:
        return False
    if fingerprint(semantic_snapshot(session, run.project_id)) != run.fingerprints["semantic"]:
        return False
    try:
        sources = source_snapshot(
            session,
            run.project_id,
            [UUID(s["id"]) for s in run.snapshot["sources"]],
            require_ready=False,
        )
        context = source_snapshot(
            session,
            run.project_id,
            [UUID(s["id"]) for s in run.snapshot["context_sources"]],
            require_ready=False,
        )
    except ProjectConflictError:
        return False
    return fingerprint(sources + context) == run.fingerprints["sources"]


def manifest_rows(session, snapshot):
    """Фиксирует состав, хеши и locators, не копируя весь текст книги."""
    for source in snapshot["sources"]:
        blocks = session.scalars(
            select(MaterialBlock)
            .where(
                MaterialBlock.material_id == UUID(source["id"]),
                MaterialBlock.revision == source["revision"],
            )
            .order_by(MaterialBlock.sort_order)
        )
        for block in blocks:
            units = block_units(session, block.id)
            yield (
                block,
                {
                    "title": block.title,
                    "section_path": block.title,
                    "block_class": block.block_class,
                    "service_reason": block.service_reason,
                    "page_from": block.page_from,
                    "page_to": block.page_to,
                    "fragments": [
                        {
                            "id": u.ref,
                            "hash": fingerprint(u.text),
                            "length": len(u.text),
                            "page_ref": u.page_ref,
                            "kind": u.kind,
                            "quality": u.quality,
                            "locator": u.locator,
                        }
                        for u in units.values()
                    ],
                    "diagnostics_fingerprint": source["diagnostics_fingerprint"],
                },
            )


def block_units(session, block_id) -> dict[str, Unit]:
    """Адрес страницы содержит material ID: page:1 двух книг не совпадает."""
    rows = session.execute(
        select(MaterialFragment, MaterialPage, Material)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(Material, Material.id == MaterialFragment.material_id)
        .where(MaterialFragment.block_id == block_id)
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
    )
    return {
        str(f.id): Unit(
            str(f.id),
            f.text,
            str(f.block_id),
            f"page:{f.material_id}:{p.page_number}",
            f.element_kind,
            f.quality,
            _locator(f, p, m),
        )
        for f, p, m in rows
    }


def _locator(fragment, page, material):
    physical = material.media_type == "application/pdf" or material.source_kind == "typst"
    kind = "time" if fragment.time_from is not None else ("page" if physical else "logical_element")
    # Fragment пока не хранит bbox_reliable: не приписывать точность по одной форме bbox.
    return {
        "kind": kind,
        "material_id": str(material.id),
        "revision": page.revision,
        "page_number": page.page_number,
        "fragment_id": str(fragment.id),
        "bbox": fragment.bbox,
        "bbox_reliable": False,
        "time_from": fragment.time_from,
        "time_to": fragment.time_to,
        "recognition_source": fragment.recognition_source,
    }
