"""Purpose-specific section detection for files of reference answers.

The detector deliberately ignores material blocks and element kinds: OCR may
classify a question as a paragraph, and a heading may cross a page boundary.
It aligns candidate boundaries to the ordered exam questions globally, so an
internal numbered proof list cannot reset the document sequence.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from app.models import MaterialFragment, ProgramNode, ReferenceAnswerMatchMethod
from app.projects.heading_match import (
    AUTO_THRESHOLD,
    CONFIDENT_MARGIN,
    MAX_CANDIDATES,
    SUGGEST_THRESHOLD,
    HeadingCandidate,
    HeadingIndex,
    normalize_answer_heading,
)

MAX_HEADER_FRAGMENTS = 4
MAX_HEADER_LENGTH = 500
NUMBERED_CONFIDENCE = 0.45
NUMBER_RE = re.compile(
    r"^\s*(?:(?:вопрос|задача|задание)\s*(?:№|#)?\s*)?(\d{1,3})(?:[.)]|\s)",
    re.IGNORECASE,
)
TEXT_KINDS = {"heading", "paragraph", "list"}
SURFACE_TERM_RE = re.compile(r"[a-zа-я0-9]{4,}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DetectedSection:
    node_ids: tuple[UUID, ...]
    title: str
    fragments: tuple[MaterialFragment, ...]
    header_fragment_ids: frozenset[UUID]
    page_from: int
    page_to: int
    method: ReferenceAnswerMatchMethod


@dataclass(frozen=True, slots=True)
class AmbiguousSection:
    anchor_fragment_id: UUID
    heading: str
    preview: str | None
    page: int
    candidates: tuple[HeadingCandidate, ...]


@dataclass(frozen=True, slots=True)
class DetectionResult:
    sections: tuple[DetectedSection, ...] = ()
    ambiguous: tuple[AmbiguousSection, ...] = ()
    linked_node_ids: tuple[UUID, ...] = ()
    missing_node_ids: tuple[UUID, ...] = ()
    extra_sections: int = 0


@dataclass(frozen=True, slots=True)
class _Candidate:
    anchor: int
    header_end: int
    node_index: int
    title: str
    score: float
    method: ReferenceAnswerMatchMethod
    ranked: tuple[HeadingCandidate, ...] = ()
    confident: bool = False


def _number(text: str) -> int | None:
    match = NUMBER_RE.match(text)
    return int(match.group(1)) if match else None


def _joined_title(
    rows: list[tuple[MaterialFragment, int]], anchor: int, end: int
) -> str:
    return " ".join(
        " ".join(fragment.text.split()) for fragment, _page in rows[anchor:end]
    )[:MAX_HEADER_LENGTH].strip()


def _surface_signature(value: str) -> frozenset[str]:
    """Cheap gate before the morphology-heavy heading matcher.

    A score of 0.86 is impossible without shared lexical stems. Keeping the
    first six characters also covers the common Russian inflection changes.
    """
    return frozenset(
        term[:6] for term in SURFACE_TERM_RE.findall(normalize_answer_heading(value))
    )


def _could_match_question(
    normalized: str, question_signatures: tuple[frozenset[str], ...]
) -> bool:
    terms = _surface_signature(normalized)
    if not terms:
        return False
    for question_terms in question_signatures:
        if not question_terms:
            continue
        overlap = len(terms & question_terms)
        union = len(terms | question_terms)
        if (
            overlap >= min(2, len(question_terms))
            and overlap / len(question_terms) >= 0.45
            and overlap / union >= 0.25
        ):
            return True
    return False


def _collapse_duplicate_titles(
    ranked: tuple[HeadingCandidate, ...],
    nodes: list[ProgramNode],
    node_index: dict[UUID, int],
) -> list[HeadingCandidate]:
    """Несколько узлов с дословно одинаковой формулировкой — не спор, а один вопрос.

    `HeadingIndex.rank` честно возвращает каждый узел с точным совпадением
    заголовка, включая задублированные при импорте вопросы программы. Ниже по
    конвейеру это читается как «второй кандидат дышит в затылок первому» и рубит
    привязку вовсе. Схлопываем дублей в самое раннее вхождение до расчёта отрыва —
    остальные вхождения получат тот же эталон позже, в `_expand_duplicate_sections`.
    """
    best_by_title: dict[str, HeadingCandidate] = {}
    order: list[str] = []
    for candidate in ranked:
        title_key = nodes[node_index[candidate.node_id]].title.casefold()
        current = best_by_title.get(title_key)
        if current is None:
            order.append(title_key)
            best_by_title[title_key] = candidate
        elif node_index[candidate.node_id] < node_index[current.node_id]:
            best_by_title[title_key] = candidate
    return [best_by_title[key] for key in order]


def _candidate_for_anchor(
    rows: list[tuple[MaterialFragment, int]],
    anchor: int,
    nodes: list[ProgramNode],
    index: HeadingIndex,
    node_index: dict[UUID, int],
    resolved: dict[str, UUID],
    question_signatures: tuple[frozenset[str], ...],
) -> _Candidate | None:
    fragment = rows[anchor][0]
    if fragment.element_kind not in TEXT_KINDS or not fragment.text.strip():
        return None
    number = _number(fragment.text)
    if number is not None and not 1 <= number <= len(nodes):
        # Раздел файла начал нумерацию заново (второй, третий раздел ответов) —
        # число не указывает ни на один узел программы, но заголовок остаётся
        # заголовком: ищем его по смыслу вместо того, чтобы выбросить якорь целиком.
        number = None

    choices: list[_Candidate] = []
    limit = min(len(rows), anchor + MAX_HEADER_FRAGMENTS)
    for end in range(anchor + 1, limit + 1):
        if end > anchor + 1 and _number(rows[end - 1][0].text) is not None:
            break
        title = _joined_title(rows, anchor, end)
        normalized = normalize_answer_heading(title)
        resolved_node = resolved.get(normalized)
        if resolved_node is not None and resolved_node in node_index:
            choices.append(
                _Candidate(
                    anchor,
                    end,
                    node_index[resolved_node],
                    title,
                    1.0,
                    ReferenceAnswerMatchMethod.RESOLVED_TITLE,
                    (),
                    True,
                )
            )
            continue
        if number is None and not _could_match_question(normalized, question_signatures):
            continue
        ranked = index.rank(title)
        if number is not None:
            target = number - 1
            score = next(
                (candidate.score for candidate in ranked if candidate.node_id == nodes[target].id),
                0.0,
            )
            choices.append(
                _Candidate(
                    anchor,
                    end,
                    target,
                    title,
                    score,
                    (
                        ReferenceAnswerMatchMethod.EXACT_TITLE
                        if score >= 0.999
                        else ReferenceAnswerMatchMethod.NUMBERED_ORDER
                    ),
                    ranked,
                    score >= NUMBERED_CONFIDENCE,
                )
            )
            if score < NUMBERED_CONFIDENCE and ranked:
                # Номер разошёлся с деревом (раздел начал счёт заново) — пробуем
                # тот же заголовок по смыслу, а не по позиции в списке вопросов.
                collapsed = _collapse_duplicate_titles(ranked, nodes, node_index)
                best = collapsed[0]
                runner_up = collapsed[1].score if len(collapsed) > 1 else 0.0
                choices.append(
                    _Candidate(
                        anchor,
                        end,
                        node_index[best.node_id],
                        title,
                        best.score,
                        (
                            ReferenceAnswerMatchMethod.EXACT_TITLE
                            if best.score >= 0.999
                            else ReferenceAnswerMatchMethod.FUZZY_TITLE
                        ),
                        ranked,
                        best.score >= AUTO_THRESHOLD
                        and best.score - runner_up >= CONFIDENT_MARGIN,
                    )
                )
            continue
        if not ranked:
            continue
        collapsed = _collapse_duplicate_titles(ranked, nodes, node_index)
        best = collapsed[0]
        runner_up = collapsed[1].score if len(collapsed) > 1 else 0.0
        choices.append(
            _Candidate(
                anchor,
                end,
                node_index[best.node_id],
                title,
                best.score,
                (
                    ReferenceAnswerMatchMethod.EXACT_TITLE
                    if best.score >= 0.999
                    else ReferenceAnswerMatchMethod.FUZZY_TITLE
                ),
                ranked,
                best.score >= AUTO_THRESHOLD and best.score - runner_up >= CONFIDENT_MARGIN,
            )
        )
    if not choices:
        return None
    # Prefer the score, then the shortest header: answer prose must not be eaten
    # just because adding it leaves the similarity unchanged.
    return max(choices, key=lambda item: (item.confident, item.score, -item.header_end))


def _monotonic_path(candidates: list[_Candidate]) -> list[_Candidate]:
    confident = [candidate for candidate in candidates if candidate.confident]
    if not confident:
        return []
    best_paths: list[tuple[float, list[_Candidate]]] = []
    for index, candidate in enumerate(confident):
        best_score = 10.0 + candidate.score
        best_path = [candidate]
        for previous_index in range(index):
            previous = confident[previous_index]
            score, path = best_paths[previous_index]
            if (
                previous.header_end > candidate.anchor
                or previous.node_index >= candidate.node_index
            ):
                continue
            candidate_score = score + 10.0 + candidate.score
            if candidate_score > best_score:
                best_score = candidate_score
                best_path = [*path, candidate]
        best_paths.append((best_score, best_path))
    return max(best_paths, key=lambda item: item[0])[1]


def _stop_anchors(
    candidates: list[_Candidate], rows: list[tuple[MaterialFragment, int]]
) -> list[int]:
    """Якоря, на которых раздел обязан закончиться, даже не попав в путь.

    Путь строится только из уверенных совпадений с деревом; заголовок раздела,
    для которого в программе нет пары (следующий раздел файла, оглавление), в
    путь не попадает и раньше срастался с предыдущим разделом до конца файла.
    Уверенный по себе кандидат или правдоподобный заголовок (`element_kind ==
    "heading"` при разумном сходстве с каким-то вопросом) границу означают.
    Заголовок с нулевым сходством — внутренний подпункт ответа (см.
    `test_links_numbered_answers_by_current_program_order`), а не начало
    следующего раздела, и границу двигать не должен.
    """
    anchors = {
        candidate.anchor
        for candidate in candidates
        if candidate.score >= AUTO_THRESHOLD
        or (
            rows[candidate.anchor][0].element_kind == "heading"
            and candidate.score >= SUGGEST_THRESHOLD
        )
    }
    return sorted(anchors)


def detect_sections(
    nodes: list[ProgramNode],
    rows: list[tuple[MaterialFragment, int]],
    resolved: dict[str, UUID] | None = None,
) -> DetectionResult:
    resolved = resolved or {}
    index = HeadingIndex((node.id, node.title) for node in nodes)
    node_index = {node.id: position for position, node in enumerate(nodes)}
    question_signatures = tuple(_surface_signature(node.title) for node in nodes)
    candidates = [
        candidate
        for anchor in range(len(rows))
        if (
            candidate := _candidate_for_anchor(
                rows,
                anchor,
                nodes,
                index,
                node_index,
                resolved,
                question_signatures,
            )
        )
        is not None
    ]
    path = _monotonic_path(candidates)
    stop_anchors = _stop_anchors(candidates, rows)
    sections: list[DetectedSection] = []
    for position, boundary in enumerate(path):
        next_path_anchor = path[position + 1].anchor if position + 1 < len(path) else len(rows)
        next_stop_anchor = next(
            (anchor for anchor in stop_anchors if anchor > boundary.anchor), len(rows)
        )
        end = min(next_path_anchor, max(next_stop_anchor, boundary.header_end))
        section_rows = rows[boundary.anchor:end]
        pages = [page for _fragment, page in section_rows]
        sections.append(
            DetectedSection(
                node_ids=(nodes[boundary.node_index].id,),
                title=boundary.title,
                fragments=tuple(fragment for fragment, _page in section_rows),
                header_fragment_ids=frozenset(
                    fragment.id
                    for fragment, _page in rows[boundary.anchor : boundary.header_end]
                ),
                page_from=min(pages),
                page_to=max(pages),
                method=boundary.method,
            )
        )

    linked = {node_id for section in sections for node_id in section.node_ids}
    missing = tuple(node.id for node in nodes if node.id not in linked)
    best_ambiguous: dict[UUID, _Candidate] = {}
    for candidate in candidates:
        node_id = nodes[candidate.node_index].id
        if candidate.confident or node_id not in missing or candidate.score < SUGGEST_THRESHOLD:
            continue
        fragment = rows[candidate.anchor][0]
        if (
            _number(fragment.text) is None
            and fragment.element_kind != "heading"
            and candidate.score < 0.7
        ):
            continue
        current = best_ambiguous.get(node_id)
        if current is None or candidate.score > current.score:
            best_ambiguous[node_id] = candidate
    ambiguous = tuple(
        AmbiguousSection(
            anchor_fragment_id=rows[candidate.anchor][0].id,
            heading=candidate.title,
            preview=None,
            page=rows[candidate.anchor][1],
            candidates=tuple(
                item
                for item in candidate.ranked[:MAX_CANDIDATES]
                if item.score >= SUGGEST_THRESHOLD
            ),
        )
        for candidate in sorted(best_ambiguous.values(), key=lambda item: item.anchor)
    )
    return DetectionResult(
        sections=tuple(sections),
        ambiguous=ambiguous,
        linked_node_ids=tuple(node.id for node in nodes if node.id in linked),
        missing_node_ids=missing,
        extra_sections=sum(
            1
            for fragment, _page in rows
            if (number := _number(fragment.text)) is not None and number > len(nodes)
        ),
    )


def section_for_resolution(
    nodes: list[ProgramNode],
    rows: list[tuple[MaterialFragment, int]],
    anchor_fragment_id: UUID,
    node_id: UUID,
) -> DetectedSection | None:
    node_index = {node.id: position for position, node in enumerate(nodes)}
    if node_id not in node_index:
        return None
    anchor = next(
        (
            position
            for position, (fragment, _page) in enumerate(rows)
            if fragment.id == anchor_fragment_id
        ),
        None,
    )
    if anchor is None:
        return None
    index = HeadingIndex((node.id, node.title) for node in nodes)
    question_signatures = tuple(_surface_signature(node.title) for node in nodes)
    candidate = _candidate_for_anchor(
        rows, anchor, nodes, index, node_index, {}, question_signatures
    )
    if candidate is None:
        return None
    detected = detect_sections(nodes, rows)
    next_anchor = len(rows)
    section_starts = {
        fragment.id
        for section in detected.sections
        for fragment in section.fragments[:1]
    }
    for position in range(anchor + 1, len(rows)):
        if rows[position][0].id in section_starts:
            next_anchor = position
            break
    section_rows = rows[anchor:next_anchor]
    pages = [page for _fragment, page in section_rows]
    return DetectedSection(
        node_ids=(node_id,),
        title=normalize_answer_heading(candidate.title),
        fragments=tuple(fragment for fragment, _page in section_rows),
        header_fragment_ids=frozenset(
            fragment.id for fragment, _page in rows[anchor : candidate.header_end]
        ),
        page_from=min(pages),
        page_to=max(pages),
        method=ReferenceAnswerMatchMethod.RESOLVED_TITLE,
    )
