"""Реестр движков распознавания. Новый режим — одна запись здесь, не переделка экрана."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EngineRuntime = Literal["worker", "gpu_service", "cloud"]

DEFAULT_QUALITY_THRESHOLD = 0.75
DEFAULT_RASTER_SCALE = 2.0
RASTER_SCALE_OPTIONS = (1.5, 2.0, 3.0)
DEFAULT_FAST_LANGUAGE = "ru"
DEFAULT_FAST_MODEL_ID = "PP-OCRv5"

# Как режим «Облако» делит работу между текстовым слоем файла и внешней моделью.
CloudStrategy = Literal["auto", "page"]
DEFAULT_CLOUD_STRATEGY: CloudStrategy = "auto"
CLOUD_STRATEGY_TITLES: dict[CloudStrategy, str] = {
    "auto": "Только то, что не читается",
    "page": "Каждую страницу целиком",
}
CLOUD_STRATEGY_HINTS: dict[CloudStrategy, str] = {
    "auto": (
        "Готовый текст берётся из файла бесплатно и точно, наружу уходят только "
        "формулы, схемы и сканы. Дешевле в разы, и страница целиком не покидает "
        "компьютер."
    ),
    "page": (
        "Каждая страница уходит в модель картинкой. Дороже и медленнее, зато "
        "вёрстку и порядок чтения выбирает модель, а не разметчик PDF."
    ),
}


@dataclass(frozen=True)
class OcrEngineSpec:
    key: str
    title: str
    # Одно предложение о том, что движок делает со страницей.
    description: str
    # Чем он берёт и чем расплачивается. Читается сразу после описания.
    trade_off: str
    # По времени выполнения различаются и настройки: у локального движка это
    # модель и язык, у облачного — провайдер, модель и стратегия, и они живут
    # в разных разделах экрана.
    runtime: EngineRuntime


OCR_ENGINES: dict[str, OcrEngineSpec] = {
    spec.key: spec
    for spec in (
        OcrEngineSpec(
            "fast",
            "Быстро",
            "Забирает готовый текст прямо из файла, а распознаёт только картинки и сканы.",
            "Считает на процессоре, подойдёт любому компьютеру. Формулы не читает — "
            "сохраняет их вырезом, чтобы не потерять.",
            "worker",
        ),
        OcrEngineSpec(
            "cloud",
            "Облако",
            "Отдаёт страницы внешней модели и получает разметку с формулами в LaTeX.",
            "Читает то, с чем локальный распознаватель не справляется. Но файл уходит "
            "с вашего компьютера, и разбор стоит денег.",
            "cloud",
        ),
    )
}


@dataclass(frozen=True)
class OcrRuntimeParams:
    """Что реально читает воркер и парсеры при разборе одного материала.

    Отдельно от `OcrSettingsRead`: парсеры не знают про БД и про реестр,
    только про эти примитивные значения.
    """

    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD
    raster_scale: float = DEFAULT_RASTER_SCALE
    fast_language: str = DEFAULT_FAST_LANGUAGE
    fast_model_id: str = DEFAULT_FAST_MODEL_ID
    cloud_strategy: CloudStrategy = DEFAULT_CLOUD_STRATEGY
