"""Общие типы разбора материала: элемент страницы, страница и порт распознавания.

Здесь нет ни PDF, ни моделей, ни сети — только то, чем парсеры обмениваются
между собой и с воркером. Внешнее распознавание подключается через протокол
:class:`PageRecognizer`: парсер знает, что кто-то умеет прочитать картинку, и
не знает, кто именно и по какому протоколу.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

ElementKind = Literal["heading", "paragraph", "list", "table", "formula", "image"]
RecognitionSource = Literal["native", "ocr", "vl", "manual"]

# Подпись нераспознанного содержания. Одно место на все парсеры: текст попадает
# и в Markdown страницы, и в поиск, и в просмотрщик.
IMAGE_PLACEHOLDER = "[Изображение]"


@dataclass(frozen=True, slots=True)
class ParsedElement:
    kind: ElementKind
    text: str
    bbox: tuple[float, float, float, float]
    level: int | None = None
    confidence: float | None = None
    time_from: float | None = None
    time_to: float | None = None
    # Исходный вырез доступен у изображений, формул и таблиц.
    asset_path: str | None = None
    recognition_source: RecognitionSource = "native"
    # Координаты пришли от разметки страницы, а не подставлены заглушкой.
    # Внешняя модель нередко возвращает элемент вовсе без bbox, и тогда он
    # получает полосу во всю ширину (`cloud_vlm._fallback_bbox`). Вырезать
    # картинку по такой полосе нельзя: получится кусок соседнего текста.
    bbox_reliable: bool = True


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    width: float
    height: float
    markdown: str
    plain_text: str
    quality: Literal["native", "ocr", "ocr_low"]
    elements: tuple[ParsedElement, ...]
    diagnostics: tuple[str, ...] = ()
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class RegionRequest:
    """Один вырез страницы, отправляемый на распознавание внешней моделью.

    `index` возвращается моделью обратно и связывает ответ с элементом
    страницы: полагаться на порядок в ответе нельзя.
    """

    index: int
    kind: ElementKind
    image: bytes
    media_type: str = "image/png"


@dataclass(frozen=True, slots=True)
class RecognizedRegion:
    """Что внешняя модель вернула про один вырез."""

    index: int
    kind: ElementKind
    text: str
    confidence: float


class PageRecognizer(Protocol):
    """Порт распознавания страницы внешней моделью.

    Реализация живёт в `app.materials.parsers.cloud_vlm` и тянет за собой шлюз
    моделей и сессию БД; парсеры зависят только от этого протокола, поэтому
    `native.py` остаётся свободен от импорта пакета `app.ai`.
    """

    def recognize_page(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        """Прочитать страницу целиком: разметка, порядок чтения и формулы."""

    def recognize_regions(
        self, regions: Sequence[RegionRequest], page_number: int
    ) -> list[RecognizedRegion]:
        """Прочитать отдельные вырезы страницы, не трогая остальной текст."""
