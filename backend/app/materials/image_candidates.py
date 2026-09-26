"""Отбор изображений до платных вызовов: содержательное, служебное или сомнительное.

Решение складывается из нескольких сигналов вместе, ни один не решает сам:

- **размер** — порог 2% площади страницы и 64 пикселя по стороне лишь поднимает
  вопрос; маленькая уникальная формула или легенда в теле страницы остаётся
  кандидатом, отбрасываются только крошки меньше `TINY_SIDE_PX`;
- **повторяемость** — точный хеш выреза (или общий xref PDF) на нескольких
  страницах, либо серия колонтитула из `header_footer.detect`;
- **положение** — верхняя или нижняя полоса листа;
- **подпись** — «Рис. 3», «Таблица 2» рядом делает изображение содержательным.

Маленький повтор в полосе колонтитула без подписи автоматически становится
служебным с объяснением. Крупный или неоднозначный повтор, неверная рамка и
отсутствующий вырез уходят в очередь проверки — не в описание. Решение
«служебное» ничего не удаляет: вырез остаётся, удаляет колонтитулы только
отдельное действие «Найти колонтитулы» с проверкой ревизии.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from app.materials.image_meta import element_meta
from app.materials.parsers.base import ImageMeta, ParsedElement

SMALL_AREA = 0.02
SMALL_SIDE_PX = 64
TINY_SIDE_PX = 16
# Полоса колонтитула: центр изображения выше или ниже этой доли листа.
MARGIN_ZONE = 0.12
# Сколько страниц с тем же вырезом делают его «повтором».
MIN_REPEATS = 2
# Сигнал разбора PDF: тот же xref растра стоит на нескольких страницах. Ставится
# до ревизии, когда посчитать повторы по всем страницам ещё нельзя.
XREF_REPEATED = "xref_repeated"

# Причины, по которым кандидат не уходит на описание сам: человек смотрит и
# решает в инвентаре «Описать изображения».
DOUBTFUL_REASONS = frozenset(
    {
        "asset_missing",
        "bbox_unreliable",
        "repeated_body",
        "repeated_margin_large",
        "unsupported_format",
        "missed_by_model",
        "crop_suspect",
    }
)
# Решения человека и проверенные исходы правило не переписывает.
LOCKED_REVIEWS = frozenset({"manual", "verified"})
# Причины, которые правило выводит само и пересчитывает при каждом вызове.
# Остальные (проверка ответа модели, подпись прошлой версии) — чужие, их
# классификация сохраняет как есть.
OWN_REASONS = frozenset(
    {"tiny", "repeated_margin", "repeated_margin_large", "repeated_body", "asset_missing",
     "bbox_unreliable"}
)

_ASSET_DIGEST_RE = re.compile(r"-([0-9a-f]{16})\.[A-Za-z0-9]+$")


def asset_digest(asset_path: str | None) -> str | None:
    """Отпечаток выреза из имени файла: `store_material_asset` кладёт туда sha256[:16]."""
    if not asset_path:
        return None
    match = _ASSET_DIGEST_RE.search(Path(asset_path).name)
    return match.group(1) if match else None


def element_signals(
    element: ParsedElement, *, conditional_geometry: bool = False
) -> tuple[str, ...]:
    """Наблюдения по одному изображению: размер, положение, подпись.

    :param conditional_geometry: координаты условные (DOCX, простой текст) —
        площадь и полоса колонтитула по ним не считаются.
    """
    meta = element_meta(element) or ImageMeta()
    signals: list[str] = []
    x0, y0, x1, y1 = element.bbox
    if not conditional_geometry and element.bbox_reliable:
        if (x1 - x0) * (y1 - y0) < SMALL_AREA:
            signals.append("small_area")
        center = (y0 + y1) / 2
        if center <= MARGIN_ZONE or center >= 1 - MARGIN_ZONE:
            signals.append("margin")
    if meta.pixel_size is not None:
        side = min(meta.pixel_size)
        if side < TINY_SIDE_PX:
            signals.append("tiny")
        elif side < SMALL_SIDE_PX:
            signals.append("small_pixels")
    if meta.caption:
        signals.append("caption")
    return tuple(signals)


def classify(
    element: ParsedElement,
    *,
    repeats: int = 1,
    header_footer: bool = False,
    conditional_geometry: bool = False,
) -> ImageMeta:
    """Роль изображения и причины по сигналам; ручное решение не переписывается."""
    meta = element_meta(element) or ImageMeta()
    if meta.review in LOCKED_REVIEWS:
        return meta
    signals = set(element_signals(element, conditional_geometry=conditional_geometry))
    if XREF_REPEATED in meta.signals:
        signals.add(XREF_REPEATED)
    repeated = header_footer or repeats >= MIN_REPEATS or XREF_REPEATED in signals
    if repeated:
        signals.add("repeated")
    if header_footer:
        signals.add("header_footer")
    small = bool(signals & {"small_area", "small_pixels", "tiny"})
    reasons = [reason for reason in meta.reasons if reason not in OWN_REASONS]
    role = "content"
    review = meta.review
    # Модель сочла изображение украшением или служебным — это уже вопрос к
    # человеку, и правило по размеру и повторам его не отменяет.
    model_role = meta.role in {"decorative", "service"} and any(
        reason.startswith("model_role_") for reason in meta.reasons
    )
    if not element.asset_path:
        reasons.append("asset_missing")
    if not element.bbox_reliable and not conditional_geometry:
        reasons.append("bbox_unreliable")
    # Подпись рядом делает изображение содержательным при любом размере и повторе.
    if "caption" not in signals:
        if "tiny" in signals:
            role, reasons = "decorative", [*reasons, "tiny"]
        elif repeated and ("margin" in signals or header_footer):
            if small:
                role, reasons = "service", [*reasons, "repeated_margin"]
            else:
                role, reasons = "unknown", [*reasons, "repeated_margin_large"]
        elif repeated:
            role, reasons = "unknown", [*reasons, "repeated_body"]
    if role == "content" and any(reason in DOUBTFUL_REASONS for reason in reasons):
        role = "unknown"
    if model_role:
        role = meta.role
    if any(reason in DOUBTFUL_REASONS for reason in reasons) and review == "unreviewed":
        review = "needs_review"
    return replace(
        meta,
        role=role,  # type: ignore[arg-type]
        review=review,
        reasons=tuple(dict.fromkeys(reasons)),
        signals=tuple(sorted(signals)),
    )


def auto_send(meta: ImageMeta) -> bool:
    """Уходит ли изображение на описание без решения человека."""
    return (
        meta.role == "content"
        and meta.review not in LOCKED_REVIEWS
        and not any(reason in DOUBTFUL_REASONS for reason in meta.reasons)
    )


def repeat_key(element: ParsedElement) -> str | None:
    """Ключ повтора: точный хеш выреза, иначе отпечаток из имени файла."""
    meta = element_meta(element)
    if meta is not None and meta.crop_hash:
        return meta.crop_hash[:16]
    return asset_digest(element.asset_path)


def repeat_counts(pages: Iterable[tuple[int, Iterable[ParsedElement]]]) -> Counter[str]:
    """На скольких разных страницах встречается каждый вырез."""
    seen: dict[str, set[int]] = {}
    for page_number, elements in pages:
        for element in elements:
            if element.kind != "image":
                continue
            key = repeat_key(element)
            if key:
                seen.setdefault(key, set()).add(page_number)
    return Counter({key: len(numbers) for key, numbers in seen.items()})


def file_hash(path: Path) -> str | None:
    """sha256 файла выреза, когда в состоянии его ещё нет."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
