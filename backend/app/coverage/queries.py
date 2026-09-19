"""Текущие агрегаты и исторические receipts: состояние job не подменяет покрытие."""

from collections import Counter
from uuid import UUID

from sqlalchemy import select

from app.coverage.budget import budget_usage
from app.coverage.lifecycle import require_run
from app.coverage.snapshots import require_project, snapshot_current
from app.models import (
    BackgroundJob,
    Binding,
    BindingStatus,
    CoverageBlockResult,
    CoverageDecision,
    CoverageFinding,
    CoverageRun,
    CoverageTask,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialRevision,
    NodeType,
    ProgramNode,
    Project,
    ProjectMaterial,
)
from app.projects.errors import ProjectNotFoundError

BUCKETS = (
    "linked",
    "outside_program",
    "service",
    "mixed_resolved",
    "unresolved",
    "pending",
    "processing",
    "error",
    "stale",
)
# Исход, по которому пользователь может что-то сделать: уточнить, повторить или перепроверить.
# Порядок задаёт и ленту: сбой повторяем, нерешённое уточняем, устаревшее ждёт запуска.
ISSUE_BUCKETS = ("error", "unresolved", "stale")


def run_read(session, project_id, run_id):
    """Исторический знаменатель неизменен, incomplete не превращается в 100%."""
    run = require_run(session, project_id, run_id)
    job = session.get(BackgroundJob, run.job_id)
    rows = list(
        session.scalars(select(CoverageBlockResult).where(CoverageBlockResult.run_id == run.id))
    )
    work = Counter(r.work_state for r in rows)
    outcomes = Counter(r.outcome for r in rows if r.work_state == "inspected")
    tasks = list(session.scalars(select(CoverageTask).where(CoverageTask.run_id == run.id)))
    return {
        "id": str(run.id),
        "job_id": str(job.id),
        "state": job.state,
        "execution_generation": run.execution_generation,
        "stop_reason": run.stop_reason,
        "snapshot": run.snapshot,
        "fingerprints": run.fingerprints,
        "stale": not snapshot_current(session, run),
        "primary": {
            "total": len(rows),
            **{k: work[k] for k in ("pending", "processing", "inspected", "error")},
        },
        "outcomes": {k: outcomes[k] for k in BUCKETS[:5]},
        "research": {
            "discovered": sum(t.kind == "refine" for t in tasks),
            "finished": sum(t.kind == "refine" and t.state == "finished" for t in tasks),
        },
        "pending_synthesis": sum(t.kind == "synthesis" and t.state != "finished" for t in tasks),
        "costs": budget_usage(session, run.id),
        "limits": run.limits,
        "pause_requested": job.pause_requested,
    }


def _current_runs(session, project_id):
    runs = list(
        session.scalars(
            select(CoverageRun)
            .where(
                CoverageRun.project_id == project_id,
                CoverageRun.mode.in_(["initial", "incremental"]),
            )
            .order_by(CoverageRun.created_at.desc())
        )
    )
    return runs, {r.id: snapshot_current(session, r) for r in runs}


def binding_fresh(session, binding, current):
    """Позиционный перенос не делает старое evidence новым, даже при прежнем Binding ID."""
    ref = binding.evidence_ref
    if not ref:
        return binding.status in {BindingStatus.MANUAL, BindingStatus.CONFIRMED}
    task = session.get(CoverageTask, UUID(ref["task_id"])) if ref.get("task_id") else None
    if not task or not current.get(task.run_id, False) or ref.get("retired_reason"):
        return False
    receipt = task.result.get(ref["target_id"])
    if not receipt or not receipt["applied"]:
        return False
    return any(
        link["fragment_id"] == str(binding.fragment_id) for link in receipt["decision"]["links"]
    )


def _active_blocks(session, project_id):
    return list(
        session.scalars(
            select(MaterialBlock)
            .join(Material, Material.id == MaterialBlock.material_id)
            .join(ProjectMaterial, ProjectMaterial.material_id == Material.id)
            .where(
                ProjectMaterial.project_id == project_id,
                MaterialBlock.revision == Material.active_parse_revision,
            )
            .order_by(MaterialBlock.material_id, MaterialBlock.sort_order)
        )
    )


