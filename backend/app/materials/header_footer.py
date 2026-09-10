"""Поиск повторяющихся колонтитулов и их удаление новой ревизией."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal
from uuid import UUID

from PIL import Image
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bindings.search import reindex_material
from app.bindings.service import transfer_bindings_on_revision
from app.materials import library
from app.materials import revisions as revision_registry
from app.materials.schemas import ApiModel
from app.materials.storage import material_path
from app.models import (
    Binding,
    Material,
    MaterialFragment,
    MaterialPage,
    MaterialRevisionOrigin,
    MaterialSourceKind,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError

# HP Labs page-association и FinSBD используют повторение в одинаковой позиции
# верхней/нижней полосы. Значения здесь — продуктовая конкретизация этого правила.
MARGIN_FRACTION = 0.15
MIN_SHORT_DOCUMENT_MATCHES = 2
MIN_LONG_DOCUMENT_MATCHES = 3
SHORT_DOCUMENT_PAGES = 5
MIN_SERIES_COVERAGE = 0.60
TEXT_SIMILARITY = 0.84
POSITION_TOLERANCE = 0.035
LINE_GAP_TOLERANCE = 0.06
LINE_VERTICAL_TOLERANCE = 0.012
MAX_ELEMENT_HEIGHT = 0.08
IMAGE_HASH_DISTANCE = 8
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:стр(?:аница)?\.?|page|p\.?)?\s*[-–—(\[]*\s*"
    r"(?P<number>\d{1,4}|[ivxlcdm]{1,10})\s*[-–—)\]]*\s*$",
    re.IGNORECASE,
)

CandidateKind = Literal["header", "footer", "page_number"]
Bbox = tuple[float, float, float, float]


class HeaderFooterOccurrenceRead(ApiModel):
    """Координаты одного вхождения на исходной странице."""

    page: int
    bbox: list[float]


class HeaderFooterCandidateRead(ApiModel):
    """Повторяющийся элемент и все страницы его серии."""

    id: str
    kind: CandidateKind
    text: str | None
    element_type: Literal["text", "image"]
    bbox: list[float]
    pages: list[int]
    representative_page: int
    occurrences: list[HeaderFooterOccurrenceRead]
    fragment_count: int
    binding_count: int


class HeaderFooterPreviewRead(ApiModel):
    """Read-only результат поиска в одной активной ревизии."""

    material_id: UUID
    revision: int
    page_count: int
    candidates: list[HeaderFooterCandidateRead]


class HeaderFooterApplyWrite(ApiModel):
    """Подтверждённый пользователем выбор для защищённого применения."""

    expected_revision: int = Field(ge=1)
    candidate_ids: list[str] = Field(min_length=1)


class HeaderFooterApplyRead(ApiModel):
    """Итог публикации следующей ревизии без выбранных элементов."""

    revision: int
    removed_occurrences: int
    removed_fragments: int
    transferred_bindings: int
    orphaned_binding_ids: list[UUID]


@dataclass(frozen=True, slots=True)
class Occurrence:
    page: int
    zone: Literal["header", "footer"]
    indexes: tuple[int, ...]
    bbox: Bbox
    text: str | None
    image_hash: int | None = None
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    kind: CandidateKind
    occurrences: tuple[Occurrence, ...]


def _normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n-–—|·•")


def _roman_value(value: str) -> int | None:
    if not value or not re.fullmatch(r"[ivxlcdm]+", value, re.IGNORECASE):
        return None
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = previous = 0
    for char in reversed(value.casefold()):
        current = values[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total or None


def _page_number(value: str) -> int | None:
    match = PAGE_NUMBER_RE.fullmatch(unicodedata.normalize("NFKC", value))
    if not match:
        return None
    token = match.group("number")
    return int(token) if token.isdigit() else _roman_value(token)


def _bbox(item: dict[str, object]) -> Bbox | None:
    raw = item.get("bbox")
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        box = tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if not all(0 <= value <= 1 for value in box) or box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box  # type: ignore[return-value]


def _union(boxes: list[Bbox]) -> Bbox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _average_hash(path: Path) -> int | None:
    try:
        with Image.open(path) as image:
            pixels = list(image.convert("L").resize((8, 8)).get_flattened_data())
    except (OSError, ValueError):
        return None
    average = sum(pixels) / len(pixels)
    return sum((value >= average) << index for index, value in enumerate(pixels))


def _zone(box: Bbox) -> Literal["header", "footer"] | None:
    center = (box[1] + box[3]) / 2
    if center <= MARGIN_FRACTION:
        return "header"
    if center >= 1 - MARGIN_FRACTION:
        return "footer"
    return None


def _same_line(
    left: tuple[int, dict[str, object], Bbox],
    right: tuple[int, dict[str, object], Bbox],
) -> bool:
    left_box, right_box = left[2], right[2]
    vertical = abs((left_box[1] + left_box[3]) / 2 - (right_box[1] + right_box[3]) / 2)
    gap = right_box[0] - left_box[2]
    return vertical <= LINE_VERTICAL_TOLERANCE and gap <= LINE_GAP_TOLERANCE


def page_occurrences(page: MaterialPage) -> list[Occurrence]:
    """Собрать цельные строки-кандидаты из элементов одной страницы."""
    text_items: dict[str, list[tuple[int, dict[str, object], Bbox]]] = {
        "header": [],
        "footer": [],
    }
    result: list[Occurrence] = []
    for index, item in enumerate(page.elements):
        box = _bbox(item)
        zone = _zone(box) if box else None
        if zone is None or box is None or box[3] - box[1] > MAX_ELEMENT_HEIGHT:
            continue
        kind = str(item.get("kind") or "paragraph")
        text = str(item.get("text") or "").strip()
        # Содержательный заголовок у края и смешанный многострочный абзац не
        # считаются колонтитулом: удалять часть одного элемента нельзя.
        if kind == "heading" or "\n" in text:
            continue
        if kind == "image":
            asset_path = item.get("asset_path")
            image_hash = _average_hash(material_path(str(asset_path))) if asset_path else None
            if image_hash is not None:
                result.append(Occurrence(page.page_number, zone, (index,), box, None, image_hash))
        elif text:
            text_items[zone].append((index, item, box))

    for zone, items in text_items.items():
        ordered = sorted(items, key=lambda entry: ((entry[2][1] + entry[2][3]) / 2, entry[2][0]))
        groups: list[list[tuple[int, dict[str, object], Bbox]]] = []
        for item in ordered:
            if groups and _same_line(groups[-1][-1], item):
                groups[-1].append(item)
            else:
                groups.append([item])
        for group in groups:
            text = " ".join(str(item[1].get("text") or "").strip() for item in group).strip()
            number = _page_number(text)
            result.append(
                Occurrence(
                    page.page_number,
                    zone,  # type: ignore[arg-type]
                    tuple(item[0] for item in group),
                    _union([item[2] for item in group]),
                    text,
                    page_number=number,
                )
            )
    return result


def _geometry_matches(left: Occurrence, right: Occurrence) -> bool:
    left_center = ((left.bbox[0] + left.bbox[2]) / 2, (left.bbox[1] + left.bbox[3]) / 2)
    right_center = ((right.bbox[0] + right.bbox[2]) / 2, (right.bbox[1] + right.bbox[3]) / 2)
    return all(
        abs(a - b) <= POSITION_TOLERANCE
        for a, b in zip(left_center, right_center, strict=True)
    )


def _matches(left: Occurrence, right: Occurrence) -> bool:
    if left.zone != right.zone or not _geometry_matches(left, right):
        return False
    if left.image_hash is not None or right.image_hash is not None:
        return (
            left.image_hash is not None
            and right.image_hash is not None
            and (left.image_hash ^ right.image_hash).bit_count() <= IMAGE_HASH_DISTANCE
        )
    if left.page_number is not None or right.page_number is not None:
        return left.page_number is not None and right.page_number is not None
    similarity = SequenceMatcher(
        None,
        _normalized_text(left.text or ""),
        _normalized_text(right.text or ""),
    ).ratio()
    return similarity >= TEXT_SIMILARITY


def _series_coverage(occurrences: list[Occurrence], parity: int | None) -> float:
    pages = sorted(item.page for item in occurrences if parity is None or item.page % 2 == parity)
    if not pages:
        return 0
    expected = [
        page
        for page in range(pages[0], pages[-1] + 1)
        if parity is None or page % 2 == parity
    ]
    return len(pages) / len(expected)


def _page_number_sequence(occurrences: list[Occurrence]) -> bool:
    offsets = Counter(
        item.page_number - item.page
        for item in occurrences
        if item.page_number is not None
    )
    return bool(offsets) and offsets.most_common(1)[0][1] / len(occurrences) >= MIN_SERIES_COVERAGE


def detect(pages: list[MaterialPage]) -> list[Candidate]:
    """Найти устойчивые повторяющиеся строки, номера и изображения."""
    if len(pages) < 3:
        return []
    occurrences = [item for page in pages for item in page_occurrences(page)]
    groups: list[list[Occurrence]] = []
    for occurrence in occurrences:
        group = next((items for items in groups if _matches(items[0], occurrence)), None)
        if group is None:
            groups.append([occurrence])
        else:
            group.append(occurrence)

    minimum = (
        MIN_SHORT_DOCUMENT_MATCHES
        if len(pages) <= SHORT_DOCUMENT_PAGES
        else MIN_LONG_DOCUMENT_MATCHES
    )
    candidates: list[Candidate] = []
    for group in groups:
        # Первое добавление в новую группу уже произошло выше; защитимся от
        # повторного элемента одной страницы, чтобы покрытие не завышалось.
        unique = list({item.page: item for item in group}.values())
        valid = [
            items
            for parity in (None, 0, 1)
            if len(
                items := [
                    item for item in unique if parity is None or item.page % 2 == parity
                ]
            )
            >= minimum
            and _series_coverage(items, parity) >= MIN_SERIES_COVERAGE
        ]
        if not valid:
            continue
        selected = max(valid, key=len)
        is_number = selected[0].page_number is not None
        if is_number and not _page_number_sequence(selected):
            continue
        kind: CandidateKind = "page_number" if is_number else selected[0].zone
        signature = (
            "image"
            if selected[0].image_hash is not None
            else _normalized_text(selected[0].text or "number")
        )
        pages_key = ",".join(str(item.page) for item in selected)
        identifier = hashlib.sha256(f"{kind}|{signature}|{pages_key}".encode()).hexdigest()[:16]
        candidates.append(
            Candidate(identifier, kind, tuple(sorted(selected, key=lambda item: item.page)))
        )
    return sorted(candidates, key=lambda item: (item.kind, item.occurrences[0].page, item.id))


def _material_pages(session: Session, material: Material) -> list[MaterialPage]:
    if (
        material.source_kind == MaterialSourceKind.TYPST
        or material.media_type != "application/pdf"
        or (material.page_count or 0) < 3
        or material.active_parse_revision < 1
    ):
        raise ProjectDomainError(
            "Поиск колонтитулов доступен для разобранного PDF из трёх и более страниц",
            status=422,
            code="header_footer_unsupported",
        )
    task = library.latest_task(session, material.id)
    if task and task.state in library.ACTIVE_TASK_STATES:
        raise ProjectConflictError(
            "Обработка материала уже идёт", code="material_processing_active"
        )
    return list(
        session.scalars(
            select(MaterialPage)
            .where(
                MaterialPage.material_id == material.id,
                MaterialPage.revision == material.active_parse_revision,
            )
            .order_by(MaterialPage.page_number)
        )
    )


def _overlaps(left: list[float], right: Bbox) -> bool:
    return left[0] < right[2] and left[2] > right[0] and left[1] < right[3] and left[3] > right[1]


def preview(session: Session, material_id: UUID) -> HeaderFooterPreviewRead:
    """Вернуть кандидатов активной ревизии, не изменяя материал."""
    material = library.material_or_404(session, material_id)
    pages = _material_pages(session, material)
    candidates = detect(pages)
    page_ids = {page.page_number: page.id for page in pages}
    fragments = list(
        session.scalars(
            select(MaterialFragment).where(
                MaterialFragment.material_id == material_id,
                MaterialFragment.page_id.in_(page_ids.values()),
            )
        )
    )
    binding_counts = dict(
        session.execute(
            select(Binding.fragment_id, func.count(Binding.id))
            .where(Binding.fragment_id.in_([item.id for item in fragments]))
            .group_by(Binding.fragment_id)
        ).all()
    ) if fragments else {}
    fragment_page = {page_id: number for number, page_id in page_ids.items()}
    result: list[HeaderFooterCandidateRead] = []
    for candidate in candidates:
        relevant = [
            fragment
            for fragment in fragments
            if any(
                occurrence.page == fragment_page.get(fragment.page_id)
                and _overlaps(fragment.bbox, occurrence.bbox)
                for occurrence in candidate.occurrences
            )
        ]
        boxes = [item.bbox for item in candidate.occurrences]
        result.append(
            HeaderFooterCandidateRead(
                id=candidate.id,
                kind=candidate.kind,
                text=candidate.occurrences[0].text,
                element_type="image" if candidate.occurrences[0].image_hash is not None else "text",
                bbox=list(_union(boxes)),
                pages=[item.page for item in candidate.occurrences],
                representative_page=candidate.occurrences[len(candidate.occurrences) // 2].page,
                occurrences=[
                    HeaderFooterOccurrenceRead(page=item.page, bbox=list(item.bbox))
                    for item in candidate.occurrences
                ],
                fragment_count=sum(len(item.indexes) for item in candidate.occurrences),
                binding_count=sum(binding_counts.get(fragment.id, 0) for fragment in relevant),
            )
        )
    return HeaderFooterPreviewRead(
        material_id=material.id,
        revision=material.active_parse_revision,
        page_count=len(pages),
        candidates=result,
    )


def _page_content(elements: list[dict[str, object]]) -> tuple[str, str]:
    plain = "\n".join(
        str(item.get("text") or "") for item in elements if item.get("kind") != "image"
    )
    markdown: list[str] = []
    for item in elements:
        text = str(item.get("text") or "")
        kind = item.get("kind")
        if kind == "heading":
            markdown.append(f"{'#' * int(item.get('level') or 2)} {text}")
        elif kind == "list":
            markdown.append(f"{'    ' * (int(item.get('level') or 1) - 1)}{text}")
        elif kind == "image" and item.get("asset_path"):
            markdown.append(f"![Изображение]({item['asset_path']})")
        else:
            markdown.append(text)
    return plain, "\n\n".join(markdown)


def _copy_pages_without(
    session: Session,
    pages: list[MaterialPage],
    revision: int,
    removed_by_page: dict[int, set[int]],
) -> None:
    """Скопировать страницы в новую ревизию, исключив выбранные целые элементы."""
    for page in pages:
        removed = removed_by_page.get(page.page_number, set())
        elements = [item for index, item in enumerate(page.elements) if index not in removed]
        text, markdown = _page_content(elements)
        session.add(
            MaterialPage(
                material_id=page.material_id,
                revision=revision,
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                text=text,
                markdown=markdown,
                quality=page.quality,
                confidence=page.confidence,
                parser_mode=page.parser_mode,
                elements=elements,
                diagnostics=sorted({*page.diagnostics, "header_footer_removed"}),
                image_path=page.image_path,
                reviewed_at=page.reviewed_at,
                created_at=utc_now(),
            )
        )


def _record_revision(
    session: Session,
    material: Material,
    old_revision: int,
    revision: int,
    selected_ids: set[str],
    removed_occurrences: int,
    removed_fragments: int,
) -> None:
    """Записать человеческое происхождение готовой ревизии колонтитулов."""
    storage_path, source_hash = revision_registry.inherit_source(
        session, material, old_revision
    )
    revision_registry.record_revision(
        session,
        material.id,
        revision,
        origin=MaterialRevisionOrigin.MANUAL_EDIT,
        parser_mode=material.parser_mode,
        parent_revision=old_revision,
        source_storage_path=storage_path,
        source_hash=source_hash,
        scope={"kind": "header_footer", "candidate_ids": sorted(selected_ids)},
        summary=revision_registry.revision_summary(session, material.id, revision)
        | {
            "removed_occurrences": removed_occurrences,
            "removed_fragments": removed_fragments,
        },
    )


def _selected_candidates(
    pages: list[MaterialPage], candidate_ids: list[str]
) -> tuple[set[str], list[Candidate]]:
    """Повторно найти и проверить выбранные кандидаты перед применением."""
    candidates = {item.id: item for item in detect(pages)}
    selected_ids = set(candidate_ids)
    if len(selected_ids) != len(candidate_ids) or not selected_ids <= candidates.keys():
        raise ProjectDomainError(
            "Выбранные колонтитулы больше не найдены",
            status=422,
            code="header_footer_selection_invalid",
        )
    return selected_ids, [candidates[item] for item in selected_ids]


def apply(
    session: Session, material_id: UUID, command: HeaderFooterApplyWrite
) -> HeaderFooterApplyRead:
    """Удалить выбранные кандидаты из текста и собрать следующую ревизию."""
    session.rollback()
    with session.begin():
        material = library.material_or_404(session, material_id)
        if material.active_parse_revision != command.expected_revision:
            raise ProjectConflictError(
                "Материал изменился после предпросмотра",
                code="stale_material_revision",
                context={"current_revision": material.active_parse_revision},
            )
        pages = _material_pages(session, material)
        selected_ids, selected = _selected_candidates(pages, command.candidate_ids)
        removed_by_page: dict[int, set[int]] = {}
        for candidate in selected:
            for occurrence in candidate.occurrences:
                removed_by_page.setdefault(occurrence.page, set()).update(occurrence.indexes)

        old_revision = material.active_parse_revision
        old_fragments = library.fragments_by_page(session, material_id, old_revision)
        revision = revision_registry.max_revision(session, material_id) + 1
        _copy_pages_without(session, pages, revision, removed_by_page)
        session.flush()
        new_fragments = library.rebuild_structure(session, material_id, revision)
        material.active_parse_revision = revision
        material.updated_at = utc_now()
        library.refresh_material_counters(session, material, revision)
        session.flush()
        transfer = transfer_bindings_on_revision(session, material_id, old_fragments, new_fragments)
        reindex_material(session, material_id)
        removed_occurrences = sum(len(item.occurrences) for item in selected)
        removed_fragments = sum(len(indexes) for indexes in removed_by_page.values())
        _record_revision(
            session,
            material,
            old_revision,
            revision,
            selected_ids,
            removed_occurrences,
            removed_fragments,
        )
        result = HeaderFooterApplyRead(
            revision=revision,
            removed_occurrences=removed_occurrences,
            removed_fragments=removed_fragments,
            transferred_bindings=transfer.transferred,
            orphaned_binding_ids=transfer.orphaned,
        )
        # Автосопоставление эталонных ответов best-effort, как после обычного OCR.
        from app.materials.worker import link_answers_projects

        link_answers_projects(session, material_id)
    return result
