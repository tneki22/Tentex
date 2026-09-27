"""Нарезка активной ревизии материала на retrieval-куски.

Кусок — единица поиска по смыслу и цитаты в чате, поэтому он обязан быть
самостоятельным текстом, а не строкой. Разбор PDF даёт блок на каждый заголовок:
у родительского раздела («Сети OTN») блок состоит из одного заголовка, а текст
лежит в дочерних блоках. Нарезка по одному блоку превращала такие заголовки в
куски из двух слов, и они выигрывали у настоящего текста по cosine: короткий
текст из слов запроса почти совпадает с запросом.

Поэтому блоки идут последовательными секциями, заголовочные и мелкие секции
склеиваются с соседями до `target`, крупные режутся на близкие по размеру части
без огрызков в хвосте. Колонтитулы и номера страниц в кусок не попадают. Вектор
считается по тексту с контекстной строкой «материал — раздел», сам текст куска
остаётся чистым для выдачи и чата.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materials.naming import material_display_name
from app.models import (
    BlockClass,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialSourceKind,
    PageQuality,
    RetrievalChunkKind,
    TypstSourceChunk,
)

#: Единицы — `count_tokens`, у русского текста это ≈ 0,73 токена XLM-R/E5.
#: 360 таких единиц с контекстной строкой укладываются в окно E5 в 512 токенов;
#: прежние 480 обрезались моделью у двух третей крупных кусков.
DEFAULT_TARGET_TOKENS = 280
DEFAULT_MAX_TOKENS = 360
DEFAULT_OVERLAP_TOKENS = 48

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|\n{2,}")
_VISUAL_ONLY = re.compile(r"^\s*\[Изображение(?:[^]]*)?]\s*$", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^\s*[-–—(]?\s*(?:\d{1,4}|[ivxlc]{1,6})\s*[-–—)]?\s*$", re.IGNORECASE)
_RUNNING_KEY = re.compile(r"[\d\W_]+", re.UNICODE)
_TYPST_HEADING = re.compile(r"^\s*(=+)\s*(.*?)\s*$")
_TYPST_NOISE = re.compile(r"^\s*(?:=+\s*.*|//.*|#\w+\(\)|#pagebreak\(.*\))?\s*$")

#: Служебные разделы, которые разбор не пометил: сегментация знает только точные
#: «Оглавление» и «Литература», а в книгах бывают «Краткое содержание»,
#: «Рекомендуемая и использованная литература» и заголовки выходных данных.
_SERVICE_TITLE = re.compile(
    r"^(?:(?:(?:краткое\s+)?(?:оглавление|содержание)|(?:table\s+of\s+)?contents"
    r"|(?:рекомендуемая\s+)?(?:и\s+)?(?:использованная\s+)?литература"
    r"|(?:список|перечень)\s+(?:рекомендуемой\s+|использованной\s+)?литературы"
    r"|(?:список|перечень)\s+(?:использованных\s+)?источников|библиографический\s+список"
    r"|библиография|references|bibliography)[\s.:]*$|(?:ббк|удк|isbn)[\s:])",
    re.IGNORECASE,
)
#: Строка оглавления: заполнитель из точек до номера страницы.
_TOC_LEADER = re.compile(r"[.…·](?:\s?[.…·]){5,}")
#: Номер раздела «2.2.6.» и маркеры глав: по ним ищется родительский раздел.
_NUMBERED = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3})*)\.?(?=\s|$)")
_PART_MARK = re.compile(
    r"^\s*(?:часть|part|приложение|appendix)\s+[\dIVXLCА-ЯA-Z]{1,6}\b", re.IGNORECASE
)
_CHAPTER_MARK = re.compile(
    r"^\s*(?:(?:глава|лекция|тема|раздел|модуль|вопрос|билет|chapter|lecture|section)"
    r"\s*№?\s*[\dIVXLC]{1,6}\b|§\s*\d)",
    re.IGNORECASE,
)
#: Typst-код преамбулы: правила оформления и функции, а не текст материала.
_TYPST_CODE = re.compile(
    r"^\s*(?:#(?:let|set|show|import|include)\b|//|[\w-]+\s*:\s|[)\]}]+[,;]?\s*$"
    r"|(?:let|if|else|return|for|while)\b|\}|\"|\w+\s*\[)"
)
_TYPST_GRAPH = re.compile(r"\"\s*(?:strict\s+)?(?:di)?graph\s*\{")
_TYPST_COMMENT = re.compile(r"(?:^|\s+)//.*$")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

#: Строка повторяется на стольких страницах — это колонтитул, а не содержание.
_RUNNING_MIN_PAGES = 4
_RUNNING_MAX_CHARS = 120
_TITLE_PART_CHARS = 120


def count_tokens(text: str) -> int:
    """Стабильная локальная оценка; runtime модели проверяет фактический лимит."""
    return len(_TOKEN_RE.findall(text))


@dataclass(frozen=True)
class ChunkAtom:
    text: str
    fragment_id: UUID | None = None
    page: int | None = None
    quality: PageQuality | None = None
    locator: dict[str, object] = field(default_factory=dict)
    heading: bool = False
    section: int = 0


@dataclass(frozen=True)
class Section:
    """Непрерывный кусок структуры материала: блок PDF или source chunk Typst."""

    block_id: UUID | None
    title: str | None
    atoms: list[ChunkAtom]
    heading_only: bool
    group: str | None = None
    #: Уровень заголовка из разбора; у PDF ненадёжен и сравнивается только внутри
    #: одного материала.
    level: int | None = None


@dataclass(frozen=True)
class ChunkDraft:
    material_id: UUID
    revision: int
    block_id: UUID | None
    kind: RetrievalChunkKind
    title: str | None
    text: str
    token_count: int
    page_from: int | None
    page_to: int | None
    quality: PageQuality | None
    fragment_ids: list[UUID]
    locator: dict[str, object]
    content_hash: str
    #: Текст для embedding: контекстная строка и сам кусок. В БД не хранится.
    embedding_text: str = ""


def _tokens(atoms: list[ChunkAtom]) -> int:
    return sum(count_tokens(atom.text) for atom in atoms)


def _split_large_atom(atom: ChunkAtom, maximum: int) -> list[ChunkAtom]:
    """Разрезать один абзац по предложениям, в крайнем случае — по словам."""
    if count_tokens(atom.text) <= maximum:
        return [atom]
    parts = [part.strip() for part in _SENTENCE_RE.split(atom.text) if part.strip()]
    pieces: list[str] = []
    pending = ""
    for part in parts or [atom.text]:
        candidate = f"{pending} {part}".strip()
        if pending and count_tokens(candidate) > maximum:
            pieces.append(pending)
            pending = part
        else:
            pending = candidate
        while count_tokens(pending) > maximum:
            words = pending.split()
            cut = max(1, int(len(words) * maximum / count_tokens(pending)))
            pieces.append(" ".join(words[:cut]))
            pending = " ".join(words[cut:])
    if pending:
        pieces.append(pending)
    return [
        ChunkAtom(
            piece, atom.fragment_id, atom.page, atom.quality, atom.locator,
            atom.heading, atom.section,
        )
        for piece in pieces
    ]


def chunk_atoms(
    atoms: list[ChunkAtom], *, target_tokens: int, max_tokens: int, overlap_tokens: int
) -> list[list[ChunkAtom]]:
    """Разрезать последовательность атомов на близкие по размеру части.

    Число частей берётся из общего объёма, поэтому хвост не вырождается в
    огрызок из пары слов. Перекрытие — только из целых атомов, которые в него
    помещаются: иначе один длинный абзац дублировался бы в соседнюю часть.
    """
    expanded = [
        piece for atom in atoms for piece in _split_large_atom(atom, max(1, max_tokens // 2))
    ]
    total = _tokens(expanded)
    if total <= max_tokens:
        return [expanded] if expanded else []
    goal = total / math.ceil(total / target_tokens)
    parts: list[list[ChunkAtom]] = []
    current: list[ChunkAtom] = []
    current_tokens = 0
    fresh_tokens = 0
    for atom in expanded:
        size = count_tokens(atom.text)
        # Цель считается по новому тексту части: перекрытие не должно рождать
        # лишнюю короткую часть в конце.
        overshoot = fresh_tokens + size - goal
        too_long = current_tokens + size > max_tokens
        if fresh_tokens and (too_long or (overshoot > 0 and overshoot > goal - fresh_tokens)):
            parts.append(current)
            overlap: list[ChunkAtom] = []
            overlap_size = 0
            for previous in reversed(current):
                previous_size = count_tokens(previous.text)
                if overlap_size + previous_size > overlap_tokens:
                    break
                overlap.insert(0, previous)
                overlap_size += previous_size
            current, current_tokens, fresh_tokens = overlap, overlap_size, 0
        current.append(atom)
        current_tokens += size
        fresh_tokens += size
    if current and fresh_tokens:
        parts.append(current)
    return parts


def pack_sections(
    sections: list[Section], *, target_tokens: int, max_tokens: int, overlap_tokens: int
) -> list[list[ChunkAtom]]:
    """Собрать куски из последовательных секций одного материала.

    Секция меньше половины `target` не остаётся одна: она дописывается к
    следующей. Заголовочная секция открывает новый кусок, если в текущем уже
    есть содержательный текст, — так заголовок раздела оказывается в начале
    своего текста, а не в хвосте чужого. Смена `group` (файл Typst) — жёсткая
    граница.
    """
    minimum = target_tokens // 2
    chunks: list[list[ChunkAtom]] = []
    pending: list[ChunkAtom] = []
    pending_tokens = 0
    group: str | None = None

    def flush() -> None:
        nonlocal pending, pending_tokens
        if pending:
            chunks.append(pending)
        pending, pending_tokens = [], 0

    for section in sections:
        size = _tokens(section.atoms)
        if not size:
            continue
        if pending and section.group != group:
            flush()
        group = section.group
        body = sum(count_tokens(atom.text) for atom in pending if not atom.heading)
        if pending and (
            (section.heading_only and body >= minimum // 2)
            or (pending_tokens >= minimum and pending_tokens + size > target_tokens)
        ):
            flush()
        combined = [*pending, *section.atoms]
        combined_tokens = pending_tokens + size
        if combined_tokens <= max_tokens:
            pending, pending_tokens = combined, combined_tokens
            continue
        parts = chunk_atoms(
            combined,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
        chunks.extend(parts[:-1])
        # Последняя часть остаётся открытой: следующая мелкая секция допишется к ней.
        pending = parts[-1] if parts else []
        pending_tokens = _tokens(pending)
    flush()
    if (
        len(chunks) > 1
        and _tokens(chunks[-1]) < minimum
        and _tokens(chunks[-2]) + _tokens(chunks[-1]) <= max_tokens
        and chunks[-1][0].locator.get("typst_path") == chunks[-2][0].locator.get("typst_path")
    ):
        tail = chunks.pop()
        chunks[-1] = [*chunks[-1], *[atom for atom in tail if atom not in chunks[-1]]]
    return chunks


def _worst_quality(atoms: list[ChunkAtom]) -> PageQuality | None:
    order = {PageQuality.NATIVE: 0, PageQuality.OCR: 1, PageQuality.OCR_LOW: 2}
    qualities = [atom.quality for atom in atoms if atom.quality is not None]
    return max(qualities, key=order.__getitem__) if qualities else None


def _join_atoms(atoms: list[ChunkAtom]) -> str:
    """Части одного абзаца склеиваются пробелом, разные абзацы — пустой строкой."""
    text = ""
    previous: ChunkAtom | None = None
    for atom in atoms:
        piece = atom.text.strip()
        if not piece:
            continue
        same_fragment = (
            previous is not None
            and atom.fragment_id is not None
            and atom.fragment_id == previous.fragment_id
        )
        text = f"{text} {piece}" if same_fragment else f"{text}\n\n{piece}" if text else piece
        previous = atom
    return text


def _short(title: str | None) -> str | None:
    if not title:
        return None
    title = " ".join(title.split())
    return title if len(title) <= _TITLE_PART_CHARS else f"{title[:_TITLE_PART_CHARS - 1]}…"


def _rank(title: str | None) -> tuple[int, tuple[int, ...]] | None:
    """Ранг заголовка по его виду: часть < глава < «1.» < «1.1.»; None — вид молчит."""
    if not title:
        return None
    if _PART_MARK.match(title):
        return 0, ()
    if _CHAPTER_MARK.match(title):
        return 1, ()
    if match := _NUMBERED.match(title):
        number = tuple(int(part) for part in match.group(1).split("."))
        return 1 + len(number), number
    return None


class _Outline:
    """Родительские разделы секций одного материала.

    Уровни заголовков у разбора PDF ненадёжны: в одной книге глава и её
    подраздел оба первого уровня, в другой все заголовки одного уровня. Поэтому
    сначала смотрим на вид заголовка — «Часть», «Глава/Лекция/Вопрос/§»,
    нумерацию «2.2.6» — и только у ненумерованных сравниваем уровни. Раньше
    родителем была последняя заголовочная секция, и «Простейшая сеть из двух
    компьютеров» из главы 2 стояла над всей книгой до следующей такой секции.
    """

    def __init__(self, sections: list[Section]) -> None:
        self.sections = sections
        self._ranks = [_rank(section.title) for section in sections]
        self._parents: dict[int, int | None] = {}

    def parent(self, index: int) -> int | None:
        if index not in self._parents:
            self._parents[index] = self._find_parent(index)
        return self._parents[index]

    def _find_parent(self, index: int) -> int | None:
        target, rank = self.sections[index], self._ranks[index]
        for position in range(index - 1, -1, -1):
            candidate, candidate_rank = self.sections[position], self._ranks[position]
            if candidate.group != target.group:
                return None
            if rank is not None:
                # «2.2.6» входит в «2.2» или «2», но не в «1.» и не в соседний «2.2.5».
                if candidate_rank is None or candidate_rank[0] >= rank[0]:
                    continue
                prefix = candidate_rank[1]
                if prefix and rank[1] and rank[1][: len(prefix)] != prefix:
                    continue
                return position
            if candidate_rank is not None:
                return position
            if candidate.heading_only and (
                candidate.level is None
                or target.level is None
                or candidate.level < target.level
            ):
                return position
        return None


def _chunk_title(atoms: list[ChunkAtom], outline: _Outline) -> tuple[int, str | None]:
    """Главная секция куска и путь «родительский раздел › раздел»."""
    weights: dict[int, int] = defaultdict(int)
    for atom in atoms:
        weights[atom.section] += 0 if atom.heading else count_tokens(atom.text)
    main = max(weights, key=lambda index: (weights[index], -index))
    title = _short(outline.sections[main].title)
    parent_index = outline.parent(main)
    parent = _short(outline.sections[parent_index].title) if parent_index is not None else None
    if parent and title and parent != title:
        return main, f"{parent} › {title}"
    return main, title or parent


def _material_label(material: Material) -> str:
    name = material_display_name(material)
    suffix = PurePath(name).suffix
    return name[: -len(suffix)] if suffix and len(suffix) <= 5 else name


def _draft(
    material: Material,
    kind: RetrievalChunkKind,
    atoms: list[ChunkAtom],
    outline: _Outline,
) -> ChunkDraft:
    sections = outline.sections
    text = _join_atoms(atoms)
    main, title = _chunk_title(atoms, outline)
    pages = [atom.page for atom in atoms if atom.page is not None]
    fragment_ids = list(dict.fromkeys(atom.fragment_id for atom in atoms if atom.fragment_id))
    block_ids = list(
        dict.fromkeys(
            sections[atom.section].block_id
            for atom in atoms
            if sections[atom.section].block_id is not None
        )
    )
    locator: dict[str, object] = dict(next((atom.locator for atom in atoms if atom.locator), {}))
    if "line_to" in locator:
        locator["line_to"] = max(int(atom.locator.get("line_to", 0)) for atom in atoms)
    if len(block_ids) > 1:
        # Кусок из нескольких блоков должен находиться фильтром по любому из них.
        locator["block_ids"] = [str(block_id) for block_id in block_ids]
    context = _material_label(material) + (f" — {title}" if title else "")
    return ChunkDraft(
        material_id=material.id,
        revision=material.active_parse_revision,
        block_id=sections[main].block_id,
        kind=kind,
        title=title or (str(locator["typst_path"]) if "typst_path" in locator else None),
        text=text,
        token_count=count_tokens(text),
        page_from=min(pages) if pages else None,
        page_to=max(pages) if pages else None,
        quality=_worst_quality(atoms),
        fragment_ids=fragment_ids,
        locator=locator,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        embedding_text=f"{context}\n\n{text}",
    )


class _FragmentRow(NamedTuple):
    block_id: UUID
    block_title: str | None
    block_order: int
    fragment_id: UUID
    fragment_order: int
    text: str
    element_kind: str
    structure_level: int | None
    quality: PageQuality
    page_number: int


def _running_keys(rows: list[_FragmentRow]) -> set[str]:
    """Колонтитулы: короткая строка без цифр, повторённая на многих страницах."""
    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        if row.element_kind == "heading" or len(row.text) > _RUNNING_MAX_CHARS:
            continue
        key = _RUNNING_KEY.sub(" ", row.text.lower()).strip()
        if key:
            pages_by_key[key].add(row.page_number)
    return {key for key, pages in pages_by_key.items() if len(pages) >= _RUNNING_MIN_PAGES}


def _fragment_rows(session: Session, material: Material) -> list[_FragmentRow]:
    """Фрагменты содержательных блоков в порядке чтения — только нужные колонки.

    Строка страницы хранит полный текст и markdown страницы. Выборка целых
    `MaterialPage` на каждый фрагмент перечитывала их через bind-mount: у
    расшифровки видео с одной «страницей» это 108 с на 1370 фрагментов.
    """
    page_numbers = dict(
        session.execute(
            select(MaterialPage.id, MaterialPage.page_number).where(
                MaterialPage.material_id == material.id,
                MaterialPage.revision == material.active_parse_revision,
            )
        ).all()
    )
    rows = [
        _FragmentRow(*row[:-1], page_numbers[row[-1]])
        for row in session.execute(
            select(
                MaterialBlock.id,
                MaterialBlock.title,
                MaterialBlock.sort_order,
                MaterialFragment.id,
                MaterialFragment.sort_order,
                MaterialFragment.text,
                MaterialFragment.element_kind,
                MaterialFragment.structure_level,
                MaterialFragment.quality,
                MaterialFragment.page_id,
            )
            .join(MaterialFragment, MaterialFragment.block_id == MaterialBlock.id)
            .where(
                MaterialBlock.material_id == material.id,
                MaterialBlock.revision == material.active_parse_revision,
                MaterialBlock.block_class == BlockClass.CONTENT,
            )
        ).tuples()
        if row[-1] in page_numbers
    ]
    rows.sort(key=lambda row: (row.block_order, row.page_number, row.fragment_order))
    return rows


def material_sections(session: Session, material: Material) -> list[Section]:
    """Содержательные блоки активной ревизии в порядке чтения, без шума страниц."""
    rows = _fragment_rows(session, material)
    running = _running_keys(rows)
    grouped: dict[UUID, list[_FragmentRow]] = {}
    for row in rows:
        text = row.text.strip()
        if not text or _VISUAL_ONLY.match(text) or _PAGE_NUMBER.match(text) or _is_toc_line(text):
            continue
        if (
            row.element_kind != "heading"
            and len(text) <= _RUNNING_MAX_CHARS
            and _RUNNING_KEY.sub(" ", text.lower()).strip() in running
        ):
            continue
        if _SERVICE_TITLE.match(" ".join((row.block_title or "").split())):
            continue
        grouped.setdefault(row.block_id, []).append(row)
    sections: list[Section] = []
    for block_id, fragments in grouped.items():
        index = len(sections)
        title = fragments[0].block_title
        title_key = " ".join((title or "").split()).lower()
        atoms = [
            ChunkAtom(
                row.text,
                row.fragment_id,
                row.page_number,
                row.quality,
                heading=row.element_kind == "heading"
                or " ".join(row.text.split()).lower() == title_key,
                section=index,
            )
            for row in fragments
        ]
        sections.append(
            Section(
                block_id=block_id,
                title=title,
                atoms=atoms,
                heading_only=all(atom.heading for atom in atoms),
                level=next(
                    (row.structure_level for row in fragments if row.element_kind == "heading"),
                    None,
                ),
            )
        )
    return sections


def _is_toc_line(text: str) -> bool:
    """Строка оглавления «Глава 2 . . . . 41»: по ней не ищут, она ведёт к тексту."""
    leaders = _TOC_LEADER.findall(text)
    return bool(leaders) and (len(leaders) >= 2 or len(text) <= 200)


def material_chunks(
    session: Session,
    material: Material,
    *,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
    block_ids: set[UUID] | None = None,
) -> list[ChunkDraft]:
    """Построить retrieval-куски активной ревизии материала.

    `block_ids` оставляет только эти блоки до упаковки: иначе короткий блок
    темы склеился бы с соседними, и в кусок попал бы текст вне области.
    Оглавление строится по всем секциям, чтобы заголовки остались прежними.
    """
    if material.active_parse_revision <= 0:
        return []
    if material.source_kind == MaterialSourceKind.TYPST:
        kind = RetrievalChunkKind.TYPST_SOURCE
        sections = _typst_sections(session, material)
    else:
        kind = RetrievalChunkKind.TEXT
        sections = material_sections(session, material)
    outline = _Outline(sections)
    packed = (
        sections
        if block_ids is None
        else [section for section in sections if section.block_id in block_ids]
    )
    return [
        _draft(material, kind, atoms, outline)
        for atoms in pack_sections(
            packed,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
    ]


def _typst_sections(session: Session, material: Material) -> list[Section]:
    rows = list(
        session.scalars(
            select(TypstSourceChunk)
            .where(
                TypstSourceChunk.material_id == material.id,
                TypstSourceChunk.revision == material.active_parse_revision,
            )
            .order_by(TypstSourceChunk.sort_order)
        )
    )
    sections: list[Section] = []
    for source in rows:
        lines = source.source_text.splitlines()
        headings = [match for line in lines if (match := _TYPST_HEADING.match(line))]
        prose = _typst_prose(lines)
        code_only = _letters(prose) < _letters(lines) / 4
        if code_only and not headings:
            # Преамбула: `#set`, `#let` и оформление блоков. Как знание она
            # только мешает — выигрывала поиск по словам из названий функций.
            continue
        index = len(sections)
        titles = [_TYPST_COMMENT.sub("", match.group(2)) for match in headings]
        atom = ChunkAtom(
            "\n".join(match.group(0) for match in headings) if code_only else "\n".join(prose),
            page=source.page_from,
            locator={
                "typst_path": source.path,
                "line_from": source.line_from,
                "line_to": source.line_to,
            },
            heading=code_only or all(_TYPST_NOISE.match(line) for line in prose),
            section=index,
        )
        sections.append(
            Section(
                block_id=None,
                title=next((title for title in titles if title), None),
                atoms=[atom],
                heading_only=atom.heading,
                group=source.path,
                level=len(headings[0].group(1)) if headings else None,
            )
        )
    return sections


def _letters(lines: list[str]) -> int:
    return sum(len(_LETTER.findall(line)) for line in lines)


def _typst_prose(lines: list[str]) -> list[str]:
    """Строки Typst без кода: определений, оформления и описаний графов.

    Описание графа для diagraph — строка DOT `"strict digraph { … }"` из
    десятков строк `x3 -> x4;`. В куске оно вытесняло определения и теоремы,
    рядом с которыми стоит, и делало кусок похожим на любой другой граф.
    Номера строк источника остаются в локаторе, поэтому переход к исходнику
    не зависит от вырезанного.
    """
    kept: list[str] = []
    in_graph = False
    for line in lines:
        if in_graph:
            in_graph = '}"' not in line
            continue
        if _TYPST_GRAPH.search(line):
            in_graph = '}"' not in line
            continue
        if _TYPST_CODE.match(line) and not _TYPST_HEADING.match(line):
            continue
        kept.append(line)
    return kept