def _select_results(session, runs, current):
    """Поздний pending/failed не заслоняет совместимый проверенный результат."""
    selected, latest, reviewed = {}, {}, set()
    for run in runs:
        for row in session.scalars(
            select(CoverageBlockResult).where(CoverageBlockResult.run_id == run.id)
        ):
            previous = latest.get(row.block_id)
            if previous is None or (
                previous.work_state != "inspected" and row.work_state == "inspected"
            ):
                latest[row.block_id] = row
            if row.work_state == "inspected" and not current[run.id]:
                reviewed.add(row.material_id)
            if current[run.id] and row.publication_state == "applied":
                selected.setdefault(row.block_id, row)
    return selected, latest, reviewed


def _unfinished_bucket(block, previous, current, reviewed):
    """Устаревшим блок делает прежний разбор, а не сам факт брошенного запуска.

    Блок, который ни один запуск не рассмотрел, остаётся нерассмотренным: иначе
    подключённый, но ни разу не исследованный учебник целиком попадает в
    «устарели» и вытесняет настоящие проблемы из ленты.
    """
    if previous is None:
        return "stale" if block.material_id in reviewed else "pending"
    if not current[previous.run_id]:
        return "stale" if previous.work_state == "inspected" else "pending"
    return "unresolved" if previous.work_state == "inspected" else previous.work_state


def current_map(session, project_id):
    """Один серверный расчёт для будущих overview/matrix/graph."""
    require_project(session, project_id)
    runs, current = _current_runs(session, project_id)
    selected, latest, reviewed = _select_results(session, runs, current)
    bindings = list(
        session.scalars(
            select(Binding)
            .join(MaterialFragment, MaterialFragment.id == Binding.fragment_id)
            .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
            .join(Material, Material.id == Binding.material_id)
            .join(ProjectMaterial, ProjectMaterial.material_id == Material.id)
            .where(
                Binding.project_id == project_id,
                ProjectMaterial.project_id == project_id,
                MaterialPage.revision == Material.active_parse_revision,
                Binding.status.in_(
                    [BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE]
                ),
            )
        )
    )
    fresh = [b for b in bindings if binding_fresh(session, b, current)]
    material_names = {
        material_id: display_name or original_name
        for material_id, display_name, original_name in session.execute(
            select(
                ProjectMaterial.material_id,
                ProjectMaterial.display_name,
                Material.original_name,
            )
            .join(Material, Material.id == ProjectMaterial.material_id)
            .where(ProjectMaterial.project_id == project_id)
        )
    }
    result = []
    block_choices = {
        row.target_key: row.payload.get("disposition")
        for row in session.scalars(
            select(CoverageDecision).where(
                CoverageDecision.project_id == project_id,
                CoverageDecision.kind == "block_disposition",
            )
        )
    }
    for block in _active_blocks(session, project_id):
        row = selected.get(block.id)
        related = [b for b in fresh if b.block_id == block.id]
        content = [b for b in related if b.semantic_kind == "content"]
        manual_content = [
            binding
            for binding in content
            if binding.status in {BindingStatus.MANUAL, BindingStatus.CONFIRMED}
        ]
        if block_choices.get(str(block.id)) in {"service", "outside_program"}:
            bucket = block_choices[str(block.id)]
        elif manual_content:
            bucket = "linked"
        elif row:
            bucket = _project_outcome(row, related)
        else:
            bucket = _unfinished_bucket(block, latest.get(block.id), current, reviewed)
        result.append(
            {
                "block_id": str(block.id),
                "material_id": str(block.material_id),
                "revision": block.revision,
                "bucket": bucket,
                "has_content": bool(content),
                "result_id": str(row.id) if row else None,
                "title": block.title,
                "page_from": block.page_from,
                "page_to": block.page_to,
                "material_name": material_names[block.material_id],
                "reason": row.reason if row else None,
            }
        )
    return result, fresh


