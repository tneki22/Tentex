"""Формулы, которые текстовый слой PDF не передаёт текстом.

Методичка из Word выглядит в PDF безупречно, а в текстовом слое у неё дыры:

- формулы редактора Word набраны шрифтом Cambria Math, и его глифы
  извлекаются пробелами той же ширины. Абзац читается «Пусть   – произвольные
  формулы», выносная формула — пустая строка, которую разметка выбрасывает;
- формулы старого редактора и MathType собраны из курсивных букв и знаков
  шрифта Symbol. Знаки приходят символами частной области (`\\uf0d9` вместо
  «∧»), а сама формула — линейной строкой без индексов и черт отрицания;
- битый шрифт даёт `U+FFFD` или управляющие символы на месте глифов.

Проверка слоя такие страницы пропускает: пробел — законный символ, а доля
мусора мала. Здесь по самим глифам находятся зоны формул: невидимые глифы
подтверждаются чернилами под ними на растре, видимые — математическим шрифтом
или знаком. Зона — это рамка для выреза, который дальше читает модель или
показывает просмотрщик. Отдельно стоящая формула (строка без прозы, ячейка
таблицы) становится своим элементом, формула внутри строки — вставкой в абзац.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import pymupdf as fitz
from PIL import Image

type Box = tuple[float, float, float, float]

# Кодировка шрифта Symbol (Adobe): глиф по коду 0x20–0xFE. TrueType-версия шрифта
# кладёт те же коды в частную область `U+F020–U+F0FE`, и без таблицы вместо
# «x1 ∧ x2 ≡ F» в тексте стоит «x1x2F».
SYMBOL_ENCODING = {
    0x20: " ", 0x21: "!", 0x22: "∀", 0x23: "#", 0x24: "∃", 0x25: "%", 0x26: "&",
    0x27: "∋", 0x28: "(", 0x29: ")", 0x2A: "∗", 0x2B: "+", 0x2C: ",", 0x2D: "−",
    0x2E: ".", 0x2F: "/", 0x3A: ":", 0x3B: ";", 0x3C: "<", 0x3D: "=", 0x3E: ">",
    0x3F: "?", 0x40: "≅", 0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε",
    0x46: "Φ", 0x47: "Γ", 0x48: "Η", 0x49: "Ι", 0x4A: "ϑ", 0x4B: "Κ", 0x4C: "Λ",
    0x4D: "Μ", 0x4E: "Ν", 0x4F: "Ο", 0x50: "Π", 0x51: "Θ", 0x52: "Ρ", 0x53: "Σ",
    0x54: "Τ", 0x55: "Υ", 0x56: "ς", 0x57: "Ω", 0x58: "Ξ", 0x59: "Ψ", 0x5A: "Ζ",
    0x5B: "[", 0x5C: "∴", 0x5D: "]", 0x5E: "⊥", 0x5F: "_", 0x61: "α", 0x62: "β",
    0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ", 0x67: "γ", 0x68: "η", 0x69: "ι",
    0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ", 0x6D: "μ", 0x6E: "ν", 0x6F: "ο", 0x70: "π",
    0x71: "θ", 0x72: "ρ", 0x73: "σ", 0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω",
    0x78: "ξ", 0x79: "ψ", 0x7A: "ζ", 0x7B: "{", 0x7C: "|", 0x7D: "}", 0x7E: "∼",
    0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞", 0xA6: "ƒ", 0xA7: "♣",
    0xA8: "♦", 0xA9: "♥", 0xAA: "♠", 0xAB: "↔", 0xAC: "←", 0xAD: "↑", 0xAE: "→",
    0xAF: "↓", 0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝",
    0xB6: "∂", 0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xBC: "…",
    0xBD: "⏐", 0xBE: "⎯", 0xBF: "↵", 0xC0: "ℵ", 0xC1: "ℑ", 0xC2: "ℜ", 0xC3: "℘",
    0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪", 0xC9: "⊃", 0xCA: "⊇",
    0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆", 0xCE: "∈", 0xCF: "∉", 0xD0: "∠", 0xD1: "∇",
    0xD2: "®", 0xD3: "©", 0xD4: "™", 0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xD8: "¬",
    0xD9: "∧", 0xDA: "∨", 0xDB: "⇔", 0xDC: "⇐", 0xDD: "⇑", 0xDE: "⇒", 0xDF: "⇓",
    0xE0: "◊", 0xE1: "⟨", 0xE2: "®", 0xE3: "©", 0xE4: "™", 0xE5: "∑", 0xE6: "⎛",
    0xE7: "⎜", 0xE8: "⎝", 0xE9: "⎡", 0xEA: "⎢", 0xEB: "⎣", 0xEC: "⎧", 0xED: "⎨",
    0xEE: "⎩", 0xEF: "⎪", 0xF1: "⟩", 0xF2: "∫", 0xF3: "⌠", 0xF4: "⎮", 0xF5: "⌡",
    0xF6: "⎞", 0xF7: "⎟", 0xF8: "⎠", 0xF9: "⎤", 0xFA: "⎥", 0xFB: "⎦", 0xFC: "⎫",
    0xFD: "⎬", 0xFE: "⎭",
} | {code: chr(code) for code in range(0x30, 0x3A)}
SYMBOL_PRIVATE_BASE = 0xF000
SYMBOL_FONT_RE = re.compile(r"(?:^|\+)symbol(?:mt)?(?:$|[,\-])", re.IGNORECASE)
# Шрифты формул: Cambria Math и STIX у Word, Computer Modern и AMS у LaTeX,
# MT Extra и Euclid у MathType и старого редактора формул.
MATH_FONT_RE = re.compile(
    r"math|symbol|mt ?extra|euclid|cmmi|cmsy|cmex|msam|msbm|stix|rtxmi|txsy|esint",
    re.IGNORECASE,
)
# Знаки, которых в прозе не бывает. ASCII `=`, `+`, `-` сюда не входят: ими
# полон и код, и обычный текст с диапазонами.
MATH_CHARS = frozenset(
    "∀∃∄∈∉∋∧∨¬⊕⊗→←↔⇒⇐⇔↦≡≢≈≅∼≤≥≠≪≫⊂⊃⊆⊇⊄∪∩∖∅∑∏∐∫∬∭∮∂∇√∛∞±∓×÷⋅∘∗⊥∥∠′″"
)
# Имена функций в формуле пишутся прямо и словом; прозой они не считаются.
MATH_WORDS = frozenset({
    "sin", "cos", "tan", "tg", "cot", "ctg", "sec", "csc", "arcsin", "arccos", "arctan",
    "arctg", "arcctg", "sinh", "cosh", "tanh", "coth", "sh", "ch", "th", "cth", "log", "lg",
    "ln", "exp", "lim", "sup", "inf", "max", "min", "det", "deg", "dim", "gcd", "lcm", "mod",
    "arg", "ker", "grad", "div", "rot", "const",
})
# Маркеры списков из Symbol и Wingdings: математический шрифт, но не формула.
BULLET_CHARS = frozenset("•◦▪▫‣⁃●○■□►▸➢✓✔·")
CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
# Нумерация пункта перед формулой («1)», «а.») — это текст абзаца, не формула.
MARKER_RE = re.compile(r"^\s*(?:\d{1,3}|[a-zа-яё])[.)]", re.IGNORECASE)

# Разрешение растра для проверки чернил: хватает, чтобы отличить глиф кегля 8
# от пустоты, а страница рисуется за сотые доли секунды.
INK_DPI = 100
# Пиксель темнее — чернила. Сглаженные края глифа светлее, серединка — чёрная.
INK_LEVEL = 170
# Глиф занимает заметную часть высоты строки и ширины прогона. Подчёркнутые
# пробелы бланка («Группа: ____») дают чернила в двух строках пикселей, линия
# таблицы поперёк пустой ячейки — в двух столбцах; ни то, ни другое не формула.
INK_MIN_ROWS = 0.25
INK_MIN_COLUMNS = 0.15
# Пробел между словами уже этого (в долях кегля); прогон шире — глиф без текста
# либо табуляция, что и решают чернила.
HIDDEN_MIN_WIDTH = 0.45
# Разрыв внутри строки, после которого начинается другой кусок: ячейка таблицы,
# номер формулы у поля. Интервалы внутри формулы и между словами уже.
SEGMENT_GAP = 1.0
# Индекс или числитель, вынесенный в свою строку, всё ещё часть того же куска.
SAME_ROW_OVERLAP = 0.3
# Доля прозы по ширине, ниже которой кусок — отдельно стоящая формула.
PROSE_SHARE = 0.3
# Этажи одной формулы (числитель, знаменатель, строка системы) стоят ближе
# межстрочного интервала: зазор в долях кегля.
FLOOR_GAP = 0.5
# Поля листа, где живут номер страницы и колонтитул: число в них — не числитель
# формулы, даже если стоит вплотную под последней строкой.
MARGIN_BAND = 0.07


@dataclass(frozen=True, slots=True)
class FormulaZone:
    """Место формулы на странице в долях её размера."""

    box: Box
    # На строке нет прозы: выносная формула или ячейка таблицы. Иначе формула
    # стоит внутри фразы и после распознавания встаёт в неё `$...$`.
    standalone: bool
    # Глифы зоны в слое невидимы (пробелы, U+FFFD) — текста у неё нет вовсе.
    hidden: bool


@dataclass(slots=True)
class _Glyph:
    rect: fitz.Rect
    char: str
    font: str
    size: float
    candidate: bool
    math: bool


@dataclass(slots=True)
class _Piece:
    """Кусок строки слоя без больших разрывов: фраза, ячейка, формула."""

    glyphs: list[_Glyph]
    runs: list[list[_Glyph]] = field(default_factory=list)

    @property
    def rect(self) -> fitz.Rect:
        return _union_rect(glyph.rect for glyph in self.glyphs)

    @property
    def size(self) -> float:
        return max((glyph.size for glyph in self.glyphs), default=10.0)


def is_symbol_font(font: str) -> bool:
    return SYMBOL_FONT_RE.search(font or "") is not None


def readable(text: str, font: str | None = None) -> str:
    """Знаки шрифта Symbol из частной области — в Unicode.

    :param font: шрифт спана; `None` — шрифт неизвестен (таблица разметчика,
        слова страницы), и частная область `U+F020–U+F0FE` считается Symbol:
        так её заполняет почти всегда именно он.
    """
    if font is not None and not is_symbol_font(font):
        return text
    if not any(0xF020 <= ord(char) <= 0xF0FE for char in text):
        return text
    return "".join(
        SYMBOL_ENCODING.get(ord(char) - SYMBOL_PRIVATE_BASE, char)
        if 0xF020 <= ord(char) <= 0xF0FE
        else char
        for char in text
    )


def _hidden_char(char: str) -> bool:
    """Символ слоя, за которым не стоит текст: пробел, U+FFFD, частная область."""
    if not char or char.isspace() or char == "�":
        return True
    return unicodedata.category(char) in {"Co", "Cn", "Cc", "Cs"}


def _math_char(char: str, font: str) -> bool:
    if char in BULLET_CHARS:
        return False
    if char in MATH_CHARS or "Ͱ" <= char <= "Ͽ":
        return True
    if "\U0001d400" <= char <= "\U0001d7ff":  # математические буквы Unicode
        return True
    return MATH_FONT_RE.search(font or "") is not None and not char.isspace()


def _union_rect(rects: Iterable[fitz.Rect]) -> fitz.Rect:
    result = fitz.Rect()
    for rect in rects:
        result = fitz.Rect(rect) if result.is_empty else result | rect
    return result


def _page_glyph_lines(page: fitz.Page) -> list[list[_Glyph]]:
    flags = fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES
    lines: list[list[_Glyph]] = []
    for block in page.get_text("rawdict", flags=flags).get("blocks", []):
        for line in block.get("lines", []):
            direction = line.get("dir", (1, 0))
            if abs(direction[1]) > 0.1:
                continue  # повёрнутый текст: подпись оси, вертикальный колонтитул
            glyphs: list[_Glyph] = []
            for span in line.get("spans", []):
                font = str(span.get("font", ""))
                size = float(span.get("size") or 10.0)
                for raw in span.get("chars", []):
                    char = readable(str(raw.get("c", "")), font)
                    rect = fitz.Rect(raw["bbox"])
                    candidate = _hidden_char(char)
                    glyphs.append(
                        _Glyph(rect, char, font, size, candidate,
                               not candidate and _math_char(char, font))
                    )
            if glyphs:
                lines.append(sorted(glyphs, key=lambda glyph: glyph.rect.x0))
    return lines


def _pieces(line: list[_Glyph]) -> list[_Piece]:
    pieces: list[_Piece] = [_Piece([line[0]])]
    for previous, glyph in zip(line, line[1:], strict=False):
        gap = glyph.rect.x0 - previous.rect.x1
        if gap > SEGMENT_GAP * max(glyph.size, previous.size):
            pieces.append(_Piece([glyph]))
        else:
            pieces[-1].glyphs.append(glyph)
    for piece in pieces:
        piece.runs = _candidate_runs(piece.glyphs)
    return pieces


def _candidate_runs(glyphs: list[_Glyph]) -> list[list[_Glyph]]:
    """Прогоны символов без текста, достаточно широкие, чтобы скрывать глиф."""
    runs: list[list[_Glyph]] = []
    current: list[_Glyph] = []
    for glyph in [*glyphs, None]:
        if glyph is not None and glyph.candidate:
            current.append(glyph)
            continue
        if current:
            width = max(item.rect.x1 for item in current) - min(item.rect.x0 for item in current)
            solid = [item for item in current if not item.char.isspace()]
            size = max(item.size for item in current)
            # Одиночный значок частной области в начале строки — маркер списка
            # из Wingdings или Symbol, а не формула.
            bullet = len(solid) == 1 and current[0] is glyphs[0] and width < size
            if (width >= HIDDEN_MIN_WIDTH * size or solid) and not bullet:
                runs.append(current)
            current = []
    return runs


def _same_row(first: fitz.Rect, second: fitz.Rect, size: float) -> bool:
    overlap = min(first.y1, second.y1) - max(first.y0, second.y0)
    height = min(first.height, second.height)
    if height <= 0 or overlap < SAME_ROW_OVERLAP * height:
        return False
    gap = max(first.x0, second.x0) - min(first.x1, second.x1)
    return gap <= SEGMENT_GAP * size


def _segments(lines: list[list[_Glyph]]) -> list[_Piece]:
    """Куски строк, склеенные с индексами и этажами, вынесенными в свои строки."""
    pieces = [piece for line in lines for piece in _pieces(line)]
    parent = list(range(len(pieces)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    rects = [piece.rect for piece in pieces]
    for first in range(len(pieces)):
        for second in range(first + 1, len(pieces)):
            size = max(pieces[first].size, pieces[second].size)
            if _same_row(rects[first], rects[second], size):
                parent[root(second)] = root(first)
    groups: dict[int, _Piece] = {}
    for index, piece in enumerate(pieces):
        group = groups.setdefault(root(index), _Piece([]))
        group.glyphs.extend(piece.glyphs)
        group.runs.extend(piece.runs)
    return list(groups.values())


class _Ink:
    """Растр страницы для проверки чернил; рисуется только по требованию."""

    def __init__(self, page: fitz.Page) -> None:
        self._page = page
        self._image: Image.Image | None = None
        self._scale = INK_DPI / 72.0

    def extent(self, rect: fitz.Rect) -> fitz.Rect | None:
        """Рамка чернил внутри прямоугольника или `None`, если глифа там нет."""
        if self._image is None:
            pixmap = self._page.get_pixmap(
                matrix=fitz.Matrix(self._scale, self._scale), colorspace=fitz.csGRAY, alpha=False
            )
            self._image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
        scale = self._scale
        # Слева и справа — только пиксели целиком внутри прогона: крайний
        # столбец наполовину занят соседней буквой, и её хвост попадал в рамку.
        left, top = max(0, math.ceil(rect.x0 * scale)), max(0, int(rect.y0 * scale))
        right = min(self._image.width, int(rect.x1 * scale))
        bottom = min(self._image.height, int(rect.y1 * scale) + 1)
        if right - left < 1 or bottom - top < 2:
            return None
        mask = self._image.crop((left, top, right, bottom)).point(
            lambda value: 255 if value < INK_LEVEL else 0
        )
        found = mask.getbbox()
        if found is None:
            return None
        width, height = mask.size
        rows = mask.resize((1, height), Image.Resampling.BOX).tobytes()
        columns = mask.resize((width, 1), Image.Resampling.BOX).tobytes()
        if sum(value > 0 for value in rows) < INK_MIN_ROWS * height:
            return None
        if sum(value > 0 for value in columns) < INK_MIN_COLUMNS * width:
            return None
        return fitz.Rect(
            (left + found[0]) / scale,
            (top + found[1]) / scale,
            (left + found[2]) / scale,
            (top + found[3]) / scale,
        )


def _confirmed_runs(segment: _Piece, ink: _Ink) -> list[tuple[fitz.Rect, int]]:
    """Прогоны без текста, под которыми на растре есть глиф: рамка и число символов."""
    confirmed: list[tuple[fitz.Rect, int]] = []
    for run in segment.runs:
        rect = _union_rect(glyph.rect for glyph in run)
        found = ink.extent(rect)
        if found is None:
            continue
        # По горизонтали — по чернилам (пробелы по краям прогона не формула),
        # по вертикали — по строке: черта над буквой выходит за чернила глифа.
        confirmed.append((fitz.Rect(found.x0, rect.y0, found.x1, rect.y1), len(run)))
    return confirmed


def _prose_width(glyphs: Sequence[_Glyph]) -> float:
    """Ширина слов прозы: русское слово от трёх букв, латинское — от четырёх."""
    total = 0.0
    word: list[_Glyph] = []
    for glyph in [*glyphs, None]:
        if glyph is not None and not glyph.candidate and not glyph.math and glyph.char.isalpha():
            word.append(glyph)
            continue
        text = "".join(item.char for item in word)
        cyrillic = CYRILLIC_RE.search(text) is not None
        if (cyrillic and len(text) >= 3) or (
            not cyrillic and len(text) >= 4 and text.casefold() not in MATH_WORDS
        ):
            total += sum(item.rect.width for item in word)
        word = []
    return total


def _visible(segment: _Piece) -> list[_Glyph]:
    glyphs = sorted(
        (glyph for glyph in segment.glyphs if not glyph.candidate),
        key=lambda glyph: glyph.rect.x0,
    )
    text = "".join(glyph.char for glyph in glyphs)
    marker = MARKER_RE.match(text)
    return glyphs[marker.end() :] if marker else glyphs


@dataclass(slots=True)
class _Zone:
    rect: fitz.Rect
    size: float
    standalone: bool
    hidden: bool


def _segment_zones(segment: _Piece, ink: _Ink) -> tuple[list[_Zone], bool]:
    """Зоны куска и признак «кусок без прозы» (для этажей соседних формул)."""
    ordered = sorted(segment.glyphs, key=lambda glyph: glyph.rect.x0)
    runs = _confirmed_runs(segment, ink) if segment.runs else []
    visible = [glyph for glyph in ordered if not glyph.candidate]
    total = sum(glyph.rect.width for glyph in visible) + sum(rect.width for rect, _ in runs)
    standalone = total > 0 and _prose_width(ordered) < PROSE_SHARE * total
    signal = bool(runs) or any(glyph.math for glyph in visible)
    size = segment.size
    if not signal:
        return [], standalone
    if standalone:
        shown = _visible(segment)
        # Один видимый знак без скрытых глифов — маркер или буква в ячейке:
        # вырез ради него дороже, чем он сам.
        if not runs and len(shown) < 2:
            return [], standalone
        rect = _union_rect([rect for rect, _ in runs] + [glyph.rect for glyph in shown])
        if rect.is_empty:
            return [], standalone
        return [_Zone(rect, size, True, not visible)], standalone
    return [_Zone(rect, size, False, True) for rect, _ in runs], standalone


def _gap(first: fitz.Rect, second: fitz.Rect) -> tuple[float, float]:
    """Зазор между рамками по горизонтали и вертикали (0 — перекрываются)."""
    horizontal = max(0.0, max(first.x0, second.x0) - min(first.x1, second.x1))
    vertical = max(0.0, max(first.y0, second.y0) - min(first.y1, second.y1))
    return horizontal, vertical


def _x_overlap(first: fitz.Rect, second: fitz.Rect) -> float:
    width = min(first.width, second.width)
    overlap = min(first.x1, second.x1) - max(first.x0, second.x0)
    return overlap / width if width > 0 else 0.0


def _merge_zones(zones: list[_Zone]) -> list[_Zone]:
    """Склеить зоны одной формулы: этажи системы, налезающие прогоны, дробь.

    Отдельно стоящие зоны склеиваются, стоя рядом или одна над другой.
    Строчные — только налезающие или стоящие этажами дроби внутри фразы;
    соседние по строке через запятую — нет.
    """
    merged = True
    while merged:
        merged = False
        for first_index, first in enumerate(zones):
            for second in zones[first_index + 1 :]:
                if first.standalone != second.standalone:
                    continue
                horizontal, vertical = _gap(first.rect, second.rect)
                size = max(first.size, second.size)
                if vertical > FLOOR_GAP * size:
                    continue
                if first.standalone:
                    beside = horizontal <= SEGMENT_GAP * size
                    if not beside and _x_overlap(first.rect, second.rect) < 0.5:
                        continue
                elif not first.rect.intersects(second.rect) and (
                    _x_overlap(first.rect, second.rect) < 0.5 or vertical == 0
                ):
                    continue
                first.rect |= second.rect
                first.hidden = first.hidden and second.hidden
                zones.remove(second)
                merged = True
                break
            if merged:
                break
    return zones


def _attach_floors(zones: list[_Zone], orphans: list[fitz.Rect]) -> None:
    """Числитель и знаменатель обычным шрифтом — к формуле, по одному сверху и снизу.

    Числитель «1» набран без признаков формулы, и без него вырез обрезан.
    Цепочкой присоединять нельзя: под шапкой таблицы из формул стоят столбцы
    цифр, и зона прорастала бы через всю таблицу в формулы под ней.
    """
    pool = list(orphans)
    for zone in zones:
        if not zone.standalone:
            continue
        taken = {"above": False, "below": False}
        for _ in range(2):  # знаменатель расширяет зону, и тогда достаёт числитель
            for orphan in list(pool):
                side = "above" if orphan.y1 <= zone.rect.y0 + 1 else "below"
                if taken[side] or orphan.y0 < zone.rect.y0 - 1 < zone.rect.y1 < orphan.y1:
                    continue
                horizontal, vertical = _gap(zone.rect, orphan)
                if vertical <= FLOOR_GAP * zone.size and horizontal <= SEGMENT_GAP * zone.size:
                    zone.rect |= orphan
                    pool.remove(orphan)
                    taken[side] = True


def find_zones(page: fitz.Page) -> list[FormulaZone]:
    """Зоны формул страницы, которые слой не передаёт текстом.

    Растр рисуется только тогда, когда на странице есть прогоны без текста:
    обычная страница проверяется по одному слою за миллисекунды.
    """
    lines = _page_glyph_lines(page)
    if not lines:
        return []
    ink = _Ink(page)
    zones: list[_Zone] = []
    orphans: list[fitz.Rect] = []
    for segment in _segments(lines):
        found, standalone = _segment_zones(segment, ink)
        if found:
            zones.extend(found)
        elif standalone:
            visible = [glyph.rect for glyph in segment.glyphs if not glyph.candidate]
            rect = _union_rect(visible)
            band = MARGIN_BAND * page.rect.height
            if visible and band < rect.y0 and rect.y1 < page.rect.height - band:
                orphans.append(rect)
    zones = _merge_zones(zones)
    _attach_floors(zones, orphans)
    width, height = page.rect.width, page.rect.height
    return [
        FormulaZone(
            (
                max(0.0, zone.rect.x0 / width),
                max(0.0, zone.rect.y0 / height),
                min(1.0, zone.rect.x1 / width),
                min(1.0, zone.rect.y1 / height),
            ),
            zone.standalone,
            zone.hidden,
        )
        for zone in sorted(zones, key=lambda item: (item.rect.y0, item.rect.x0))
    ]


def page_words(page: fitz.Page) -> list[tuple[Box, str]]:
    """Слова слоя в долях страницы, со знаками Symbol в Unicode.

    Невидимые глифы формул — пробелы, поэтому они разделяют слова, а не
    приклеиваются к соседним: «Пусть» остаётся якорем для вставки формулы.
    """
    width, height = page.rect.width, page.rect.height
    words: list[tuple[Box, str]] = []
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        text = "".join(char for char in readable(word) if not _hidden_char(char))
        if text:
            words.append(((x0 / width, y0 / height, x1 / width, y1 / height), text))
    return words
