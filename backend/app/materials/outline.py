"""Оглавление материала: обнаружение печатной страницы «Оглавление» / «Содержание».

Часть общего приоритета из четырёх источников (закладки PDF → печатная
страница → распознанные заголовки → модель по кнопке пользователя), описанного
в `docs/architecture/textbook-outline.md`. Этот модуль отвечает только за
печатную страницу — работает по текстовому слою, без OCR и без разбора
материала, поэтому доступен сразу после загрузки файла.

Найденный список импортирует отдельный модуль `projects.program_outline`;
здесь остаётся только извлечение структуры из печатных страниц.
"""

from __future__ import annotations

import logging
import re
import shutil
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

import pymupdf as fitz

from app.materials.file_inspection import inspection_pool
from app.materials.outline_titles import GENERAL_TITLE_RE, TOPIC_TITLE_RE

log = logging.getLogger("tentex.materials.outline")
# Карточка опрашивается во время разбора; скан PDF нужен лишь при смене файла.
PRINTED_OUTLINE_CACHE_SIZE = 64
_printed_outline_lock = RLock()

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
# Разница кегля внутри одной строки PDF бывает дробной; пояснение под пунктом
# обычно отличается заметнее, чем соседние фрагменты одного заголовка.
WRAPPED_TITLE_SIZE_TOLERANCE = 0.75

_NUMBERING = r"\d+(?:\.\d+)*\.?"
# Заголовок и номер страницы через точечную (или похожую) выноску.
_LEADER_RE = re.compile(
    rf"^(?P<num>{_NUMBERING})?\s*(?P<title>.+?)[\s.·…]{{2,}}(?P<page>\d{{1,4}})\s*$"
)
# Запасной путь без выноски: заголовок, пробелы, число.
_PLAIN_RE = re.compile(rf"^(?P<num>{_NUMBERING})?\s*(?P<title>.+?)\s+(?P<page>\d{{1,4}})\s*$")
_ENDS_WITH_NUMBER_RE = re.compile(r"(?<=\D)\d{1,4}\s*$")
_SPACED_CHAPTER_RE = re.compile(r"^Г\s+л\s+а\s+в\s+а(?=\s)", re.IGNORECASE)
PhysicalLine = tuple[str, float, float, float]
ParsedLine = tuple[str | None, str, int, float]


def _candidate_pages(page_count: int) -> list[int]:
    leading = range(1, min(MAX_LEADING_CANDIDATES, page_count) + 1)
    trailing = range(max(1, page_count - TRAILING_CANDIDATES + 1), page_count + 1)
    ordered: dict[int, None] = {}
    for page in (*leading, *trailing):
        ordered.setdefault(page, None)
    return list(ordered)


