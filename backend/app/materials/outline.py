"""Оглавление материала: обнаружение печатной страницы «Оглавление» / «Содержание».

Часть общего приоритета из четырёх источников (закладки PDF → печатная
страница → распознанные заголовки → модель по кнопке пользователя), описанного
в `docs/architecture/textbook-outline.md`. Этот модуль отвечает только за
печатную страницу — работает по текстовому слою, без OCR и без разбора
материала, поэтому доступен сразу после загрузки файла.

Импорт найденного оглавления в настоящую программу (`ProgramNode`) не
реализован — это заведомый максимум текущего захода: вытащить и показать
оглавление, не больше.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

# Кандидаты — начало книги и последние страницы: в русских учебниках
# содержание нередко печатают в конце, а не сразу после титула.
MAX_LEADING_CANDIDATES = 40
TRAILING_CANDIDATES = 10
# Сколько соседних страниц может занимать одно оглавление (длинный учебник
# с многими главами не влезает в один лист). Найдено на реальном учебнике:
# подробное «Оглавление» заняло 14 страниц — прежний запас в 5 обрезал его
# на середине части I.
MAX_MERGED_PAGES = 20

TITLE_MARKERS = ("оглавление", "содержание", "contents", "table of contents")
MIN_TOC_LINES = 8
MIN_TOC_LINE_RATIO = 0.5
# Шаг отступа одного уровня вложенности при кластеризации без нумерации, в
# пунктах PDF — тот же порядок, что и у распознавания структуры страницы.
LEVEL_INDENT_STEP = 6.0

_NUMBERING = r"\d+(?:\.\d+)*\.?"
# Заголовок и номер страницы через точечную (или похожую) выноску.
_LEADER_RE = re.compile(
    rf"^(?P<num>{_NUMBERING})?\s*(?P<title>.+?)[\s.·…]{{2,}}(?P<page>\d{{1,4}})\s*$"
)
# Запасной путь без выноски: заголовок, пробелы, число.
_PLAIN_RE = re.compile(rf"^(?P<num>{_NUMBERING})?\s*(?P<title>.+?)\s+(?P<page>\d{{1,4}})\s*$")
_ENDS_WITH_NUMBER_RE = re.compile(r"(?<=\D)\d{1,4}\s*$")


def _candidate_pages(page_count: int) -> list[int]:
    leading = range(1, min(MAX_LEADING_CANDIDATES, page_count) + 1)
    trailing = range(max(1, page_count - TRAILING_CANDIDATES + 1), page_count + 1)
    ordered: dict[int, None] = {}
    for page in (*leading, *trailing):
        ordered.setdefault(page, None)
    return list(ordered)


def _page_lines(page: fitz.Page) -> list[tuple[str, float]]:
    """Строки страницы с левой границей (`x0`) — нужна для уровня без нумерации."""
    raw = page.get_text("dict", sort=True)
    lines: list[tuple[str, float]] = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            x0 = min((span["bbox"][0] for span in spans), default=0.0)
            lines.append((text, x0))
    return lines


def _toc_page_kind(lines: list[str]) -> str | None:
    """`"strong"` — заголовок страницы буквально начинается с «Оглавление»/
    «Содержание»; `"weak"` — заголовка нет (например, это уже продолжение),
    но плотность выносок в номера страниц похожа на оглавление; `None` — не
    похоже совсем.

    Найдено на реальном учебнике: короткое «Краткое содержание» (только
    части книги, 2 страницы) стоит в файле раньше подробного «Оглавление»
    (все главы, 14 страниц) — оба проходят плотностный фильтр одинаково, но
    заголовок различает их однозначно. Сканирование ниже выбирает первую
    `"strong"`-страницу, если она есть, а не просто первую подходящую."""
    if not lines:
        return None
    head = lines[0].strip().lower()
    if any(head.startswith(marker) for marker in TITLE_MARKERS):
        return "strong"
    if len(lines) < MIN_TOC_LINES:
        return None
    ending = sum(1 for line in lines if _ENDS_WITH_NUMBER_RE.search(line))
    return "weak" if ending / len(lines) >= MIN_TOC_LINE_RATIO else None


def _parse_line(line: str) -> tuple[str | None, str, int] | None:
    match = _LEADER_RE.match(line) or _PLAIN_RE.match(line)
    if not match:
        return None
    title = match.group("title").strip(" .·…")
    if not title:
        return None
    try:
        page_number = int(match.group("page"))
    except ValueError:
        return None
    return match.group("num"), title, page_number


def _level_from_numbering(num: str) -> int:
    segments = [segment for segment in num.strip(".").split(".") if segment]
    return max(1, min(4, len(segments)))


def _cluster_levels(indents: list[float]) -> list[int]:
    """Без нумерации уровень идёт от левой границы строки: соседние отступы в
    пределах `LEVEL_INDENT_STEP` — один уровень, дальше — следующий, максимум
    третий (без нумерации глубже почти никогда не печатают)."""
    if not indents:
        return []
    distinct = sorted({round(value, 1) for value in indents})
    level_of: dict[float, int] = {}
    level = 1
    previous: float | None = None
    for value in distinct:
        if previous is not None and value - previous > LEVEL_INDENT_STEP:
            level = min(3, level + 1)
        level_of[value] = level
        previous = value
    return [level_of[round(value, 1)] for value in indents]


def _extract_page_items(page: fitz.Page, *, max_page: int) -> list[dict[str, object]] | None:
    lines = _page_lines(page)
    plain = [text for text, _ in lines]
    if _toc_page_kind(plain) is None:
        return None

    # Номер страницы не может далеко уйти за объём книги — это и отсекает
    # колонтитул с годом («ИУ-6, МГТУ..., 2023») и страницу-обманку вроде
    # списка литературы с годами изданий, случайно прошедшую первый фильтр.
    page_bound = max_page + max(20, max_page // 4)
    parsed: list[tuple[str | None, str, int, float]] = []
    for text, x0 in lines:
        result = _parse_line(text.strip())
        if result is None:
            continue
        num, title, page_number = result
        if page_number < 1 or page_number > page_bound:
            continue
        parsed.append((num, title, page_number, x0))
    if len(parsed) < MIN_TOC_LINES:
        return None

    # Страницы идут по возрастанию; одиночные выбросы отбрасываются, а не
    # валят всю страницу. Это же отсекает страницу-обманку вроде списка
    # литературы с годами изданий — они идут вразнобой (по алфавиту автора),
    # а не по возрастанию, и после фильтра почти ничего не остаётся.
    filtered: list[tuple[str | None, str, int, float]] = []
    last_page = 0
    for entry in parsed:
        if entry[2] < last_page:
            continue
        filtered.append(entry)
        last_page = entry[2]
    if len(filtered) < MIN_TOC_LINES:
        return None

    numbered_ratio = sum(1 for entry in filtered if entry[0]) / len(filtered)
    if numbered_ratio >= 0.6:
        levels = [_level_from_numbering(entry[0]) if entry[0] else 1 for entry in filtered]
    else:
        levels = _cluster_levels([entry[3] for entry in filtered])

    return [
        {"level": level, "title": title, "page": page_number}
        for (_, title, page_number, _), level in zip(filtered, levels, strict=True)
    ]


def find_printed_outline(
    path: Path, page_count: int
) -> tuple[list[dict[str, object]], list[int]] | None:
    """Первая найденная печатная страница «Оглавление» — с продолжением на
    соседних страницах, если оно есть. `None`, если ни один кандидат не подошёл.

    Необязательное улучшение поверх основного пути: отсутствующий или битый
    файл не должен ронять вызывающую сторону (загрузку, просмотр Библиотеки).
    """
    if path.suffix.lower() != ".pdf" or page_count < 1 or not path.exists():
        return None
    try:
        return _scan_printed_outline(path, page_count)
    except Exception:
        return None


def _scan_printed_outline(
    path: Path, page_count: int
) -> tuple[list[dict[str, object]], list[int]] | None:
    with fitz.open(path) as document:
        total = min(page_count, document.page_count)
        weak_start: tuple[int, list[dict[str, object]]] | None = None
        for page_number in _candidate_pages(total):
            page = document[page_number - 1]
            kind = _toc_page_kind([text for text, _ in _page_lines(page)])
            if kind is None:
                continue
            items = _extract_page_items(page, max_page=page_count)
            if items is None:
                continue
            if kind == "strong":
                return _merge_from(document, page_number, items, total, max_page=page_count)
            if weak_start is None:
                weak_start = (page_number, items)
        if weak_start is not None:
            return _merge_from(document, *weak_start, total, max_page=page_count)
    return None


def _merge_from(
    document: fitz.Document,
    page_number: int,
    items: list[dict[str, object]],
    total: int,
    *,
    max_page: int,
) -> tuple[list[dict[str, object]], list[int]]:
    """Печатное оглавление может занимать несколько листов подряд — тянем
    вперёд от найденной страницы, пока следующая всё ещё разбирается как
    её продолжение."""
    source_pages = [page_number]
    next_page = page_number + 1
    while len(source_pages) < MAX_MERGED_PAGES and next_page <= total:
        continued = _extract_page_items(document[next_page - 1], max_page=max_page)
        if continued is None:
            break
        items.extend(continued)
        source_pages.append(next_page)
        next_page += 1
    return items, source_pages
