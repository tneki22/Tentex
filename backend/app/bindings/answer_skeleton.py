"""Скелет файла эталонных ответов для разметки моделью (срез F).

Модель размечает границы разделов, а не читает ответы: ей достаётся только
список фрагментов-кандидатов в границы, по ~100 знаков заголовка на строку, с
дешёвыми локальными признаками. Полный текст эталона собирается на сервере из
фрагментов между границами уже после того, как модель вернула номера строк, а
не текст (см. `apply_sections` в `answers_link.py`).

Кандидатом становится фрагмент, у которого есть хоть один из четырёх
признаков ниже — остальное (внутренние списки внутри тела ответа) остаётся
телом раздела и в скелет не попадает.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

from app.models import MaterialFragment, ProgramNode
from app.projects.heading_match import HeadingIndex

MARKER_RE = re.compile(
    r"^\s*(?:"
    r"(?:вопрос|билет|задача|задание|тема)\s*(?:№|#)?\s*\d{1,3}(?:\.\d{1,3})*\s*"
    r"|§\s*\d{1,3}"
    r"|#{1,6}\s"
    r"|\d{1,3}(?:\.\d{1,3})*\s*[.)]"
    r"|[ivxlcdm]{1,7}\s*[.)]"
    r")",
    re.IGNORECASE,
)

LEXICAL_CANDIDATE_THRESHOLD = 0.35
TOP_LEXICAL_HINTS = 3
SHORT_HEADING_MAX_CHARS = 200
NEXT_BODY_MIN_CHARS = 300
MAX_HEADING_CHARS = 100

SKELETON_BATCH_LINES = 150
SKELETON_BATCH_BYTES = 24_000
SKELETON_BATCH_OVERLAP = 3


@dataclass(frozen=True, slots=True)
class SkeletonHint:
    question: int
    score: float


@dataclass(frozen=True, slots=True)
class SkeletonLine:
    index: int
    fragment_id: UUID
    page: int
    element_kind: str
    heading: str
    chars_to_next: int
    hints: tuple[SkeletonHint, ...] = ()


@dataclass(frozen=True, slots=True)
class Skeleton:
    lines: tuple[SkeletonLine, ...]
    source_hash: str


def _has_marker(text: str) -> bool:
    return MARKER_RE.match(text) is not None


def _is_page_start(rows: list[tuple[MaterialFragment, int]], position: int) -> bool:
    return position == 0 or rows[position][1] != rows[position - 1][1]


def build_skeleton(
    nodes: list[ProgramNode], rows: list[tuple[MaterialFragment, int]]
) -> Skeleton:
    node_index = {node.id: position for position, node in enumerate(nodes)}
    index = HeadingIndex((node.id, node.title) for node in nodes)

    lengths = [len(fragment.text) for fragment, _page in rows]
    hints_by_position: list[tuple[SkeletonHint, ...]] = []
    best_scores: list[float] = []
    for fragment, _page in rows:
        text = fragment.text.strip()
        if not text:
            hints_by_position.append(())
            best_scores.append(0.0)
            continue
        ranked = index.rank(text)[:TOP_LEXICAL_HINTS]
        hints = tuple(
            SkeletonHint(node_index[candidate.node_id] + 1, round(candidate.score, 2))
            for candidate in ranked
        )
        hints_by_position.append(hints)
        best_scores.append(hints[0].score if hints else 0.0)

    candidate_positions: list[int] = []
    for position, (fragment, _page) in enumerate(rows):
        text = fragment.text.strip()
        if not text:
            continue
        marker = _has_marker(text)
        next_length = lengths[position + 1] if position + 1 < len(rows) else 0
        is_candidate = (
            fragment.element_kind == "heading"
            or best_scores[position] >= LEXICAL_CANDIDATE_THRESHOLD
            or (marker and _is_page_start(rows, position))
            or (
                marker
                and lengths[position] <= SHORT_HEADING_MAX_CHARS
                and next_length > NEXT_BODY_MIN_CHARS
            )
        )
        if is_candidate:
            candidate_positions.append(position)

    lines: list[SkeletonLine] = []
    for line_index, position in enumerate(candidate_positions):
        next_position = (
            candidate_positions[line_index + 1]
            if line_index + 1 < len(candidate_positions)
            else len(rows)
        )
        fragment, page = rows[position]
        lines.append(
            SkeletonLine(
                index=line_index,
                fragment_id=fragment.id,
                page=page,
                element_kind=fragment.element_kind,
                heading=" ".join(fragment.text.split())[:MAX_HEADING_CHARS],
                chars_to_next=sum(lengths[position + 1 : next_position]),
                hints=hints_by_position[position],
            )
        )

    source_hash = hashlib.sha256(
        json.dumps(
            [
                {
                    "index": line.index,
                    "fragment_id": str(line.fragment_id),
                    "page": line.page,
                    "kind": line.element_kind,
                    "heading": line.heading,
                    "chars": line.chars_to_next,
                }
                for line in lines
            ],
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return Skeleton(lines=tuple(lines), source_hash=source_hash)


def format_skeleton_line(line: SkeletonLine) -> str:
    kind = "head" if line.element_kind == "heading" else "para"
    hints = ",".join(f"{hint.question}:{hint.score:.2f}" for hint in line.hints)
    suffix = f" ->{hints}" if hints else ""
    return f'#{line.index} p{line.page} {kind} "{line.heading}" {line.chars_to_next}ch{suffix}'


def batch_skeleton_lines(
    lines: tuple[SkeletonLine, ...],
    *,
    max_lines: int = SKELETON_BATCH_LINES,
    max_bytes: int = SKELETON_BATCH_BYTES,
    overlap: int = SKELETON_BATCH_OVERLAP,
) -> list[tuple[SkeletonLine, ...]]:
    """Разбить скелет на пакеты для модели, с нахлёстом между соседними.

    Нахлёст не даёт границе пакета оторвать заголовок раздела от строк,
    которые модель использует, чтобы отличить его от оглавления или списка.
    """
    if not lines:
        return []
    batches: list[tuple[SkeletonLine, ...]] = []
    start = 0
    while start < len(lines):
        current: list[SkeletonLine] = []
        size = 0
        end = start
        while end < len(lines):
            line = lines[end]
            line_size = len(format_skeleton_line(line).encode("utf-8"))
            if current and (len(current) >= max_lines or size + line_size > max_bytes):
                break
            current.append(line)
            size += line_size
            end += 1
        batches.append(tuple(current))
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return batches
