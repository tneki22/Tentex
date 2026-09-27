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
# Выбирается на запуск; значение в настройках — только выбор по умолчанию.
CloudStrategy = Literal["economy", "auto", "page"]
DEFAULT_CLOUD_STRATEGY: CloudStrategy = "auto"
CLOUD_STRATEGY_TITLES: dict[CloudStrategy, str] = {
    "economy": "Экономно",
    "auto": "Адаптивно",
    "page": "Каждую страницу",
}
CLOUD_STRATEGY_HINTS: dict[CloudStrategy, str] = {
    "economy": (
        "Готовый текст берётся из файла бесплатно, наружу уходят только формулы, "
        "схемы и сканы без текстового слоя. Страница с испорченным слоем помечается "
        "для проверки, но целиком не отправляется."
    ),
    "auto": (
        "Как «Экономно», но страница с неполным или испорченным текстовым слоем "
        "уходит в модель целиком. Причина выбора сохраняется в диагностике страницы."
    ),
    "page": (
        "Каждая страница уходит в модель картинкой. Дороже и медленнее, зато "
        "вёрстку и порядок чтения выбирает модель, а не разметчик PDF."
    ),
}

# Что делать с изображениями на запуске. У «Быстро» описаний нет: только текст
# внутри картинки локальным OCR или ничего.
ImageMode = Literal["describe", "text_only", "skip"]
IMAGE_MODE_TITLES: dict[ImageMode, str] = {
    "describe": "Описывать",
    "text_only": "Только текст",
    "skip": "Не распознавать",
}
IMAGE_MODE_HINTS: dict[ImageMode, str] = {
    "describe": (
        "Каждое содержательное изображение отдельным запросом получает название, "
        "описание, надписи и при наличии — таблицу или формулу. Повторяющиеся "
        "логотипы и колонтитулы не отправляются."
    ),
    "text_only": "Из изображения берутся только надписи, без описания увиденного.",
    "skip": "Изображения остаются вырезами оригинала без текста.",
}
DEFAULT_IMAGE_MODE: dict[str, ImageMode] = {"cloud": "describe", "fast": "text_only"}
IMAGE_MODES_BY_ENGINE: dict[str, tuple[ImageMode, ...]] = {
    "cloud": ("describe", "text_only", "skip"),
    "fast": ("text_only", "skip"),
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
    # `None` — выбор движка по умолчанию (`DEFAULT_IMAGE_MODE`).
    image_mode: ImageMode | None = None

    def images_for(self, engine: str) -> ImageMode:
        """Режим изображений, реально действующий для движка этого запуска."""
        allowed = IMAGE_MODES_BY_ENGINE.get(engine, ("text_only", "skip"))
        if self.image_mode in allowed:
            return self.image_mode  # type: ignore[return-value]
        return DEFAULT_IMAGE_MODE.get(engine, "text_only")