def _project_outcome(row, bindings):
    """Ручное снятие меняет текущую проекцию, не исторический ответ модели."""
    dispositions = row.result["dispositions"]
    for part in dispositions:
        if part["outcome"] in {"content", "mention", "context"} and not any(
            str(b.fragment_id) == part["fragment_id"] and b.semantic_kind == part["outcome"]
            for b in bindings
        ):
            return "unresolved"
    return row.outcome


def overview(session, project_id):
    """Покрытие меньше 100% — распределение результата, не признак ошибки."""
    project = require_project(session, project_id)
    blocks, bindings = current_map(session, project_id)
    counts = Counter(b["bucket"] for b in blocks)
    nodes = list(
        session.scalars(
            select(ProgramNode).where(
                ProgramNode.project_id == project_id,
                ProgramNode.node_type != NodeType.SECTION,
                ProgramNode.is_in_current_program.is_(True),
                ProgramNode.is_archived.is_(False),
            )
        )
    )
    node_ids = {n.id for n in nodes}
    titles = {n.id: n.title for n in nodes}
    content = {b.program_node_id for b in bindings if b.semantic_kind == "content"} & node_ids
    reading = {
        b.program_node_id
        for b in bindings
        if b.semantic_kind == "content" and set(b.roles or []) & {"definition", "explanation"}
    } & node_ids
    numerator = counts["linked"] + counts["mixed_resolved"]
    denominator = numerator + counts["outside_program"]
    sources = list(
        session.execute(
            select(Material, ProjectMaterial.display_name)
            .join(ProjectMaterial, ProjectMaterial.material_id == Material.id)
            .where(ProjectMaterial.project_id == project_id)
        )
    )
    runs, _ = _current_runs(session, project_id)
    latest = runs[0] if runs else None
    latest_job = session.get(BackgroundJob, latest.job_id) if latest else None
    latest_scope = {s["id"] for s in latest.snapshot["sources"]} if latest else set()
    by_material = Counter((item["material_id"], item["bucket"]) for item in blocks)
    source_rows = []
    for material, display_name in sources:
        revision = session.scalar(
            select(MaterialRevision).where(
                MaterialRevision.material_id == material.id,
                MaterialRevision.revision == material.active_parse_revision,
            )
        )
        diagnostics = (revision.summary if revision else {}) or {}
        source_rows.append(
            {
                "id": str(material.id),
                "name": display_name or material.original_name,
                "revision": material.active_parse_revision,
                "total": sum(by_material[(str(material.id), bucket)] for bucket in BUCKETS),
                "distribution": {
                    bucket: by_material[(str(material.id), bucket)] for bucket in BUCKETS
                },
                "diagnostics": diagnostics,
                "known_limits": _known_extraction_limits(material),
                # Источник проекта и область последнего запуска — разные вещи.
                "in_latest_run": str(material.id) in latest_scope,
            }
        )
    return {
        "coverage_revision": project.coverage_revision,
        "program_revision": project.program_revision,
        "source_revisions": {
            str(material.id): material.active_parse_revision for material, _ in sources
        },
        "partial": bool(
            counts["pending"] + counts["processing"] + counts["error"] + counts["stale"]
        ),
        "total": len(blocks),
        "distribution": {k: counts[k] for k in BUCKETS},
        "topics": {
            "total": len(nodes),
            "with_content": len(content),
            "reading_basis": len(reading),
            "legacy": len(
                {b.program_node_id for b in bindings if b.semantic_kind in {None, "unknown"}}
                & node_ids
            ),
        },
        # Число без названий нечитаемо: «6 тем» не говорит, каких именно.
        "content_titles": _titles(content, titles),
        "reading_titles": _titles(reading, titles),
        "material_ratio": {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
            "label": "Среди разобранных",
            "mixed": counts["mixed_resolved"],
        },
        "findings": len(
            list(
                session.scalars(
                    select(CoverageFinding.id).where(
                        CoverageFinding.project_id == project_id,
                        CoverageFinding.state == "proposed",
                    )
                )
            )
        ),
        "latest_run_id": str(latest.id) if latest else None,
        "latest_run_state": latest_job.state if latest_job else None,
        "sources": source_rows,
    }


