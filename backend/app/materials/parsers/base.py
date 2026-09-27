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
# Метка описания, сделанного моделью. Стоит в начале текста фрагмента, поэтому
# доезжает и до поиска, и до цитаты в чате: описание не выдаётся за текст книги.
MODEL_DESCRIPTION_MARK = "[Описание изображения, сделано моделью]"

# Три независимые оси состояния изображения. Смешивать их нельзя: «описано»
# не значит «проверено», а «служебное» не значит «удалено».
ImageRole = Literal["content", "service", "decorative", "unknown"]
ImageProcessing = Literal["unprocessed", "text_only", "described", "legacy", "skipped", "error"]
ImageReview = Literal["unreviewed", "needs_review", "verified", "manual"]


@dataclass(frozen=True, slots=True)
class ImageDescription:
    """Структурированный ответ модели про один вырез.

    Видимое (`objects`, `relations`, `labels`) хранится отдельно от того, что
    модель взяла из подписи и соседнего текста (`context_note`): контекст не
    выдаётся за увиденное на картинке.
    """

    kind: str
    title: str
    summary: str
    objects: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    table_markdown: str = ""
    latex: str = ""
    context_note: str = ""
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ImageProvenance:
    """Кто и чем сделал текст изображения — для цитаты и для повторного запуска."""

    source: Literal["parse", "describe_job", "manual", "legacy"]
    model_id: str | None = None
    provider_id: str | None = None
    prompt_version: str | None = None
    run_id: str | None = None
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class ImageMeta:
    """Состояние изображения страницы: роль, обработка, проверка и происхождение.

    `reasons` — машинные коды того, почему кандидат служебный, сомнительный или
    не отправлен (`repeated_margin`, `bbox_unreliable`, `asset_missing`…).
    `signals` — наблюдения, из которых сложилось решение: размер, повтор, подпись.
    """

    role: ImageRole = "unknown"
    processing: ImageProcessing = "unprocessed"
    review: ImageReview = "unreviewed"
    reasons: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    detection: str = "embedded"
    crop_hash: str | None = None
    pixel_size: tuple[int, int] | None = None
    caption: str | None = None
    description: ImageDescription | None = None
    provenance: ImageProvenance | None = None


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
    # Состояние изображения; у остальных видов элементов — None.
    image: ImageMeta | None = None


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


@dataclass(frozen=True, slots=True)
class ImageRequest:
    """Один вырез-изображение, отправляемый на описание.

    Модель получает только сам вырез, номер страницы, подпись и ограниченные
    соседние абзацы — не страницу и не материал целиком.
    """

    index: int
    image: bytes
    page_number: int
    crop_hash: str
    caption: str | None = None
    context: str = ""
    media_type: str = "image/png"


@dataclass(frozen=True, slots=True)
class DescribedImage:
    """Ответ про один вырез после проверки: описание или причина отказа."""

    index: int
    description: ImageDescription | None
    review: ImageReview
    reasons: tuple[str, ...] = ()
    role_hint: ImageRole | None = None
    run_id: str | None = None
    model_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PageImage:
    """Растр страницы, отправляемый модели целиком."""

    image: bytes
    page_number: int
    width: float
    height: float


class PageRecognizer(Protocol):
    """Порт распознавания страницы внешней моделью.

    Реализация живёт в `app.materials.parsers.cloud_vlm` и тянет за собой шлюз
    моделей и сессию БД; парсеры зависят только от этого протокола, поэтому
    `native.py` остаётся свободен от импорта пакета `app.ai`.
    """

    # Сколько страниц разбор может отдать наперёд одним `prefetch_pages`.
    concurrency: int

    def recognize_page(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        """Прочитать страницу целиком: разметка, порядок чтения и формулы."""

    def prefetch_pages(self, pages: Sequence[PageImage]) -> None:
        """Прочитать страницы наперёд; `recognize_page` потом отдаст готовое.

        Только ускорение: реализация вправе ничего не делать.
        """

    def recognize_regions(
        self, regions: Sequence[RegionRequest], page_number: int
    ) -> list[RecognizedRegion]:
        """Прочитать отдельные вырезы страницы, не трогая остальной текст."""

    def describe_images(self, images: Sequence[ImageRequest]) -> list[DescribedImage]:
        """Описать вырезы-изображения: по одному вызову на видимое содержание."""
