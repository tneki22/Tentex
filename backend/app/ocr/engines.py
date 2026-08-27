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
DEFAULT_TEXTBOOK_MODEL_ID = "PP-StructureV3 + PP-FormulaNet Plus M"
DEFAULT_TEXTBOOK_DEVICE = "gpu"
DEFAULT_TEXTBOOK_EXECUTOR = "formulas"


@dataclass(frozen=True)
class OcrEngineSpec:
    key: str
    title: str
    # Одно предложение о том, что движок делает со страницей.
    description: str
    # Чем он берёт и чем расплачивается. Читается сразу после описания.
    trade_off: str
    runtime: EngineRuntime
    # Статические заглушки (cloud/maximum/expert) не имеют ни настроек, ни строки в БД.
    configurable: bool = True
    unavailable_reason: str | None = None


OCR_ENGINES: dict[str, OcrEngineSpec] = {
    spec.key: spec
    for spec in (
        OcrEngineSpec(
            "fast",
            "Быстро",
            "Забирает готовый текст прямо из файла, а распознаёт только картинки и сканы.",
            "Считает на процессоре, подойдёт любому компьютеру. Сложные формулы и "
            "многоколоночную вёрстку разбирает приблизительно.",
            "worker",
        ),
        OcrEngineSpec(
            "textbook",
            "Учебник",
            "Читает страницу целиком: формулы, колонки, заголовки и подписи под рисунками.",
            "Нужна видеокарта NVIDIA с 8 ГБ памяти и отдельно запущенный сервис. "
            "Таблицы остаются обычным текстом, зато профиль помещается в память.",
            "gpu_service",
        ),
        OcrEngineSpec(
            "cloud",
            "Облако",
            "Отправляет страницы во внешний сервис и получает готовый разбор.",
            "Не нужна ни видеокарта, ни ожидание — но файл уходит с вашего компьютера "
            "и разбор стоит денег.",
            "cloud",
            configurable=False,
            unavailable_reason="Ещё не подключено. Появится вместе с отправкой файлов наружу.",
        ),
        OcrEngineSpec(
            "maximum",
            "Максимум",
            "Разбирает документ на структуру: заголовки, уровни, таблицы, координаты.",
            "Внешний сервис и цена выше облачного разбора.",
            "cloud",
            configurable=False,
            unavailable_reason="Ещё не подключено.",
        ),
        OcrEngineSpec(
            "expert",
            "Эксперт",
            "Перепроверяет отдельные сомнительные места: формулы, рукописные вставки.",
            "Дороже всех и применяется точечно, а не ко всему документу.",
            "cloud",
            configurable=False,
            unavailable_reason="Ещё не подключено.",
        ),
    )
}


@dataclass(frozen=True)
class OcrRuntimeParams:
    """Что реально читает воркер и парсеры при разборе одного материала.

    Отдельно от `OcrSettingsRead`: парсеры не знают про БД и про реестр,
    только про эти примитивные значения. `textbook_base_url`/`timeout` — `None`
    означает «взять дефолт из `app.config.settings`».
    """

    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD
    raster_scale: float = DEFAULT_RASTER_SCALE
    fast_language: str = DEFAULT_FAST_LANGUAGE
    fast_model_id: str = DEFAULT_FAST_MODEL_ID
    textbook_base_url: str | None = None
    textbook_timeout_seconds: float | None = None
