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


def _build_selection(
    lines: Sequence[str],
    chain: list[_Series],
    dropped: list[_Series],
    expected_count: int | None,
) -> NumberedSeriesSelection:
    items: list[NumberedItem] = []
    for candidate in chain:
        items.extend(candidate.items)
    start = chain[0].items[0].source_index
    end = chain[-1].source_end
    ignored_before = tuple(line.strip() for line in lines[:start] if line.strip())
    ignored_after = tuple(line.strip() for line in lines[end:] if line.strip())
    warnings: list[str] = []
    if ignored_before:
        warnings.append(f"Перед списком пропущено строк: {len(ignored_before)}")
    if ignored_after:
        warnings.append(f"После списка пропущено строк: {len(ignored_after)}")
    if len(chain) > 1:
        gap_lines = 0
        for index in range(len(chain) - 1):
            gap_start = chain[index].source_end
            gap_end = chain[index + 1].items[0].source_index
            gap_lines += len([line for line in lines[gap_start:gap_end] if line.strip()])
        warnings.append(
            f"Список сшит из {len(chain)} частей после разрыва нумерации; "
            f"между частями пропущено строк: {gap_lines}"
        )
    if dropped:
        dropped_count = sum(len(candidate.items) for candidate in dropped)
        warnings.append(f"Не удалось пристроить к списку пунктов: {dropped_count}")
    if expected_count is not None and len(items) != expected_count:
        warnings.append(f"Ожидалось пунктов: {expected_count}; найдено: {len(items)}")
    return NumberedSeriesSelection(
        items=tuple(items),
        ignored_before=ignored_before,
        ignored_after=ignored_after,
        warnings=tuple(warnings),
        source_end=end,
    )


def _stitch_chain(candidates: list[_Series]) -> tuple[list[_Series], list[_Series]]:
    """Сшивает кандидатов, идущих вперёд по номеру, начиная с первого по тексту.

    Кандидат с номером, который не продолжает цепочку вперёд (перезапуск,
    приложение, повтор), в цепочку не попадает — это защищает случай
    «список, а за ним отдельное приложение с 1» от склеивания.
    """
    chain = [candidates[0]]
    dropped: list[_Series] = []
    for candidate in candidates[1:]:
        if candidate.items[0].number > chain[-1].items[-1].number:
            chain.append(candidate)
        else:
            dropped.append(candidate)
    return chain, dropped


def _longest_candidate_selection(
    lines: Sequence[str], candidates: list[_Series], expected_count: int | None
) -> NumberedSeriesSelection:
    longest = max(len(candidate.items) for candidate in candidates)
    best = [candidate for candidate in candidates if len(candidate.items) == longest]
    if len(best) != 1:
        return NumberedSeriesSelection(
            warnings=("Найдено несколько равноправных нумерованных списков",),
            ambiguous=True,
        )
    return _build_selection(lines, best, [], expected_count)


def select_numbered_series(
    lines: Sequence[str], expected_count: int | None = None
) -> NumberedSeriesSelection:
    """Выбирает основную нумерованную серию.

    Без ожидаемого числа пунктов ведёт себя как раньше — берёт единственного
    самого длинного кандидата и не гадает через разрывы нумерации: у вызовов
    без ориентира (например, сопоставление эталонных ответов по заголовкам)
    сшивка через пропущенный номер опаснее, чем отказ.

    С ожидаемым числом пунктов вначале ищет кандидата с точным совпадением
    длины, а если не находит — сшивает кандидатов, идущих вперёд по номеру,
    пока сумма пунктов не сойдётся с ожиданием.
    """
    candidates = [candidate for candidate in _series(lines) if candidate.items]
    if not candidates:
        return NumberedSeriesSelection()

    if expected_count is None:
        return _longest_candidate_selection(lines, candidates, expected_count)

    exact = [candidate for candidate in candidates if len(candidate.items) == expected_count]
    if len(exact) == 1:
        return _build_selection(lines, [exact[0]], [], expected_count)
    if len(exact) > 1:
        return NumberedSeriesSelection(
            warnings=("Найдено несколько равноправных нумерованных списков",),
            ambiguous=True,
        )

    chain, dropped = _stitch_chain(candidates)
    stitched_count = sum(len(candidate.items) for candidate in chain)
    if stitched_count == expected_count or len(chain) > 1:
        return _build_selection(lines, chain, dropped, expected_count)

    # Сшить нечего и точное совпадение не найдено — берём самого длинного
    # кандидата целиком, даже если он не первый по тексту.
    return _longest_candidate_selection(lines, candidates, expected_count)
