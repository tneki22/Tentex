"""Источники ответа учебного чата: запрос, область, подбор мест и их снимок.

Роутер и сборка запроса к модели получают отсюда готовый список источников
с S-ID и заметки для модели; как именно искали — забота этого модуля.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatMessageRole, RetrievalChunk
from app.projects.errors import ProjectDomainError
from app.retrieval.citations import CITATION_GROUP
from app.retrieval.context import ContextAssembler
from app.retrieval.schemas import (
    RetrievalHitRead,
    RetrievalScope,
    RetrievalSearchRead,
    RetrievalSearchWrite,
    SearchStrategy,
)
from app.retrieval.search import HybridRetriever, resolve_scope

#: Операции, которым нужны места из разных материалов.
COMPARING_OPERATIONS: frozenset[str] = frozenset({"compare_sources", "find_discrepancies"})

#: Вопрос от стольких слов ищется сам по себе. Короче — ещё и вместе с прошлым
#: вопросом: «а подробнее?» без него находит случайные места, а самостоятельный
#: короткий вопрос не теряет своих мест, потому что его запрос тоже выполняется.
STANDALONE_WORDS = 12
SOURCES_LIMIT = 10
#: Сколько мест добирается из других материалов, когда выдача из одного.
SECOND_MATERIAL_LIMIT = 4
_RRF_K = 60

NO_SECOND_MATERIAL_NOTE = (
    "В выбранной области не нашлось второго материала по этому запросу: "
    "сравнивать не с чем, скажи об этом прямо."
)


class RetrievalScopeEmptyError(ProjectDomainError):
    def __init__(self) -> None:
        super().__init__(
            "К теме ничего не привязано — искать в «Связано с темой» негде",
            status=409,
            code="retrieval_scope_empty",
        )


@dataclass(frozen=True)
class FoundSources:
    entries: list[dict[str, Any]]
    notes: list[str]


def retrieval_queries(text: str, tail: list[ChatMessage]) -> list[str]:
    """Запросы к источникам: текст хода и, для короткого, он же с прошлым вопросом."""
    queries = [text]
    if len(text.split()) >= STANDALONE_WORDS:
        return queries
    previous = next(
        (
            item.text.strip()
            for item in reversed(tail)
            if item.role == ChatMessageRole.USER and item.text.strip()
        ),
        None,
    )
    if previous and previous != text.strip():
        queries.append(f"{previous}\n{text}")
    return queries


def ensure_scope_has_places(
    session: Session, project_id: UUID, node_id: UUID | None, scope: str
) -> None:
    """«Связано с темой» без привязок отклоняется до записи хода и до вызова модели."""
    if scope != RetrievalScope.LINKED_TOPIC or node_id is None:
        return
    filter_ = resolve_scope(
        session,
        RetrievalSearchWrite(
            query="-", scope=RetrievalScope.LINKED_TOPIC, project_id=project_id, node_id=node_id
        ),
    )
    if filter_.block_ids is not None and not filter_.block_ids:
        raise RetrievalScopeEmptyError()


def _fuse(rankings: list[list[RetrievalHitRead]]) -> list[RetrievalHitRead]:
    """Слить выдачи нескольких запросов по RRF; одно место — один раз."""
    if len(rankings) == 1:
        return rankings[0]
    scores: dict[UUID, float] = {}
    hits: dict[UUID, RetrievalHitRead] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            chunk_id = hit.locator.chunk_id
            hits.setdefault(chunk_id, hit)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (_RRF_K + rank + 1)
    order = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [hits[chunk_id] for chunk_id in order]


def round_robin_by_material(hits: list[RetrievalHitRead]) -> list[RetrievalHitRead]:
    """Сначала лучшее место каждого материала, затем остальные по релевантности."""
    seen: set[UUID] = set()
    leaders: list[RetrievalHitRead] = []
    rest: list[RetrievalHitRead] = []
    for hit in hits:
        if hit.locator.material_id in seen:
            rest.append(hit)
        else:
            seen.add(hit.locator.material_id)
            leaders.append(hit)
    return leaders + rest


def _locator_label(hit: RetrievalHitRead) -> str:
    locator = hit.locator
    if locator.typst_path:
        if locator.line_from:
            return (
                f"{locator.typst_path}, строки {locator.line_from}–"
                f"{locator.line_to or locator.line_from}"
            )
        return locator.typst_path
    if locator.page_from:
        if locator.page_to and locator.page_to != locator.page_from:
            return f"стр. {locator.page_from}–{locator.page_to}"
        return f"стр. {locator.page_from}"
    return "без страницы"


def source_entry(number: int, hit: RetrievalHitRead, also_in: list[str]) -> dict[str, Any]:
    """Источник ответа с полным локатором: страницы или путь и строки Typst."""
    locator = hit.locator
    return {
        "kind": "retrieval_source",
        "id": f"S{number}",
        "material": locator.material_name,
        "material_id": str(locator.material_id),
        "locator": _locator_label(hit),
        "page": locator.page_from,
        "page_to": locator.page_to,
        "typst_path": locator.typst_path,
        "line_from": locator.line_from,
        "line_to": locator.line_to,
        "block_title": locator.block_title,
        "chunk_id": str(locator.chunk_id),
        "fragment_ids": [str(item) for item in locator.fragment_ids],
        "text": hit.text,
        "quality": hit.quality.value if hit.quality else None,
        "warning": hit.warning,
        "also_in": also_in,
        "included": True,
        "bytes": len(hit.text.encode()),
    }


async def find_sources(
    session: Session,
    *,
    project_id: UUID,
    node_id: UUID | None,
    text: str,
    tail: list[ChatMessage],
    scope: str,
    material_ids: list[UUID],
    operation: str,
) -> FoundSources:
    """Места для ответа: поиск в области, слияние запросов, разнообразие для сравнения."""
    retriever = HybridRetriever()
    scope_value = RetrievalScope(scope)

    def command(query: str, limit: int, exclude: list[UUID] | None = None) -> RetrievalSearchWrite:
        return RetrievalSearchWrite(
            query=query,
            strategy=SearchStrategy.HYBRID,
            scope=scope_value,
            project_id=project_id,
            node_id=node_id,
            material_ids=material_ids,
            exclude_material_ids=exclude or [],
            limit=limit,
        )

    results = [
        await retriever.search(session, command(query, SOURCES_LIMIT))
        for query in retrieval_queries(text, tail)
    ]
    notes = list(
        dict.fromkeys(reason for result in results for reason in result.degradation_reasons)
    )
    hits = _fuse([result.results for result in results])[:SOURCES_LIMIT]

    if operation in COMPARING_OPERATIONS:
        present = list(dict.fromkeys(hit.locator.material_id for hit in hits))
        if len(present) < 2:
            extra = await retriever.search(
                session, command(text, SECOND_MATERIAL_LIMIT, exclude=present)
            )
            if extra.results:
                hits = [*hits[: SOURCES_LIMIT - len(extra.results)], *extra.results]
            else:
                notes.append(NO_SECOND_MATERIAL_NOTE)
        hits = round_robin_by_material(hits)

    assembled = ContextAssembler().assemble(
        session,
        RetrievalSearchRead(
            query=text,
            strategy=SearchStrategy.HYBRID,
            index_id=results[0].index_id,
            degraded=bool(notes),
            degradation_reasons=notes,
            results=hits,
        ),
    )
    entries = [
        source_entry(number, hit, assembled.also_in.get(hit.locator.chunk_id, []))
        for number, hit in enumerate(assembled.sources, start=1)
    ]
    return FoundSources(entries=entries, notes=notes)


# ------------------------------------------------------------ стабильные S-ID

#: Пометка снимка ответа: его S-ID — номера всего чата, а не одного хода.
STABLE_IDS = "stable"
SOURCE_ID = re.compile(r"\bS(\d+)\b")


@dataclass
class SourceIds:
    """Номера источников чата: один кусок — один S-ID во всех ходах.

    Прежде S1 каждого хода был своим, и «что в S3?» или старая ссылка в
    истории указывали на другое место. Номера восстанавливаются из снимков
    прежних ответов; отдельной таблицы не нужно.
    """

    by_chunk: dict[str, str] = field(default_factory=dict)
    #: Последний снимок каждого S-ID — для вопроса о номере, которого нет в выдаче.
    latest: dict[str, dict[str, Any]] = field(default_factory=dict)
    next_number: int = 1

    @classmethod
    def from_history(cls, messages: list[ChatMessage]) -> SourceIds:
        ids = cls()
        for message in messages:
            snapshot = message.context_snapshot or {}
            if snapshot.get("source_ids") != STABLE_IDS:
                continue
            for entry in snapshot.get("retrieval_sources") or []:
                source_id = str(entry.get("id", ""))
                match = SOURCE_ID.fullmatch(source_id)
                if not match:
                    continue
                ids.by_chunk.setdefault(str(entry.get("chunk_id")), source_id)
                ids.latest[source_id] = entry
                ids.next_number = max(ids.next_number, int(match.group(1)) + 1)
        return ids

    def assign(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Выдать выдаче номера чата: известный кусок — прежний, новый — следующий."""
        assigned = []
        for entry in entries:
            chunk_id = str(entry.get("chunk_id"))
            source_id = self.by_chunk.get(chunk_id)
            if source_id is None:
                source_id = f"S{self.next_number}"
                self.next_number += 1
                self.by_chunk[chunk_id] = source_id
            assigned.append({**entry, "id": source_id})
        return assigned

    def mentioned(
        self, session: Session, text: str, present: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Источники, о которых спрашивают по номеру, но которых нет в выдаче.

        Кусок ещё в индексе — его текст берётся заново; кусок заменён новой
        ревизией материала — остаётся текст снимка с пометкой о старой версии.
        """
        have = {entry["id"] for entry in present}
        extra = []
        for number in dict.fromkeys(SOURCE_ID.findall(text)):
            source_id = f"S{number}"
            entry = self.latest.get(source_id)
            if entry is None or source_id in have:
                continue
            chunk = _chunk(session, entry.get("chunk_id"))
            if chunk is not None:
                extra.append({**entry, "text": chunk.text, "stale": False})
            else:
                extra.append({**entry, "stale": True})
        return extra


def _chunk(session: Session, chunk_id: object) -> RetrievalChunk | None:
    try:
        return session.get(RetrievalChunk, UUID(str(chunk_id)))
    except ValueError:
        return None


def legacy_citations(message: ChatMessage) -> str:
    """Текст старого ответа, где S-ID ходовые: ссылки заменяются названием и локатором.

    Иначе модель видела бы в истории [S3] прошлого хода и путала его с S3 новой
    выдачи.
    """
    snapshot = message.context_snapshot or {}
    if snapshot.get("source_ids") == STABLE_IDS:
        return message.text
    labels = {
        str(entry.get("id")): ", ".join(
            part for part in (entry.get("material"), entry.get("locator")) if part
        ) or "источник"
        for entry in snapshot.get("retrieval_sources") or []
    }

    def label(match: re.Match[str]) -> str:
        ids = [item.strip() for item in re.split(r"[,;]", match.group(1))]
        return "[" + "; ".join(labels.get(item, "источник") for item in ids) + "]"

    return CITATION_GROUP.sub(label, message.text)
