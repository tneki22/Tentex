import re
from collections.abc import Sequence
from dataclasses import dataclass, field

NUMBERED_ITEM_RE = re.compile(
    r"^\s*(?:(?P<delimited>\d{1,4})[.)](?!\d)\s*|"
    r"(?P<spaced>\d{1,4})\s+)(?P<text>\S.*?)\s*$"
)


@dataclass(frozen=True, slots=True)
class NumberedItem:
    number: int
    text: str
    source_index: int


@dataclass(frozen=True, slots=True)
class NumberedSeriesSelection:
    items: tuple[NumberedItem, ...] = ()
    ignored_before: tuple[str, ...] = ()
    ignored_after: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    ambiguous: bool = False
    source_end: int = 0


@dataclass(slots=True)
class _Series:
    items: list[NumberedItem] = field(default_factory=list)
    source_end: int = 0


def numbered_item(line: str, source_index: int) -> NumberedItem | None:
    match = NUMBERED_ITEM_RE.match(line)
    if match is None:
        return None
    number = int(match.group("delimited") or match.group("spaced"))
    return NumberedItem(number=number, text=match.group("text").strip(), source_index=source_index)


def _series(lines: Sequence[str]) -> list[_Series]:
    result: list[_Series] = []
    current: _Series | None = None
    for source_index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        item = numbered_item(line, source_index)
        if item is not None:
            if current is None or item.number != current.items[-1].number + 1:
                current = _Series()
                result.append(current)
            current.items.append(item)
            current.source_end = source_index + 1
            continue
        if current is not None:
            previous = current.items[-1]
            current.items[-1] = NumberedItem(
                number=previous.number,
                text=f"{previous.text} {line}",
                source_index=previous.source_index,
            )
            current.source_end = source_index + 1
    return result


def select_numbered_series(
    lines: Sequence[str], expected_count: int | None = None
) -> NumberedSeriesSelection:
    """Выбирает одну непрерывную нумерованную серию и не склеивает её через сброс."""
    candidates = [candidate for candidate in _series(lines) if candidate.items]
    if not candidates:
        return NumberedSeriesSelection()

    if expected_count is not None:
        best = [candidate for candidate in candidates if len(candidate.items) == expected_count]
        if not best:
            longest = max(len(candidate.items) for candidate in candidates)
            best = [candidate for candidate in candidates if len(candidate.items) == longest]
    else:
        longest = max(len(candidate.items) for candidate in candidates)
        best = [candidate for candidate in candidates if len(candidate.items) == longest]

    if len(best) != 1:
        return NumberedSeriesSelection(
            warnings=("Найдено несколько равноправных нумерованных списков",),
            ambiguous=True,
        )

    selected = best[0]
    start = selected.items[0].source_index
    end = selected.source_end
    ignored_before = tuple(line.strip() for line in lines[:start] if line.strip())
    ignored_after = tuple(line.strip() for line in lines[end:] if line.strip())
    warnings: list[str] = []
    if ignored_before:
        warnings.append(f"Перед списком пропущено строк: {len(ignored_before)}")
    if ignored_after:
        warnings.append(f"После списка пропущено строк: {len(ignored_after)}")
    if expected_count is not None and len(selected.items) != expected_count:
        warnings.append(
            f"Ожидалось пунктов: {expected_count}; найдено в основной серии: {len(selected.items)}"
        )
    return NumberedSeriesSelection(
        items=tuple(selected.items),
        ignored_before=ignored_before,
        ignored_after=ignored_after,
        warnings=tuple(warnings),
        source_end=end,
    )
