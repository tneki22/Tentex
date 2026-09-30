"""Годится ли текстовый слой PDF-страницы и какой ветке её отдавать.

Прежний выбор по одному признаку «есть хоть какой-то текст» не замечал
частичный слой (скан с невидимым OCR-текстом на трёх строках из сорока),
испорченную кодировку («Ãëàâà» вместо «Глава», символы из области частного
использования шрифта) и страницу, где текст есть, а содержание — картинкой.
Здесь считается несколько дешёвых признаков по самому слою и растрам страницы,
без рендеринга, и из них выводится маршрут с объяснением.

Маршрут — не приговор, а вход для стратегии запуска: «Быстро» отдаёт
подозрительную страницу локальному OCR, «Адаптивно» — модели целиком,
«Экономно» оставляет слой и помечает страницу для проверки.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

import pymupdf as fitz

from app.materials.parsers.formula_zones import HIDDEN_MIN_WIDTH, MATH_FONT_RE, readable

TextRoute = Literal["text", "partial", "broken", "scan", "blank"]

# Меньше — слоя нет: пара символов номера страницы или штампа сканера.
MIN_TEXT_CHARS = 20
# Доля «правдоподобных» символов, ниже которой слой считается испорченным.
MIN_GOOD_RATIO = 0.85
# Доля латиницы с диакритикой среди букв: так выглядит cp1251, прочитанный как
# latin-1. В русском учебнике её почти не бывает.
MAX_MOJIBAKE_RATIO = 0.2
# Растр на всю страницу — признак скана, даже если поверх лежит текст.
FULL_PAGE_RASTER = 0.7
# У скана с полноценным невидимым слоем строки покрывают заметную часть листа;
# меньше — распознаны отдельные строки, остальное осталось картинкой.
MIN_TEXT_COVERAGE_ON_SCAN = 0.12
MIN_CHARS_ON_SCAN = 300
# Пустая страница без растров и векторной графики — нечего распознавать.
MAX_BLANK_DRAWINGS = 20
# Доля ширины строк, занятая глифами без текста в обычном (не математическом)
# шрифте. Так выглядит основной шрифт без таблицы Unicode: страница целиком из
# «пробелов». Невидимые глифы Cambria Math — формулы, их режут вырезами.
MAX_HIDDEN_TEXT_SHARE = 0.5

_PLAUSIBLE_PUNCT = set(".,;:!?()[]{}«»\"'`-–—/\\%+=<>*&#№§°±×÷…·•^_|~@$")


@dataclass(frozen=True, slots=True)
class TextLayerDiagnosis:
    """Признаки текстового слоя страницы и вывод о маршруте."""

    route: TextRoute
    chars: int
    good_ratio: float
    raster_share: float
    text_coverage: float
    reasons: tuple[str, ...] = ()

    @property
    def suspicious(self) -> bool:
        return self.route in {"partial", "broken"}

    def diagnostics(self) -> tuple[str, ...]:
        """Отметки для `MaterialPage.diagnostics`: маршрут, числа и причины."""
        return (
            f"route:{self.route}",
            f"text_chars:{self.chars}",
            f"text_quality:{self.good_ratio:.2f}",
            f"raster_share:{self.raster_share:.2f}",
            *self.reasons,
        )


def _plausible(char: str) -> bool:
    if char.isspace() or char.isalnum() or char in _PLAUSIBLE_PUNCT:
        return char != "�"
    category = unicodedata.category(char)
    # Математические и прочие символы (Sm, So) законны в учебнике; управляющие,
    # частного использования и неназначенные — признак сломанного шрифта.
    return category in {"Sm", "So", "Sc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po", "Mn"}


def _quality(text: str) -> tuple[int, float, float]:
    """Число символов без пробелов, доля правдоподобных и доля mojibake."""
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0, 1.0, 0.0
    good = sum(_plausible(char) for char in visible)
    letters = [char for char in visible if char.isalpha()]
    mojibake = sum("À" <= char <= "ÿ" for char in letters)
    return len(visible), good / len(visible), (mojibake / len(letters) if letters else 0.0)


def _area(rect: fitz.Rect) -> float:
    return max(0.0, rect.width) * max(0.0, rect.height)


def _raster_share(page: fitz.Page) -> tuple[float, float]:
    """Суммарная (не больше единицы) и наибольшая доля листа под растрами."""
    page_area = _area(page.rect) or 1.0
    total = 0.0
    largest = 0.0
    try:
        infos = page.get_image_info()
    except (RuntimeError, ValueError):
        return 0.0, 0.0
    for info in infos:
        rect = fitz.Rect(info.get("bbox", (0, 0, 0, 0))) & page.rect
        share = _area(rect) / page_area
        total += share
        largest = max(largest, share)
    return min(1.0, total), largest


@dataclass(frozen=True, slots=True)
class _LayerStats:
    """Что видно по спанам слоя: текст, покрытие листа и ширина невидимых глифов."""

    text: str
    coverage: float
    visible_width: float
    hidden_math_width: float
    hidden_text_width: float

    @property
    def hidden_text_share(self) -> float:
        total = self.visible_width + self.hidden_math_width + self.hidden_text_width
        return self.hidden_text_width / total if total > 0 else 0.0


def _layer_stats(page: fitz.Page) -> _LayerStats:
    """Один проход по спанам: текст для оценки качества, покрытие и пустоты.

    Пустота — спан из пробелов шире межсловного: за ним либо табуляция, либо
    глиф без Unicode. Какой из двух, решают чернила (`formula_zones`); здесь
    нужна только ширина, чтобы отличить формулы от основного шрифта без таблицы.
    """
    page_area = _area(page.rect) or 1.0
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except (RuntimeError, ValueError):
        return _LayerStats("", 0.0, 0.0, 0.0, 0.0)
    parts: list[str] = []
    covered = visible = hidden_math = hidden_text = 0.0
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            filled = False
            for span in line.get("spans", []):
                font = str(span.get("font", ""))
                text = readable(str(span.get("text", "")), font)
                parts.append(text)
                x0, _, x1, _ = span.get("bbox", (0, 0, 0, 0))
                width = max(0.0, float(x1) - float(x0))
                if text.strip():
                    visible += width
                    filled = True
                elif width >= HIDDEN_MIN_WIDTH * float(span.get("size") or 10.0):
                    if MATH_FONT_RE.search(font):
                        hidden_math += width
                    else:
                        hidden_text += width
            parts.append("\n")
            if filled:
                covered += _area(fitz.Rect(line["bbox"]) & page.rect)
    return _LayerStats(
        "".join(parts), min(1.0, covered / page_area), visible, hidden_math, hidden_text
    )


def diagnose(page: fitz.Page) -> TextLayerDiagnosis:
    """Разобрать слой страницы и выбрать маршрут. Без рендеринга, за миллисекунды."""
    stats = _layer_stats(page)
    chars, good_ratio, mojibake = _quality(stats.text)
    raster_share, largest_raster = _raster_share(page)
    # Страница из одних формул Cambria Math или целиком шрифтом без Unicode:
    # букв в слое нет, но она не пустая. Пара набранных пробелов на пустом
    # листе меньше строки шириной и пустоты не отменяет.
    hidden = stats.hidden_math_width > 0 or stats.hidden_text_width >= page.rect.width
    if chars < MIN_TEXT_CHARS and not hidden:
        if raster_share > 0 or _drawings(page) > MAX_BLANK_DRAWINGS:
            return TextLayerDiagnosis("scan", chars, good_ratio, raster_share, 0.0)
        return TextLayerDiagnosis("blank", chars, good_ratio, raster_share, 0.0)
    coverage = stats.coverage
    reasons: list[str] = []
    if good_ratio < MIN_GOOD_RATIO:
        reasons.append("text_layer_garbled")
    if mojibake > MAX_MOJIBAKE_RATIO:
        reasons.append("text_layer_mojibake")
    if stats.hidden_text_share > MAX_HIDDEN_TEXT_SHARE:
        reasons.append("text_layer_hidden_glyphs")
    if reasons:
        return TextLayerDiagnosis(
            "broken", chars, good_ratio, raster_share, coverage, tuple(reasons)
        )
    if largest_raster >= FULL_PAGE_RASTER and (
        coverage < MIN_TEXT_COVERAGE_ON_SCAN or chars < MIN_CHARS_ON_SCAN
    ):
        return TextLayerDiagnosis(
            "partial",
            chars,
            good_ratio,
            raster_share,
            coverage,
            ("text_layer_partial",),
        )
    return TextLayerDiagnosis("text", chars, good_ratio, raster_share, coverage)


def _drawings(page: fitz.Page) -> int:
    """Число векторных путей: текст, превращённый в кривые, даёт их сотни."""
    try:
        return len(page.get_drawings())
    except (RuntimeError, ValueError):
        return 0
