"""Геометрия ссылки урока на материал: какие фрагменты она покрывает, разрез, склейка,
какую страницу рисует и перенос границ при новой ревизии (записка «Уроки» §3.2–§3.3).

Кусок — отрезок фрагментов активной ревизии в порядке чтения. Пустая граница
(`from_fragment_id`/`to_fragment_id` = None) — граница страницы.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BlockClass,
    LessonSourceRef,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
)
from app.projects.errors import ProjectDomainError


@dataclass(frozen=True, slots=True)
class OrderedFragment:
    id: UUID
    page: int
    block_id: UUID
    is_content: bool


@dataclass(frozen=True, slots=True)
class MaterialOrder:
    """Фрагменты диапазона страниц активной ревизии в порядке чтения."""

    fragments: list[OrderedFragment]
    index: dict[UUID, int]

    def first_on_page(self, page: int) -> int | None:
        return next((i for i, item in enumerate(self.fragments) if item.page == page), None)

    def is_last_on_page(self, position: int) -> bool:
        following = position + 1
        return (
            following >= len(self.fragments)
            or self.fragments[following].page != self.fragments[position].page
        )


@dataclass(frozen=True, slots=True)
class Bounds:
    page_from: int
    page_to: int
    from_fragment_id: UUID | None
    to_fragment_id: UUID | None


def load_order(session: Session, material: Material, page_from: int, page_to: int) -> MaterialOrder:
    """Фрагменты страниц активной ревизии; у неразобранного материала — пусто."""
    if material.active_parse_revision <= 0:
        return MaterialOrder([], {})
    rows = session.execute(
        select(MaterialFragment.id, MaterialPage.page_number, MaterialBlock.id,
               MaterialBlock.block_class)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(
            MaterialPage.material_id == material.id,
            MaterialPage.revision == material.active_parse_revision,
            MaterialPage.page_number.between(page_from, page_to),
        )
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
    )
    fragments = [
        OrderedFragment(fragment_id, page, block_id, block_class == BlockClass.CONTENT)
        for fragment_id, page, block_id, block_class in rows
    ]
    return MaterialOrder(fragments, {item.id: i for i, item in enumerate(fragments)})


def span(order: MaterialOrder, bounds: Bounds) -> tuple[int, int] | None:
    """Индексы первого и последнего фрагмента куска; None — во фрагментах пусто."""
    inside = [
        i for i, item in enumerate(order.fragments)
        if bounds.page_from <= item.page <= bounds.page_to
    ]
    if not inside:
        return None
    start = order.index.get(bounds.from_fragment_id, inside[0]) \
        if bounds.from_fragment_id else inside[0]
    end = order.index.get(bounds.to_fragment_id, inside[-1]) \
        if bounds.to_fragment_id else inside[-1]
    return (start, end) if start <= end else None


def content_fragment_ids(order: MaterialOrder, bounds: Bounds) -> list[UUID]:
    """Фрагменты куска, которые можно привязывать к теме: служебные блоки не в счёт."""
    covered = span(order, bounds)
    if covered is None:
        return []
    return [item.id for item in order.fragments[covered[0] : covered[1] + 1] if item.is_content]


def fragments_in_region(
    session: Session, material: Material, page: int, region: list[float]
) -> list[UUID]:
    """Содержательные фрагменты, центр которых попал в выделенную область страницы.

    Центр, а не пересечение: рамка, проведённая по схеме, почти всегда задевает края
    соседних абзацев, и привязывать их к теме было бы неправдой.
    """
    if material.active_parse_revision <= 0:
        return []
    x0, y0, x1, y1 = region
    rows = session.execute(
        select(MaterialFragment.id, MaterialFragment.bbox)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(
            MaterialPage.material_id == material.id,
            MaterialPage.revision == material.active_parse_revision,
            MaterialPage.page_number == page,
            MaterialBlock.block_class == BlockClass.CONTENT,
        )
        .order_by(MaterialFragment.sort_order)
    )
    inside = []
    for fragment_id, bbox in rows:
        if not bbox or len(bbox) != 4:
            continue
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        if x0 <= center_x <= x1 and y0 <= center_y <= y1:
            inside.append(fragment_id)
    return inside


def bounds_of(ref: LessonSourceRef) -> Bounds:
    """Границы сохранённой ссылки в виде, с которым работают функции модуля."""
    return Bounds(ref.page_from, ref.page_to, ref.from_fragment_id, ref.to_fragment_id)


def ids_between(session: Session, material: Material, first_id: UUID, last_id: UUID
                ) -> list[UUID]:
    """Все фрагменты от `first_id` до `last_id` включительно в порядке чтения ревизии.

    В отличие от `fragment_range` порядок аргументов важен: кусок, выбранный человеком,
    задан парой «начало, конец», и конец перед началом — ошибка данных, а не «выделили
    снизу вверх».
    """
    pages = dict(session.execute(
        select(MaterialFragment.id, MaterialPage.page_number)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(
            MaterialFragment.id.in_([first_id, last_id]),
            MaterialPage.material_id == material.id,
            MaterialPage.revision == material.active_parse_revision,
        )
    ).tuples().all())
    if len(pages) != len({first_id, last_id}):
        raise ProjectDomainError(
            "Фрагмент куска не найден в текущей ревизии материала",
            status=422, code="lesson_pinned_range",
        )
    order = load_order(session, material, min(pages.values()), max(pages.values()))
    start, end = order.index[first_id], order.index[last_id]
    if start > end:
        raise ProjectDomainError(
            "Начало куска стоит после его конца", status=422, code="lesson_pinned_range",
        )
    return [item.id for item in order.fragments[start : end + 1]]


def fragment_range(order: MaterialOrder, first_id: UUID, last_id: UUID) -> Bounds:
    """Выделенные фрагменты → границы куска; порядок выбора не важен."""
    if first_id not in order.index or last_id not in order.index:
        raise ProjectDomainError(
            "Фрагменты не найдены в текущей ревизии материала",
            status=422, code="lesson_fragment_not_found",
        )
    start, end = sorted((order.index[first_id], order.index[last_id]))
    return _normalized(order, start, end)


def _normalized(order: MaterialOrder, start: int, end: int) -> Bounds:
    """Граница, совпавшая с краем страницы, хранится как граница страницы."""
    first, last = order.fragments[start], order.fragments[end]
    return Bounds(
        page_from=first.page,
        page_to=last.page,
        from_fragment_id=None if order.first_on_page(first.page) == start else first.id,
        to_fragment_id=None if order.is_last_on_page(end) else last.id,
    )


def split(order: MaterialOrder, bounds: Bounds, fragment_id: UUID | None,
          after_page: int | None) -> tuple[Bounds, Bounds]:
    """«Вставить после этого абзаца»: кусок режется на два по фрагменту или странице."""
    if fragment_id is None:
        if after_page is None or not bounds.page_from <= after_page < bounds.page_to:
            raise ProjectDomainError(
                "Разрезать можно только между страницами куска",
                status=422, code="lesson_split_outside",
            )
        return (
            Bounds(bounds.page_from, after_page, bounds.from_fragment_id, None),
            Bounds(after_page + 1, bounds.page_to, None, bounds.to_fragment_id),
        )
    covered = span(order, bounds)
    position = order.index.get(fragment_id)
    if covered is None or position is None or not covered[0] <= position < covered[1]:
        raise ProjectDomainError(
            "Разрез должен быть внутри куска и не после последнего абзаца",
            status=422, code="lesson_split_outside",
        )
    current = order.fragments[position]
    following = order.fragments[position + 1]
    if order.is_last_on_page(position):
        first = Bounds(bounds.page_from, current.page, bounds.from_fragment_id, None)
        second = Bounds(current.page + 1, bounds.page_to, None, bounds.to_fragment_id)
    else:
        first = Bounds(bounds.page_from, current.page, bounds.from_fragment_id, current.id)
        second = Bounds(following.page, bounds.page_to, following.id, bounds.to_fragment_id)
    return first, second


def merge(order: MaterialOrder, first: Bounds, second: Bounds) -> Bounds | None:
    """«Убрать разрез»: соседние куски склеиваются, только если второй продолжает первый."""
    if second.page_from > first.page_to + 1 or second.page_from < first.page_to:
        return None
    if first.to_fragment_id is None and second.from_fragment_id is None:
        return None if second.page_from != first.page_to + 1 else _joined(first, second)
    first_span, second_span = span(order, first), span(order, second)
    if first_span is None or second_span is None or second_span[0] != first_span[1] + 1:
        return None
    return _joined(first, second)


def _joined(first: Bounds, second: Bounds) -> Bounds:
    return Bounds(first.page_from, second.page_to, first.from_fragment_id, second.to_fragment_id)


def owns_page_start(session: Session, ref: LessonSourceRef) -> bool:
    """Кусок начинается с верха `page_from`: перед граничным фрагментом нет содержательного."""
    if ref.from_fragment_id is None:
        return True
    boundary = session.get(MaterialFragment, ref.from_fragment_id)
    if boundary is None:
        return True
    earlier = session.scalar(
        select(MaterialFragment.id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(
            MaterialFragment.page_id == boundary.page_id,
            MaterialFragment.sort_order < boundary.sort_order,
            MaterialBlock.block_class == BlockClass.CONTENT,
        )
        .limit(1)
    )
    return earlier is None


def shown_pages(session: Session, refs: list[LessonSourceRef]) -> dict[UUID, list[int]]:
    """Режим «Страницы»: лист рисуется один раз — в куске, где лежит его первый фрагмент.

    Нет куска с началом страницы — лист достаётся первому по порядку урока куску.
    """
    starts: dict[tuple[UUID, int], UUID] = {}
    any_owner: dict[tuple[UUID, int], UUID] = {}
    for ref in refs:
        # Область рисует свой вырез и лист целиком не занимает — иначе страница пропала бы.
        if ref.material_id is None or ref.region_bbox is not None:
            continue
        starts_top = owns_page_start(session, ref)
        for page in range(ref.page_from, ref.page_to + 1):
            key = (ref.material_id, page)
            any_owner.setdefault(key, ref.id)
            if page > ref.page_from or starts_top:
                starts.setdefault(key, ref.id)
    result: dict[UUID, list[int]] = {ref.id: [] for ref in refs}
    for key, ref_id in any_owner.items():
        result[starts.get(key, ref_id)].append(key[1])
    for pages in result.values():
        pages.sort()
    return result


def transfer_refs_on_revision(
    session: Session,
    material_id: UUID,
    mapping: dict[UUID, MaterialFragment],
    new_fragment_ids: set[UUID],
) -> int:
    """Границы кусков идут за фрагментами новой ревизии тем же сопоставлением, что привязки.

    Не нашлась пара — граница деградирует до границы страницы с пометкой «Разрез сдвинут»:
    урок не ломается. Возвращает число сдвинутых границ.
    """
    material = session.get(Material, material_id)
    if material is None:
        return 0
    shifted = 0
    for ref in session.scalars(
        select(LessonSourceRef).where(LessonSourceRef.material_id == material_id)
    ):
        for field in ("from_fragment_id", "to_fragment_id"):
            fragment_id = getattr(ref, field)
            if fragment_id is None:
                continue
            if fragment_id in mapping:
                setattr(ref, field, mapping[fragment_id].id)
            elif fragment_id not in new_fragment_ids:
                setattr(ref, field, None)
                ref.boundary_shifted = True
                shifted += 1
        ref.material_revision = material.active_parse_revision
    return shifted