def _page_lines(page: fitz.Page) -> list[PhysicalLine]:
    """Строки страницы с координатами текста.

    Координата ``y`` нужна для вынесенного отдельно номера страницы, а размер
    шрифта отличает перенос заголовка от мелкого пояснения под ним.
    """
    # Координаты текста нужны, бинарные изображения в оглавлении — нет.
    raw = page.get_text("dict", sort=True, flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
    lines: list[PhysicalLine] = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            x0 = min((span["bbox"][0] for span in spans), default=0.0)
            main_span = max(spans, key=lambda span: len(span.get("text", "")), default=None)
            size = float(main_span["size"]) if main_span else 0.0
            lines.append((text, x0, float(line["bbox"][1]), size))
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
    # Заголовок часто идёт после двух-трёх строк колонтитула. Проверяем
    # начало страницы, но не принимаем «Краткое содержание» за подробное
    # оглавление: у этого файла оно является отдельным коротким списком.
    for line in lines[:10]:
        head = line.strip().lower()
        if head.startswith(("оглавление", "содержание", "contents", "table of contents")):
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
    title = _SPACED_CHAPTER_RE.sub("Глава", title)
    if not title:
        return None
    try:
        page_number = int(match.group("page"))
    except ValueError:
        return None
    return match.group("num"), title, page_number


def _logical_lines(lines: list[PhysicalLine]) -> list[PhysicalLine]:
    """Приклеивает вынесенный справа номер к строке с той же координатой.

    PDF может отдать несколько заголовков подряд, а затем их номера отдельным
    блоком; соседство в порядке извлечения тогда не соответствует строке.
    """
    logical: list[PhysicalLine] = []
    attached: set[int] = set()
    for text, x0, y0, size in lines:
        if re.fullmatch(r"\d{1,4}", text.strip()):
            for index in range(len(logical) - 1, -1, -1):
                previous_text, previous_x, previous_y, previous_size = logical[index]
                if (
                    abs(y0 - previous_y) <= 2.5
                    and x0 > previous_x
                    and index not in attached
                ):
                    logical[index] = (
                        f"{previous_text} {text.strip()}", previous_x, previous_y,
                        previous_size,
                    )
                    attached.add(index)
                    break
            else:
                logical.append((text, x0, y0, size))
            continue
        logical.append((text, x0, y0, size))
    return logical


def _parsed_lines(lines: list[PhysicalLine]) -> list[ParsedLine]:
    """Склеивает переносы заголовка, не прихватывая пояснения меньшим кеглем."""
    parsed: list[ParsedLine] = []
    pending: PhysicalLine | None = None
    for text, x0, y0, size in _logical_lines(lines):
        result = _parse_line(text.strip())
        if result is None:
            same_entry = (
                pending is not None
                and 0 <= y0 - pending[2] <= 20
                and abs(size - pending[3]) <= WRAPPED_TITLE_SIZE_TOLERANCE
            )
            pending = (
                (f"{pending[0]} {text.strip()}", pending[1], y0, size)
                if same_entry and pending is not None
                else (text.strip(), x0, y0, size)
            )
            continue
        if (
            pending is not None
            and 0 <= y0 - pending[2] <= 20
            and abs(size - pending[3]) <= WRAPPED_TITLE_SIZE_TOLERANCE
        ):
            combined = _parse_line(f"{pending[0]} {text.strip()}")
            if combined is not None:
                result = combined
                x0 = pending[1]
        pending = None
        num, title, page_number = result
        parsed.append((num, title, page_number, x0))
    return parsed


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


def _normalize_named_hierarchy(items: list[dict[str, object]]) -> None:
    """Восстанавливает `часть → тема/глава → пункт` без видимых отступов.

    Некоторые издательские PDF выравнивают все строки оглавления по одной
    левой границе. В таком файле геометрия бесполезна, но явные маркеры части
    и темы однозначно задают уровни. Список меняется на месте перед возвратом.
    """
    titles = [str(item["title"]).strip() for item in items]
    if not any(GENERAL_TITLE_RE.match(title) for title in titles):
        return
    if not any(TOPIC_TITLE_RE.match(title) for title in titles):
        return
    inside_subsection = False
    for item, title in zip(items, titles, strict=True):
        if GENERAL_TITLE_RE.match(title):
            item["level"] = 1
            inside_subsection = False
        elif TOPIC_TITLE_RE.match(title):
            item["level"] = 2
            inside_subsection = True
        elif inside_subsection:
            item["level"] = 3


def _extract_page_items(
    page: fitz.Page, *, max_page: int, continuation: bool = False
) -> list[dict[str, object]] | None:
    lines = _page_lines(page)
    plain = [text for text, *_ in lines]
    if not continuation and _toc_page_kind(plain) is None:
        return None

    # Номер страницы не может далеко уйти за объём книги — это и отсекает
    # колонтитул с годом («ИУ-6, МГТУ..., 2023») и страницу-обманку вроде
    # списка литературы с годами изданий, случайно прошедшую первый фильтр.
    page_bound = max_page + max(20, max_page // 4)
    parsed: list[ParsedLine] = []
    for num, title, page_number, x0 in _parsed_lines(lines):
        if page_number < 1 or page_number > page_bound:
            continue
        parsed.append((num, title, page_number, x0))
    if len(parsed) < MIN_TOC_LINES:
        return None

    # Страницы идут по возрастанию; одиночные выбросы отбрасываются, а не
    # валят всю страницу. Это же отсекает страницу-обманку вроде списка
    # литературы с годами изданий — они идут вразнобой (по алфавиту автора),
    # а не по возрастанию, и после фильтра почти ничего не остаётся.
    filtered: list[ParsedLine] = []
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
        stat = path.stat()
        # lru_cache сам не объединяет одновременные промахи: первый опрос
        # не должен запустить несколько одинаковых сканов в потоках API.
        with _printed_outline_lock:
            result = _cached_printed_outline(
                path.resolve(), page_count, stat.st_mtime_ns, stat.st_size
            )
            return deepcopy(result)
    except (OSError, RuntimeError, ValueError):
        log.exception("Не удалось прочитать печатное оглавление")
        return None


@lru_cache(maxsize=PRINTED_OUTLINE_CACHE_SIZE)
def _cached_printed_outline(
    path: Path, page_count: int, modified_ns: int, size: int
) -> tuple[list[dict[str, object]], list[int]] | None:
    """Кэшировать также отсутствие оглавления; stat входит в ключ снимка."""
    return inspection_pool.submit(_local_printed_outline, path, page_count).result()


def _local_printed_outline(
    path: Path, page_count: int,
) -> tuple[list[dict[str, object]], list[int]] | None:
    """Полсотни страниц проверяются локально, а память MuPDF остаётся вне API."""
    with TemporaryDirectory(prefix="tentex-outline-") as temporary:
        local = Path(temporary) / "source.pdf"
        shutil.copyfile(path, local)
        return _scan_printed_outline(local, page_count)


def _scan_printed_outline(
    path: Path, page_count: int
) -> tuple[list[dict[str, object]], list[int]] | None:
    with fitz.open(path) as document:
        total = min(page_count, document.page_count)
        weak_start: tuple[int, list[dict[str, object]]] | None = None
        for page_number in _candidate_pages(total):
            page = document[page_number - 1]
            kind = _toc_page_kind([text for text, *_ in _page_lines(page)])
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
        continued = _extract_page_items(
            document[next_page - 1], max_page=max_page, continuation=True
        )
        if continued is None:
            break
        if int(continued[0]["page"]) < int(items[-1]["page"]):
            break
        items.extend(continued)
        source_pages.append(next_page)
        next_page += 1
    _normalize_named_hierarchy(items)
    return items, source_pages
