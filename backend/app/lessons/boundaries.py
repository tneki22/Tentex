"""Границы быстрого урока: уточнение диапазона оглавления и разрезы по подпунктам.

Чистые функции без базы — их и тестируют. Позиция в материале — пара
`(страница, индекс фрагмента на странице)`; кусок урока — полуинтервал
`[начало, конец)`. Индекс 0 означает «с начала страницы».
Правила — записка вертикали «Уроки» §4.1.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

Position = tuple[int, int]
TitleMatcher = Callable[[str, str], bool]


@dataclass(frozen=True, slots=True)
class FragmentView:
    id: UUID
    text: str
    is_heading: bool
    level: int | None
    is_content: bool
    block_id: UUID


@dataclass(frozen=True, slots=True)
class OutlineRange:
    """Диапазон узла программы в одном материале."""

    node_id: UUID
    title: str
    page_from: int
    page_to: int
    depth: int = 0


@dataclass(frozen=True, slots=True)
class NextItem:
    title: str
    page: int


@dataclass(frozen=True, slots=True)
class Segment:
    """Кусок source-блока."""

    page_from: int
    page_to: int
    from_fragment_id: UUID | None
    to_fragment_id: UUID | None
    start: Position
    end: Position


@dataclass(frozen=True, slots=True)
class Piece:
    """Заголовок подпункта (или его отсутствие у первого куска) и кусок после него."""

    heading: OutlineRange | None
    segment: Segment | None


Pages = Mapping[int, Sequence[FragmentView]]


def _back_over_service(fragments: Sequence[FragmentView], index: int) -> int:
    """Служебные фрагменты перед заголовком (колонтитул) уходят со следующим куском."""
    while index > 0 and not fragments[index - 1].is_content:
        index -= 1
    return index


def find_heading(
    fragments: Sequence[FragmentView],
    title: str,
    matches: TitleMatcher,
    *,
    start_index: int = 0,
    max_level: int | None = None,
    fallback: bool = True,
) -> int | None:
    """Индекс заголовка на странице: совпавший с `title`, иначе не глубже `max_level`."""
    headings = [
        index
        for index in range(start_index, len(fragments))
        if fragments[index].is_heading and fragments[index].is_content
    ]
    for index in headings:
        if matches(fragments[index].text, title):
            return index
    if not fallback:
        return None
    for index in headings:
        level = fragments[index].level
        if max_level is None or level is None or level <= max_level:
            return index
    return None


def refine_range(
    pages: Pages,
    *,
    title: str,
    page_from: int,
    page_to: int,
    next_item: NextItem | None,
    page_count: int | None,
    matches: TitleMatcher,
) -> tuple[Position, Position]:
    """Уточнить начало и конец темы по заголовкам на граничных страницах."""
    start: Position = (page_from, 0)
    max_level: int | None = None
    first_page = pages.get(page_from)
    if first_page:
        heading = find_heading(first_page, title, matches, fallback=False)
        if heading is not None:
            start = (page_from, _back_over_service(first_page, heading))
            max_level = first_page[heading].level

    end: Position = (page_to + 1, 0)
    if next_item is None:
        return start, end

    if next_item.page == page_from and first_page:
        cut = find_heading(
            first_page, next_item.title, matches, start_index=start[1] + 1, max_level=max_level
        )
        if cut is not None:
            end = (page_from, _back_over_service(first_page, cut))
        return start, end

    if next_item.page != page_to + 1:
        return start, end
    if page_count is not None and next_item.page > page_count:
        return start, end

    shared = pages.get(next_item.page)
    if shared is None or not shared:
        # Страница не разобрана: целиком, она общая со следующей темой.
        return start, (next_item.page + 1, 0)
    if not any(fragment.is_content for fragment in shared):
        return start, end
    cut = find_heading(shared, next_item.title, matches, max_level=max_level)
    if cut is None:
        return start, (next_item.page + 1, 0)
    return start, (next_item.page, _back_over_service(shared, cut))


def split_by_children(
    pages: Pages,
    *,
    start: Position,
    end: Position,
    children: Sequence[OutlineRange],
    matches: TitleMatcher,
) -> list[Piece]:
    """Разрезать `[start, end)` по подпунктам; пустой кусок остаётся только заголовком."""
    cuts: list[tuple[Position, OutlineRange]] = []
    for child in sorted(children, key=lambda item: item.page_from):
        if child.page_from < start[0]:
            # Диапазон подпункта из оглавления вне темы — разрезать нечем.
            continue
        page = pages.get(child.page_from)
        position: Position = (child.page_from, 0)
        if page:
            floor = start[1] + 1 if child.page_from == start[0] else 0
            heading = find_heading(page, child.title, matches, start_index=floor, fallback=False)
            if heading is not None:
                position = (child.page_from, _back_over_service(page, heading))
        position = max(position, start)
        if position >= end:
            continue
        if cuts and position < cuts[-1][0]:
            position = cuts[-1][0]
        cuts.append((position, child))

    bounds: list[tuple[Position, OutlineRange | None]] = [(start, None), *cuts]
    pieces: list[Piece] = []
    for index, (segment_start, heading) in enumerate(bounds):
        segment_end = bounds[index + 1][0] if index + 1 < len(bounds) else end
        segment = to_segment(pages, segment_start, segment_end)
        if segment is not None or heading is not None:
            pieces.append(Piece(heading, segment))
    return pieces


def to_segment(pages: Pages, start: Position, end: Position) -> Segment | None:
    """Полуинтервал позиций → страницы и граничные фрагменты ссылки."""
    if start >= end:
        return None
    page_from, from_index = start
    from_fragment_id = None
    first_page = pages.get(page_from) or ()
    if from_index > 0:
        if from_index >= len(first_page):
            page_from, from_index = page_from + 1, 0
        else:
            from_fragment_id = first_page[from_index].id

    end_page, end_index = end
    if end_index == 0:
        page_to, to_fragment_id = end_page - 1, None
    else:
        page_to, to_fragment_id = end_page, pages[end_page][end_index - 1].id
    if page_to < page_from:
        return None
    if (page_from, from_index) >= end:
        return None
    return Segment(
        page_from, page_to, from_fragment_id, to_fragment_id, (page_from, from_index), end
    )


def fragments_in(pages: Pages, start: Position, end: Position) -> list[FragmentView]:
    """Фрагменты в полуинтервале, по порядку чтения."""
    result: list[FragmentView] = []
    for page_number in range(start[0], end[0] + 1):
        fragments = pages.get(page_number) or ()
        for index, fragment in enumerate(fragments):
            if start <= (page_number, index) < end:
                result.append(fragment)
    return result


def estimate_minutes(characters: int) -> int | None:
    """Символы содержательного текста ÷ 1200 в минуту, округление до 5 минут."""
    if characters <= 0:
        return None
    return max(5, round(characters / 1200 / 5) * 5)
