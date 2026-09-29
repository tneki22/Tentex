"""Семантическая актуальность, manifest и чтение конкретной ревизии."""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.coverage.validation import Unit
from app.materials.image_meta import fragment_meta, has_readable_text
from app.materials.naming import project_material_display_name
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
    NodeType,
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


def topic_nodes(program: list[dict]) -> list[dict]:
    """Темы программы в снимке — то, что видит модель: в программе, не в архиве, не раздел.

    Один порядок для prompt, оценки, aliases и проверки актуальности запуска.
    """
    return [
        node
        for node in program
        if node["is_in_current_program"]
        and not node["is_archived"]
        and node["node_type"] != "section"
    ]


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
                "name": project_material_display_name(material, link),
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


@dataclass(frozen=True, slots=True)
class RunCurrency:
    """Что в снимке запуска ещё верно для чтения (правило актуальности, шаг 7.1).

    Правка программы не обесценивает исследование целиком: модель видела только список
    тем `{alias, title}`, поэтому связь к теме X из запуска актуальна, пока X в программе
    с тем же названием, сколько бы тем ни добавили рядом. Цели в запросе нет, и её смена
    ничего не устаревает. Источник актуален, пока не сменилась его активная ревизия.
    """

    active: bool
    stale_sources: frozenset[str]
    stale_topics: frozenset[str]

    def alive(self, material_id) -> bool:
        """Разбор источника не устарел: проект активен и ревизия та же."""
        return self.active and str(material_id) not in self.stale_sources

    def fresh(self, material_id, topic_id) -> bool:
        """Связь к теме актуальна: живой источник и тема на месте под прежним названием."""
        return self.alive(material_id) and str(topic_id) not in self.stale_topics


def runs_currency(session, runs) -> dict[UUID, RunCurrency]:
    """Актуальность истории проекта пачкой, по снимку каждого запуска.

    Программа, проекты и источники читаются по одному запросу на всю историю: на
    «Экономике» с десятью запусками и тремя тысячами связей поштучная проверка стоила
    минуту. Миграции не нужны — всё берётся из `CoverageRun.snapshot`.
    """
    if not runs:
        return {}
    project_ids = {run.project_id for run in runs}
    active = set(
        session.scalars(
            select(Project.id).where(
                Project.id.in_(project_ids), Project.status == ProjectStatus.ACTIVE
            )
        )
    )
    titles: dict[UUID, dict[str, str]] = defaultdict(dict)
    for project_id, node_id, title in session.execute(
        select(ProgramNode.project_id, ProgramNode.id, ProgramNode.title).where(
            ProgramNode.project_id.in_(project_ids),
            ProgramNode.is_in_current_program.is_(True),
            ProgramNode.is_archived.is_(False),
            ProgramNode.node_type != NodeType.SECTION,
        )
    ):
        titles[project_id][str(node_id)] = title
    source_ids = {UUID(source["id"]) for run in runs for source in run.snapshot["sources"]}
    revisions = dict(
        session.execute(
            select(Material.id, Material.active_parse_revision).where(Material.id.in_(source_ids))
        ).tuples().all()
    )
    linked = set(
        session.execute(
            select(ProjectMaterial.project_id, ProjectMaterial.material_id).where(
                ProjectMaterial.project_id.in_(project_ids),
                ProjectMaterial.material_id.in_(source_ids),
            )
        ).tuples()
    )
    result = {}
    for run in runs:
        current = titles[run.project_id]
        result[run.id] = RunCurrency(
            active=run.project_id in active,
            stale_sources=frozenset(
                source["id"]
                for source in run.snapshot["sources"]
                if (run.project_id, UUID(source["id"])) not in linked
                or revisions.get(UUID(source["id"])) != source["revision"]
            ),
            stale_topics=frozenset(
                node["id"]
                for node in topic_nodes(run.snapshot["program"])
                if current.get(node["id"]) != node["title"]
            ),
        )
    return result


def manifest_rows(session, snapshot, only=None):
    """Фиксирует состав, хеши и locators, не копируя весь текст книги.

    `only` — область доисследования: остальные блоки не получают строки в запуске,
    и их прежний результат остаётся в силе.
    """
    for source in snapshot["sources"]:
        blocks = session.scalars(
            select(MaterialBlock)
            .where(
                MaterialBlock.material_id == UUID(source["id"]),
                MaterialBlock.revision == source["revision"],
            )
            .order_by(MaterialBlock.sort_order)
        )
        by_block = material_units(session, UUID(source["id"]), source["revision"])
        for block in blocks:
            if only is not None and block.id not in only:
                continue
            units = by_block.get(str(block.id), {})
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


def _kind(fragment) -> str:
    """Вид фрагмента для прохода 2: изображение с проверяемым текстом — обычный абзац.

    Проход не смотрит картинок, поэтому любой `image` считался непросмотренным и снимал
    связь своего фрагмента (`visual_unavailable`). Описание модели, надпись в рисунке или
    ручная правка — такой же текст, как и остальной: его читают и цитируют. Рисунок без
    описания и заглушка остаются `image`.
    """
    if fragment.element_kind != "image":
        return fragment.element_kind
    meta = fragment_meta(
        fragment.visual, fragment.text, fragment.recognition_source, fragment.asset_path
    )
    return "paragraph" if has_readable_text(meta, fragment.text) else "image"


def _unit(fragment, page, material) -> Unit:
    """Адрес страницы содержит material ID: page:1 двух книг не совпадает."""
    return Unit(
        str(fragment.id),
        fragment.text,
        str(fragment.block_id),
        f"page:{fragment.material_id}:{page.page_number}",
        _kind(fragment),
        fragment.quality,
        _locator(fragment, page, material),
    )


def _units_query():
    return (
        select(MaterialFragment, MaterialPage, Material)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(Material, Material.id == MaterialFragment.material_id)
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
    )


def block_units(session, block_id) -> dict[str, Unit]:
    """Один блок: используется исполнителем, который читает пакет за пакетом."""
    rows = session.execute(_units_query().where(MaterialFragment.block_id == block_id))
    return {str(f.id): _unit(f, p, m) for f, p, m in rows}


def material_units(session, material_id, revision) -> dict[str, dict[str, Unit]]:
    """Все фрагменты ревизии одним запросом: книга на 900 блоков не даёт 900 обращений."""
    rows = session.execute(
        _units_query().where(
            MaterialFragment.material_id == material_id,
            MaterialPage.revision == revision,
        )
    )
    result: dict[str, dict[str, Unit]] = {}
    for fragment, page, material in rows:
        if fragment.block_id is None:
            continue
        result.setdefault(str(fragment.block_id), {})[str(fragment.id)] = _unit(
            fragment, page, material
        )
    return result


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
