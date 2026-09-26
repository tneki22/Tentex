"""Снимок retrieval-индекса в памяти процесса: векторы и места фрагментов.

База живёт на bind-mount с Windows-хоста. Там каждое чтение страницы SQLite —
отдельный запрос через 9p (≈ 0,5 мс), а `NullPool` открывает соединение с
пустым кешем. Точный cosine и поиск куска по фрагменту BM25 проходили все куски
индекса заново на каждом запросе: 5–6 с на проход, два прохода на поиск.

Снимок читает куски один раз и дальше только сверяет дешёвый штамп по индексу
`(index_id, material_id)`. Косинус считает тот же sqlite-vec, но в базе в памяти.
Ревизия материала проверяется на каждом запросе: новая ревизия делает его куски
непригодными сразу, до переиндексации.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import RetrievalSettings

log = logging.getLogger("tentex.retrieval")

#: Активный индекс и, например, кандидат из benchmark; больше в памяти не держим.
_CAPACITY = 2


@dataclass(frozen=True)
class ChunkRef:
    chunk_id: UUID
    material_id: UUID
    revision: int
    #: Главный блок и `locator.block_ids` куска из нескольких блоков.
    block_ids: frozenset[str]


class IndexSnapshot:
    def __init__(self, stamp: tuple[object, ...], rows: list[tuple[object, ...]]) -> None:
        self.stamp = stamp
        self.refs: list[ChunkRef] = []
        self.by_fragment: dict[str, int] = {}
        self._positions: dict[tuple[UUID, int], list[int]] = {}
        self._lock = threading.Lock()
        self._vectors = sqlite3.connect(":memory:", check_same_thread=False)
        _load_vec(self._vectors)
        self._vectors.execute("CREATE TABLE v (pos INTEGER PRIMARY KEY, embedding BLOB)")
        vectors: list[tuple[int, bytes]] = []
        # Строки идут по sort_order: фрагмент на стыке двух кусков (перекрытие)
        # принадлежит первому, как и раньше в SQL-варианте.
        for chunk_hex, material_hex, revision, block_hex, fragments, locator, blob in rows:
            position = len(self.refs)
            blocks = {str(UUID(hex=str(block_hex)))} if block_hex else set()
            blocks.update(json.loads(str(locator or "{}")).get("block_ids", []))
            ref = ChunkRef(
                UUID(hex=str(chunk_hex)), UUID(hex=str(material_hex)), int(revision),
                frozenset(blocks),
            )
            self.refs.append(ref)
            self._positions.setdefault((ref.material_id, ref.revision), []).append(position)
            for fragment_id in json.loads(str(fragments or "[]")):
                self.by_fragment.setdefault(fragment_id, position)
            if blob is not None:
                vectors.append((position, bytes(blob)))
        self._vectors.executemany("INSERT INTO v VALUES (?, ?)", vectors)

    def indexed(self, material_id: UUID, revision: int | None) -> bool:
        return revision is not None and (material_id, revision) in self._positions

    def chunk_for(self, fragment_ids: list[UUID], revisions: dict[UUID, int]) -> UUID | None:
        """Первый кусок текущей ревизии, где лежит один из фрагментов."""
        for fragment_id in fragment_ids:
            position = self.by_fragment.get(str(fragment_id))
            if position is None:
                continue
            ref = self.refs[position]
            if revisions.get(ref.material_id) == ref.revision:
                return ref.chunk_id
        return None

    def nearest(
        self,
        query: bytes,
        revisions: dict[UUID, int],
        *,
        limit: int,
        block_ids: list[UUID] | None = None,
    ) -> list[tuple[UUID, float]]:
        """Точный cosine по кускам текущих ревизий материалов области."""
        positions = [
            position
            for key in revisions.items()
            for position in self._positions.get(key, ())
        ]
        if block_ids is not None:
            wanted = {str(block_id) for block_id in block_ids}
            positions = [item for item in positions if self.refs[item].block_ids & wanted]
        if not positions:
            return []
        with self._lock:
            rows = self._vectors.execute(
                "SELECT pos, vec_distance_cosine(embedding, ?) AS distance FROM v "
                "WHERE pos IN (SELECT value FROM json_each(?)) ORDER BY distance LIMIT ?",
                (query, json.dumps(positions), limit),
            ).fetchall()
        return [(self.refs[position].chunk_id, float(distance)) for position, distance in rows]


def _load_vec(connection: sqlite3.Connection) -> None:
    import sqlite_vec

    connection.enable_load_extension(True)
    try:
        sqlite_vec.load(connection)
    finally:
        connection.enable_load_extension(False)


_snapshots: OrderedDict[UUID, IndexSnapshot] = OrderedDict()
_guard = threading.Lock()
_build_locks: dict[UUID, threading.Lock] = {}


def _stamp(session: Session, index_id: UUID) -> tuple[object, ...]:
    # Покрывающий индекс `(index_id, material_id)` хранит rowid: штамп читает
    # только его страницы. Замена кусков материала даёт новые rowid и число.
    return tuple(
        session.execute(
            text(
                "SELECT count(*), max(rowid), total(rowid) FROM retrieval_chunks "
                "WHERE index_id = :index_id"
            ),
            {"index_id": index_id.hex},
        ).one()
    )


def index_snapshot(session: Session, index_id: UUID) -> IndexSnapshot:
    stamp = _stamp(session, index_id)
    with _guard:
        cached = _snapshots.get(index_id)
        if cached is not None and cached.stamp == stamp:
            _snapshots.move_to_end(index_id)
            return cached
        build_lock = _build_locks.setdefault(index_id, threading.Lock())
    # Параллельные запросы к холодному индексу ждут одну сборку, а не делают свою.
    with build_lock:
        with _guard:
            cached = _snapshots.get(index_id)
            if cached is not None and cached.stamp == stamp:
                return cached
        rows = session.execute(
            text(
                "SELECT id, material_id, revision, block_id, fragment_ids, locator, embedding "
                "FROM retrieval_chunks WHERE index_id = :index_id ORDER BY sort_order"
            ),
            {"index_id": index_id.hex},
        ).all()
        snapshot = IndexSnapshot(stamp, [tuple(row) for row in rows])
        with _guard:
            _snapshots[index_id] = snapshot
            _snapshots.move_to_end(index_id)
            while len(_snapshots) > _CAPACITY:
                _snapshots.popitem(last=False)
        return snapshot


def forget_snapshot(index_id: UUID) -> None:
    """Сбросить снимок: например, выдача сослалась на уже удалённый кусок."""
    with _guard:
        _snapshots.pop(index_id, None)


def current_revisions(session: Session, material_ids: list[UUID] | set[UUID]) -> dict[UUID, int]:
    if not material_ids:
        return {}
    params = {f"m{number}": item.hex for number, item in enumerate(material_ids)}
    rows = session.execute(
        text(
            "SELECT id, active_parse_revision FROM materials "
            f"WHERE id IN ({', '.join(f':{key}' for key in params)})"
        ),
        params,
    ).all()
    return {UUID(hex=str(row[0])): int(row[1]) for row in rows}


def warm_active_snapshot() -> None:
    """Собрать снимок активного индекса в фоне: первый поиск не ждёт чтения базы."""

    def run() -> None:
        try:
            with SessionLocal() as session:
                settings = session.get(RetrievalSettings, 1)
                if settings is not None and settings.active_index_id is not None:
                    index_snapshot(session, settings.active_index_id)
        except Exception:
            log.exception("retrieval snapshot warm-up failed")

    threading.Thread(target=run, name="retrieval-snapshot", daemon=True).start()
