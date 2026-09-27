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


def _text_coverage(page: fitz.Page) -> float:
    """Доля листа под строками текстового слоя."""
    page_area = _area(page.rect) or 1.0
    covered = 0.0
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except (RuntimeError, ValueError):
        return 0.0
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            if any(str(span.get("text", "")).strip() for span in line.get("spans", [])):
                covered += _area(fitz.Rect(line["bbox"]) & page.rect)
    return min(1.0, covered / page_area)


def diagnose(page: fitz.Page) -> TextLayerDiagnosis:
    """Разобрать слой страницы и выбрать маршрут. Без рендеринга, за миллисекунды."""
    text = page.get_text("text")
    chars, good_ratio, mojibake = _quality(text)
    raster_share, largest_raster = _raster_share(page)
    if chars < MIN_TEXT_CHARS:
        if raster_share > 0 or _drawings(page) > MAX_BLANK_DRAWINGS:
            return TextLayerDiagnosis("scan", chars, good_ratio, raster_share, 0.0)
        return TextLayerDiagnosis("blank", chars, good_ratio, raster_share, 0.0)
    coverage = _text_coverage(page)
    reasons: list[str] = []
    if good_ratio < MIN_GOOD_RATIO:
        reasons.append("text_layer_garbled")
    if mojibake > MAX_MOJIBAKE_RATIO:
        reasons.append("text_layer_mojibake")
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