# Сколько названий тем экран показывает под числом, не превращаясь в список программы.
TITLE_SAMPLE = 24


def _titles(ids, titles) -> list[str]:
    """Названия в порядке программы; длинный список отсекается по TITLE_SAMPLE."""
    return sorted(titles[node_id] for node_id in ids)[:TITLE_SAMPLE]


def _known_extraction_limits(material):
    """И0а ещё не выполнен: экран обязан честно показать известные границы адаптера."""
    limits = []
    name = material.original_name.casefold()
    if name.endswith(".docx"):
        limits.append("docx_tables_not_enumerated")
    if name.endswith((".md", ".markdown")):
        limits.append("markdown_fenced_heading_risk")
    if material.source_kind == "youtube":
        limits.append("youtube_timestamps_not_preserved")
    limits.append("bbox_reliability_not_preserved")
    return limits


def _page(rows, offset, limit, coverage_revision):
    return {
        "coverage_revision": coverage_revision,
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "distribution": dict(Counter(row["bucket"] for row in rows)),
    }


def source_blocks(session, project_id, material_id, offset, limit):
    """Ограниченная лента текущих блоков с явным остатком."""
    blocks, _ = current_map(session, project_id)
    revision = session.get(Project, project_id).coverage_revision
    return _page(
        [b for b in blocks if b["material_id"] == str(material_id)],
        offset,
        limit,
        revision,
    )


def issue_blocks(session, project_id, offset, limit):
    """Отдельная лента требующих внимания блоков: экран не выкачивает весь проект ради списка."""
    blocks, _ = current_map(session, project_id)
    rows = [b for b in blocks if b["bucket"] in ISSUE_BUCKETS]
    # Сначала то, с чем можно что-то сделать сейчас: устаревшее ждёт нового запуска
    # и не должно вытеснять сбои и нерешённые блоки с первой страницы.
    rows.sort(key=lambda row: ISSUE_BUCKETS.index(row["bucket"]))
    return _page(rows, offset, limit, session.get(Project, project_id).coverage_revision)


def evidence_read(session, project_id, evidence_id):
    """ID = task UUID:target UUID:local key, цитата не участвует в идентичности."""
    try:
        task_id, target_id, key = evidence_id.split(":")
        task = session.get(CoverageTask, UUID(task_id))
        UUID(target_id)
    except (ValueError, TypeError):
        raise ProjectNotFoundError("Опора не найдена") from None
    if task is None:
        raise ProjectNotFoundError("Опора не найдена")
    run = session.get(CoverageRun, task.run_id)
    require_run(session, project_id, run.id)
    receipt = task.result.get(target_id)
    decision = receipt["decision"] if receipt else {}
    evidence = next(
        (
            e
            for item in decision.get("links", []) + decision.get("findings", [])
            for e in item["evidence"]
            if e["key"] == key
        ),
        None,
    )
    if evidence is None:
        raise ProjectNotFoundError("Опора не найдена")
    ref = evidence["ref"]
    if ref.startswith("page:"):
        _, material_id, page_number = ref.split(":")
        source = next(
            s
            for s in run.snapshot["sources"] + run.snapshot["context_sources"]
            if s["id"] == material_id
        )
        available = (
            session.scalar(
                select(MaterialPage.id).where(
                    MaterialPage.material_id == UUID(material_id),
                    MaterialPage.revision == source["revision"],
                    MaterialPage.page_number == int(page_number),
                )
            )
            is not None
        )
    else:
        available = session.get(MaterialFragment, UUID(ref)) is not None
    return {
        "id": evidence_id,
        **evidence,
        "available": available,
        "stale": not snapshot_current(session, run),
        "origin": decision.get("origin"),
        "applied": receipt["applied"],
    }
