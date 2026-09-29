"""Кандидаты материала для модельного урока — этап B, без вызова модели.

Куски, выбранные человеком, идут первыми, и тогда урок строится из них одних; иначе
три источника в порядке доверия: диапазон темы по оглавлению (уточнённый
`boundaries`), опоры темы (ручные и содержательные привязки, в том числе
прохода 2) и общий поиск `HybridRetriever` по выбранным материалам. Фрагмент
принадлежит первому кандидату, который его взял: дубли не повторяются, а
сигналы копятся. Большой блок режется на части по фрагментам, чтобы кусок
можно было и прочитать моделью, и вставить в урок точной ссылкой.

Поиск здесь — единственное место, где урок зовёт `HybridRetriever`: изменения
порога релевантности и `no_relevant_match` подхватываются тут, а не во всех вызовах.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings.service import topic_support
from app.lessons import boundaries
from app.lessons import refs as refs_module
from app.lessons.service import (
    ROLE_ORDER,
    _load_program,
    _plan_source,
    _Program,
    _source_name,
)
from app.materials.image_meta import DESCRIBABLE_PROCESSING
from app.models import (
    BindingMechanism,
    BindingStatus,
    BlockClass,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    PageQuality,
    ProgramNode,
    ProjectMaterial,
    SourceRole,
)
from app.projects.errors import ProjectDomainError
from app.retrieval.chunking import count_tokens
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite, SearchStrategy
from app.retrieval.search import HybridRetriever
from app.retrieval.vector import fuse_rankings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.lessons.ai_schemas import LessonPinnedRange

#: Сигнал куска, который человек выбрал сам: он обязателен для урока, не вытесняется
#: лимитом и поиском и не теряется как дубль другого материала.
PINNED_SIGNAL = "выбрано человеком"
#: Вес выбранного куска выше любого автоматического сигнала (оглавление — 1,0).
PINNED_SCORE = 1.1
#: Столько кусков модель ещё сопоставляет между собой; больше — шум.
MAX_CANDIDATES = 30
#: Кусок крупнее режется по фрагментам: его должно быть можно прочитать целиком.
PART_TOKENS = 1_200
SEARCH_LIMIT = 12
#: Вес роли материала: основной источник важнее справочного при равных сигналах.
ROLE_WEIGHT = {SourceRole.MAIN: 1.0, SourceRole.ADDITIONAL: 0.8, SourceRole.REFERENCE: 0.6}
OCR_LOW_PENALTY = 0.85
SIGNAL_WEIGHT = {
    "outline": 1.0,
    BindingStatus.MANUAL: 0.95,
    BindingStatus.CONFIRMED: 0.9,
    BindingStatus.MACHINE: 0.7,
}
MECHANISM_LABEL = {
    BindingMechanism.MANUAL: "вручную",
    BindingMechanism.SEARCH: "из поиска",
    BindingMechanism.ANSWERS_FILE: "файл ответов",
    BindingMechanism.PASS_TWO: "проход 2",
    BindingMechanism.LESSON: "урок",
    BindingMechanism.OUTLINE: "оглавление",
}
STATUS_LABEL = {
    BindingStatus.MANUAL: "ручная",
    BindingStatus.CONFIRMED: "подтверждённая",
    BindingStatus.MACHINE: "машинная",
}
EXERCISE_TITLE = re.compile(
    r"вопросы\s+(?:для|к)\s+самопровер|контрольн\w*\s+вопрос|упражнени|задач|задани|практикум",
    re.IGNORECASE,
)
FORMULA = re.compile(r"\$[^$]+\$|\\\(|\\\[")


@dataclass
class Candidate:
    """Кусок материала, который модель может положить в урок или на который опереться.

    Границы — первый и последний фрагмент в порядке чтения: ровно их урок и
    сохранит ссылкой (`refs.fragment_range`), поэтому модель не может сослаться
    на то, чего в её контексте не было (FR-L10).
    """

    material_id: UUID
    material_name: str
    role: SourceRole
    priority: int
    block_id: UUID | None
    title: str | None
    page_from: int
    page_to: int
    fragment_ids: list[UUID]
    text: str
    tokens: int
    score: float
    signals: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    also_in: list[str] = field(default_factory=list)
    time_from: float | None = None
    time_to: float | None = None
    in_outline: bool = False

    @property
    def pinned(self) -> bool:
        """Кусок выбран человеком: урок обязан его содержать."""
        return PINNED_SIGNAL in self.signals

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["material_id"] = str(self.material_id)
        data["block_id"] = str(self.block_id) if self.block_id else None
        data["fragment_ids"] = [str(item) for item in self.fragment_ids]
        data["role"] = self.role.value
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Candidate:
        return cls(**{
            **data,
            "material_id": UUID(data["material_id"]),
            "block_id": UUID(data["block_id"]) if data.get("block_id") else None,
            "fragment_ids": [UUID(item) for item in data["fragment_ids"]],
            "role": SourceRole(data["role"]),
        })


@dataclass(frozen=True)
class _Row:
    fragment_id: UUID
    block_id: UUID
    block_title: str | None
    page: int
    order: int
    text: str
    kind: str
    quality: PageQuality
    visual: dict[str, Any] | None
    time_from: float | None
    time_to: float | None


@dataclass
class CandidateSet:
    candidates: list[Candidate]
    #: Есть ли у темы диапазон по оглавлению хотя бы в одном выбранном материале.
    has_outline: bool
    searched: bool
    search_notes: list[str]
    #: Сколько кусков выбрал человек (заказ `pinned`); их кандидаты идут первыми.
    pinned: int = 0


@dataclass
class _Source:
    material: Material
    link: ProjectMaterial
    name: str


# --- чтение фрагментов -----------------------------------------------------------------


def _rows(session: Session, material: Material, fragment_ids: set[UUID]) -> list[_Row]:
    """Фрагменты содержательных блоков активной ревизии в порядке чтения."""
    if not fragment_ids:
        return []
    rows = session.execute(
        select(
            MaterialFragment.id, MaterialFragment.block_id, MaterialBlock.title,
            MaterialPage.page_number, MaterialFragment.sort_order, MaterialFragment.text,
            MaterialFragment.element_kind, MaterialFragment.quality, MaterialFragment.visual,
            MaterialFragment.time_from, MaterialFragment.time_to,
        )
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(
            MaterialFragment.id.in_(list(fragment_ids)),
            MaterialPage.material_id == material.id,
            MaterialPage.revision == material.active_parse_revision,
            MaterialBlock.block_class == BlockClass.CONTENT,
        )
    ).tuples().all()
    return sorted((_Row(*row) for row in rows), key=lambda row: (row.page, row.order))


def _fragment_text(row: _Row, figures: list[str]) -> str | None:
    """Текст фрагмента для модели; рисунок без описания — называется, а не выдумывается."""
    if row.kind != "image":
        return row.text.strip() or None
    visual = row.visual or {}
    if visual.get("role") in {"service", "decorative"}:
        return None
    if visual.get("processing") in DESCRIBABLE_PROCESSING or not row.text.strip():
        figures.append(f"рисунок без описания, стр. {row.page}")
        return f"[Рисунок без описания, стр. {row.page} — ссылайся на страницу]"
    return f"[Рисунок, стр. {row.page}] {row.text.strip()}"


def _group_rows(rows: list[_Row]) -> list[list[_Row]]:
    """Подряд идущие фрагменты одного блока — одна группа; крупная режется на части."""
    groups: list[list[_Row]] = []
    for row in rows:
        if groups and groups[-1][-1].block_id == row.block_id:
            groups[-1].append(row)
        else:
            groups.append([row])
    parts: list[list[_Row]] = []
    for group in groups:
        current: list[_Row] = []
        size = 0
        for row in group:
            tokens = count_tokens(row.text)
            if current and size + tokens > PART_TOKENS:
                parts.append(current)
                current, size = [], 0
            current.append(row)
            size += tokens
        if current:
            parts.append(current)
    return parts


def _candidate(source: _Source, rows: list[_Row], score: float, signal: str) -> Candidate | None:
    figures: list[str] = []
    texts = [text for row in rows if (text := _fragment_text(row, figures))]
    if not texts:
        return None
    text = "\n\n".join(texts)
    flags: list[str] = []
    title = rows[0].block_title
    if title and EXERCISE_TITLE.search(title):
        flags.append("упражнения")
    if FORMULA.search(text) or any(row.kind == "formula" for row in rows):
        flags.append("формулы")
    if any(row.kind == "table" for row in rows):
        flags.append("таблица")
    if any(row.quality == PageQuality.OCR_LOW for row in rows):
        flags.append("OCR низкого качества — сверяться со страницей")
        score *= OCR_LOW_PENALTY
    times = [row.time_from for row in rows if row.time_from is not None]
    ends = [row.time_to for row in rows if row.time_to is not None]
    return Candidate(
        material_id=source.material.id,
        material_name=source.name,
        role=source.link.source_role,
        priority=source.link.priority,
        block_id=rows[0].block_id,
        title=title,
        page_from=rows[0].page,
        page_to=rows[-1].page,
        fragment_ids=[row.fragment_id for row in rows],
        text=text,
        tokens=count_tokens(text),
        score=score * ROLE_WEIGHT[source.link.source_role],
        signals=[signal],
        flags=flags,
        figures=figures,
        time_from=min(times) if times else None,
        time_to=max(ends) if ends else None,
    )


# --- сбор ------------------------------------------------------------------------------


class _Pool:
    """Кандидаты в порядке доверия; фрагмент принадлежит первому, кто его взял."""

    def __init__(self) -> None:
        self.items: list[Candidate] = []
        self.owner: dict[UUID, Candidate] = {}

    def add(self, source: _Source, rows: list[_Row], score: float, signal: str,
            *, outline: bool = False) -> None:
        free: list[_Row] = []
        for row in rows:
            owner = self.owner.get(row.fragment_id)
            if owner is None:
                free.append(row)
            elif signal not in owner.signals:
                owner.signals.append(signal)
                owner.score += score * ROLE_WEIGHT[source.link.source_role] * 0.5
        for part in _group_rows(free):
            candidate = _candidate(source, part, score, signal)
            if candidate is None:
                continue
            candidate.in_outline = outline
            self.items.append(candidate)
            for fragment_id in candidate.fragment_ids:
                self.owner[fragment_id] = candidate


def _pin(session: Session, pool: _Pool, sources: dict[UUID, _Source],
         pinned: Sequence[LessonPinnedRange]) -> None:
    """Куски человека — первыми: неверный диапазон отклоняется до любых запросов к модели.

    Фрагменты берутся от начала до конца диапазона в порядке чтения; `outline=True`
    защищает кусок от вытеснения поиском и лимитом `MAX_CANDIDATES`.
    """
    for pin in pinned:
        source = sources.get(pin.material_id)
        if source is None:
            raise ProjectDomainError(
                "Материал выбранного куска не входит в проект",
                status=422, code="lesson_source_unavailable",
            )
        ids = refs_module.ids_between(
            session, source.material, pin.from_fragment_id, pin.to_fragment_id
        )
        rows = _rows(session, source.material, set(ids))
        if not rows:
            raise ProjectDomainError(
                "В выбранном куске нет текста", status=422, code="lesson_pinned_empty",
            )
        pool.add(source, rows, PINNED_SCORE, PINNED_SIGNAL, outline=True)


def _outline(session: Session, pool: _Pool, program: _Program, node: ProgramNode,
             sources: dict[UUID, _Source]) -> bool:
    has_outline = False
    for material_id, source in sources.items():
        if material_id not in program.ranges.get(node.id, {}):
            continue
        has_outline = True
        if source.material.active_parse_revision <= 0:
            continue
        plan = _plan_source(session, program, node, source.material, source.link)
        segment = boundaries.to_segment(plan.pages, plan.start, plan.end)
        if segment is None:
            continue
        ids = {
            fragment.id
            for fragment in boundaries.fragments_in(plan.pages, segment.start, segment.end)
            if fragment.is_content
        }
        pool.add(source, _rows(session, source.material, ids), SIGNAL_WEIGHT["outline"],
                 "оглавление темы", outline=True)
    return has_outline


def _bindings(session: Session, pool: _Pool, node: ProgramNode,
              sources: dict[UUID, _Source]) -> None:
    by_signal: dict[tuple[UUID, BindingStatus, BindingMechanism], set[UUID]] = defaultdict(set)
    for binding in topic_support(session, node.project_id, node.id):
        if binding.material_id in sources and binding.fragment_id is not None:
            by_signal[(binding.material_id, binding.status, binding.mechanism)].add(
                binding.fragment_id
            )
    # Ручные раньше машинных: сильный сигнал забирает фрагмент первым.
    for (material_id, status, mechanism), ids in sorted(
        by_signal.items(), key=lambda item: -SIGNAL_WEIGHT[item[0][1]]
    ):
        signal = f"привязка {STATUS_LABEL[status]} ({MECHANISM_LABEL[mechanism]})"
        source = sources[material_id]
        pool.add(source, _rows(session, source.material, ids), SIGNAL_WEIGHT[status], signal)


def search_queries(program: _Program, node: ProgramNode) -> list[str]:
    """«Раздел › тема», каждый подпункт и подсказки «Где искать» — без повторов."""
    by_id = {item.id: item for item, _ in program.ordered}
    parent = by_id.get(node.parent_id) if node.parent_id else None
    queries = [f"{parent.title} › {node.title}" if parent else node.title]
    queries += [
        f"{node.title}: {item.title}"
        for item, _ in program.ordered
        if item.parent_id == node.id
    ]
    queries += list(node.material_search_queries or [])
    return list(dict.fromkeys(query.strip()[:2_000] for query in queries if query.strip()))


async def _search(session: Session, pool: _Pool, program: _Program, node: ProgramNode,
                  sources: dict[UUID, _Source]) -> list[str]:
    retriever = HybridRetriever()
    results = [
        await retriever.search(session, RetrievalSearchWrite(
            query=query,
            strategy=SearchStrategy.HYBRID,
            scope=RetrievalScope.SELECTED_MATERIALS,
            project_id=node.project_id,
            node_id=node.id,
            material_ids=list(sources),
            limit=SEARCH_LIMIT,
        ))
        for query in search_queries(program, node)
    ]
    notes = list(dict.fromkeys(
        reason for result in results for reason in result.degradation_reasons
    ))
    hits = fuse_rankings([result.results for result in results])
    for rank, hit in enumerate(hits[: SEARCH_LIMIT * 2]):
        source = sources.get(hit.locator.material_id)
        if source is None:
            continue
        # Место в слитой выдаче, а не score: оценки разных запросов несопоставимы.
        weight = 0.6 * (1 - rank / (SEARCH_LIMIT * 2)) + 0.2
        rows = _rows(session, source.material, set(hit.locator.fragment_ids))
        pool.add(source, rows, weight, f"поиск, место {rank + 1}")
    return notes


def _mark_duplicates(candidates: list[Candidate]) -> list[Candidate]:
    """Тот же текст в другом материале — `also_in` у лучшего, а не второй кусок."""
    kept: dict[str, Candidate] = {}
    result: list[Candidate] = []
    # Выбранные человеком идут первыми и дублем не считаются: выбор нельзя «съесть».
    for candidate in sorted(candidates, key=lambda item: (not item.pinned, -item.score)):
        key = " ".join(candidate.text.split()).lower()
        twin = kept.get(key)
        if (
            twin is not None
            and twin.material_id != candidate.material_id
            and not candidate.pinned
        ):
            if candidate.material_name not in twin.also_in:
                twin.also_in.append(candidate.material_name)
            continue
        kept[key] = candidate
        result.append(candidate)
    return result


def reading_order(candidates: list[Candidate]) -> list[Candidate]:
    """Модель видит последовательность самого учебника: материал, затем страницы."""
    return sorted(candidates, key=lambda item: (
        ROLE_ORDER[item.role], item.priority, item.material_name,
        item.page_from, item.time_from or 0,
    ))


def _load_sources(session: Session, project_id: UUID, material_ids: list[UUID]
                  ) -> dict[UUID, _Source]:
    sources: dict[UUID, _Source] = {}
    for material_id in material_ids:
        material = session.get(Material, material_id)
        link = session.get(ProjectMaterial, (project_id, material_id))
        if material is not None and link is not None:
            sources[material_id] = _Source(material, link, _source_name(material, link, ""))
    return sources


async def collect(
    session: Session, node: ProgramNode, material_ids: list[UUID],
    pinned: Sequence[LessonPinnedRange] = (), pinned_only: bool = True,
) -> CandidateSet:
    """Кандидаты темы по выбранным материалам, лучшие не больше `MAX_CANDIDATES`.

    `pinned` — куски, выбранные человеком: их материал участвует, даже если его не
    отметили. С `pinned_only` (по умолчанию) урок строится из выбранного одного — ни
    оглавление, ни привязки, ни поиск не зовутся; без него они добавляют своё.
    """
    wanted = list(dict.fromkeys([*material_ids, *(pin.material_id for pin in pinned)]))
    sources = _load_sources(session, node.project_id, wanted)
    pool = _Pool()
    _pin(session, pool, sources, pinned)
    if not sources:
        return CandidateSet([], has_outline=False, searched=False, search_notes=[])
    only = bool(pinned) and pinned_only
    has_outline, notes = False, []
    if not only:
        program = _load_program(session, node.project_id)
        has_outline = _outline(session, pool, program, node, sources)
        _bindings(session, pool, node, sources)
        notes = await _search(session, pool, program, node, sources)
    candidates = _mark_duplicates(pool.items)
    # Выбранное и весь диапазон оглавления — сама тема: поиск их не вытесняет.
    outline = [item for item in candidates if item.in_outline]
    rest = sorted((item for item in candidates if not item.in_outline), key=lambda i: -i.score)
    chosen = (outline + rest)[:MAX_CANDIDATES]
    return CandidateSet(reading_order(chosen), has_outline, not only, notes, len(pinned))


# --- текст для модели ------------------------------------------------------------------


def _clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"


def header(candidate: Candidate, label: str) -> str:
    """Шапка куска: место, раздел, сигналы, метки и дубли — «насколько точно это про тему»."""
    role = {SourceRole.MAIN: "основной", SourceRole.ADDITIONAL: "дополнительный",
            SourceRole.REFERENCE: "справочный"}[candidate.role]
    if candidate.time_from is not None:
        place = f"время {_clock(candidate.time_from)}–{_clock(candidate.time_to or 0)}"
    elif candidate.page_from == candidate.page_to:
        place = f"стр. {candidate.page_from}"
    else:
        place = f"стр. {candidate.page_from}–{candidate.page_to}"
    first = f"[{label}] {candidate.material_name} · {role} · {place}"
    if candidate.title:
        first += f" · «{candidate.title}»"
    lines = [first, "сигналы: " + ", ".join(candidate.signals)]
    marks = candidate.flags + candidate.figures
    if marks:
        lines.append("метки: " + ", ".join(marks))
    if candidate.also_in:
        lines.append("также в: " + ", ".join(candidate.also_in))
    return "\n".join(lines)


def head_text(text: str, tokens: int) -> str:
    """Начало куска для карты: первые слова до предела и многоточие."""
    words = text.split()
    return text if len(words) <= tokens else " ".join(words[:tokens]) + " …"
