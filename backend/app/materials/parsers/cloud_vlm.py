"""Режим «Облако»: страницу или её вырезы читает внешняя зрительная модель.

Реализация порта :class:`app.materials.parsers.base.PageRecognizer`. Здесь
собирается запрос, проверяется ответ и строится обычная `ParsedPage` — всё
остальное (выбор модели, ключи, лимиты, учёт стоимости и кэш) делает шлюз
моделей, и дублировать его тут нечем.

Ответ модели не принимается на веру. Зрительная модель не ошибается «немного
не так» — она пересказывает: текст выглядит гладким и правильным, а абзаца в
нём нет. Поэтому у каждой страницы проверяются координаты, синтаксис формул и
объём ответа, а всё сомнительное уходит в качество `ocr_low`, то есть в
«требует проверки», а не в готовый материал.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass, field, replace
from io import BytesIO
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.budget import BudgetContext
from app.ai.gateway import RETRY_BACKOFF_SECONDS, AiResult, AiTextRequest, ModelGateway
from app.ai.provider import OpenAICompatibleTransport
from app.ai.schemas import AiImagePart, AiImageUrl, AiMessage, AiModelSelection, AiTextPart
from app.ai.settings import AiGatewayError
from app.materials.parsers.base import (
    DescribedImage,
    ElementKind,
    ImageDescription,
    ImageRequest,
    PageImage,
    ParsedElement,
    ParsedPage,
    RecognizedRegion,
    RegionRequest,
)
from app.ocr.engines import DEFAULT_QUALITY_THRESHOLD
from app.projects.errors import ProjectDomainError

log = logging.getLogger("tentex.worker")

ROLE = "material_page_recognition"
IMAGE_ROLE = "material_image_description"
# Версия промпта описаний: попадает в происхождение описания и в снимок задачи.
IMAGE_PROMPT_VERSION = "image-description-v1"
# Описание — платный этап: не больше одного автоматического повтора на вызов.
IMAGE_RETRY_BACKOFF: tuple[float, ...] = (3.0,)
# Ниже этой уверенности описание сохраняется, но требует проверки.
IMAGE_REVIEW_CONFIDENCE = 0.5
MIN_SUMMARY_CHARS = 20
# Причина «не описано»: предел запуска исчерпан раньше, чем очередь изображений.
BUDGET_REASON = "budget_exhausted"
# Строка-разделитель Markdown-таблицы: без неё перечисление ячеек таблицей не считается.
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}", re.MULTILINE)
# Мнение модели о роли — только сигнал: «unclear» решения не меняет.
ROLE_HINTS: dict[str, str] = {
    "content": "content",
    "decorative": "decorative",
    "service": "service",
}

# Сколько вырезов уходит одним запросом. Больше — ответ упирается в потолок
# токенов и обрывается на середине формулы, меньше — платим за инструкцию
# столько же раз, сколько на странице формул.
MAX_REGIONS_PER_REQUEST = 6
# Сколько вызовов одного разбора идут к модели одновременно: пачки вырезов и
# описания страницы, страницы-сканы наперёд. Время разбора — это ожидание
# ответа, а не работа процессора; четыре запроса разом не упираются в лимиты
# запросов OpenRouter и не держат лишних резервов предела запуска.
DEFAULT_CONCURRENCY = 4

# Метка нечитаемого места: модель ставит её вместо догадки, а мы по ней
# опускаем уверенность элемента, даже если сама модель этого не сделала.
UNREADABLE_MARK = "⟨?⟩"
# Первые байты JPEG: страница для модели рендерится в JPEG, вырезы — в PNG.
JPEG_SIGNATURE = bytes((0xFF, 0xD8, 0xFF))
# Потолок уверенности для элемента с оговоркой: дальше страница уходит в
# «требует проверки», а не в готовый материал.
SUSPECT_CONFIDENCE = 0.4

# Коды, после которых разбор материала имеет смысл продолжать: они говорят про
# один конкретный ответ, а не про настройку. Ключ, лимиты стоимости и
# несовместимость модели сюда не входят — от продолжения они не чинятся, и
# разбор обязан остановиться на первой же такой ошибке.
SURVIVABLE_CODES = frozenset(
    {
        "ai_invalid_structured_output",
        "ai_empty_response",
        "ai_provider_unavailable",
        "ai_rate_limited",
        "ai_timeout",
    }
)
# Сколько кусков подряд может не прочитаться, прежде чем разбор останавливается
# целиком. Одна страница — это ответ, который не разобрать: терять из-за неё
# остальные шестьдесят незачем, её достаточно перезапустить диапазоном. Три
# подряд — это уже лежащий провайдер, и продолжать нельзя, иначе получится
# материал из пустых страниц, помеченный как готовый.
MAX_CONSECUTIVE_FAILURES = 3


class PageUnreadable(Exception):
    """Внешняя модель не прочитала этот кусок, но разбор продолжается."""


TEX_ENVIRONMENT_RE = re.compile(r"\\(begin|end)\{([^}]+)\}")
# Признак «это LaTeX, а не обычный текст»: команда вида \frac, \int, \lim.
# Обычный русский или английский текст с распознанной страницы такой
# последовательности не даёт — обратный слеш там не встречается.
BARE_LATEX_RE = re.compile(r"\\[a-zA-Z]{2,}")

PAGE_INSTRUCTION = """Ты распознаёшь страницу учебного документа.
Верни JSON по схеме и ничего кроме него.

1. Переписывай текст дословно. Не исправляй опечатки, не сокращай, не пересказывай
   и ничего не добавляй от себя.
2. Формулы — в LaTeX: внутристрочные $...$, выносные $$...$$. Обрамляй знаками
   $ каждую формулу без исключения, включая ту, что стоит отдельной строкой —
   голый LaTeX без $ не отрисуется. Номер формулы, напечатанный на странице,
   ставь в \\tag{...}.
3. Таблица — только Markdown с вертикальными чертами и строкой-разделителем,
   ровно в таком виде (в ячейке допустим LaTeX):
   | № | Функция | Первообразная |
   |---|---------|---------------|
   | 1 | $x^n$ | $\\frac{x^{n+1}}{n+1} + C$ |
   Перечисление ячеек через перевод строки таблицей не считается.
4. Порядок элементов — порядок чтения. Две колонки: сначала левая целиком, потом правая.
5. Колонтитул, номер страницы и маргиналия — отдельные элементы своего вида,
   не части соседнего абзаца.
6. Нечитаемое место передавай как ⟨?⟩ и ставь этому элементу confidence ниже 0.5.
7. bbox — доля от размера страницы: [x0, y0, x1, y1] в диапазоне 0..1,
   считая от левого верхнего угла. Если удобнее в пикселях присланной
   картинки — присылай в пикселях, но одинаково для всех элементов."""

REGION_INSTRUCTION = """Тебе даны вырезы со страницы учебного документа.
Текст страницы уже прочитан, нужно прочитать только эти куски.
Верни JSON по схеме и ничего кроме него.

1. Формулу передавай в LaTeX без окружения: `\\int_a^b f(x)\\,dx = F(b) - F(a)`.
   Номер формулы, напечатанный рядом, ставь в \\tag{...}.
2. Таблицу передавай Markdown с вертикальными чертами и строкой-разделителем:
   `| № | Функция |`, ниже `|---|---------|`, ниже строки данных. В ячейке
   допустим LaTeX. Перечисление ячеек через перевод строки таблицей не считается.
3. У графика, схемы или фотографии перепиши только надписи на изображении
   дословно, через перевод строки. Надписей нет — верни пустую строку.
   Не описывай, что изображено.
4. Обычный текст переписывай дословно.
5. index в ответе — тот же, что и в подписи к вырезу; порядок ответов неважен.
6. Нечитаемое место передавай как ⟨?⟩ и ставь confidence ниже 0.5."""


IMAGE_INSTRUCTION = """Ты описываешь один вырез-изображение из учебного материала.
Описание нужно для поиска и проверки человеком. Верни JSON по схеме и ничего
кроме него. Пиши по-русски.

1. Описывай только то, что видно на вырезе. Подпись и соседний текст даны для
   ориентира: всё, что взято из них, а не увидено, пиши только в context_note.
2. title — короткое название, до 10 слов. summary — 2–6 предложений: что
   изображено и как части связаны. Не делай выводов, которых изображение не
   подтверждает.
3. visible_objects — видимые объекты. relations — связи между ними в виде
   «A → B: что передаётся». labels — все надписи на изображении дословно.
4. details: у графика — оси, единицы и легенда; у таблицы — строки и столбцы;
   у схемы — узлы и связи.
5. Таблица — table_markdown: Markdown с | и строкой-разделителем. Формула —
   latex без $ и без окружения. Иначе оба поля — пустые строки.
6. Нечитаемое не угадывай: перечисли такие места в unreadable и снизь confidence.
7. crop_issue: cut_off — рисунок обрезан рамкой; extra_text — в вырез попал
   посторонний абзац; multiple_objects — несколько независимых рисунков;
   empty — вырез пустой; unreadable — прочитать нельзя; иначе none.
8. content_role: content — содержательное изображение; decorative — украшение
   или фон; service — логотип, колонтитул, служебная отметка; unclear — не понять."""


class CloudImageDescription(BaseModel):
    """Ответ модели про один вырез-изображение."""

    kind: Literal[
        "diagram",
        "chart",
        "photo",
        "screenshot",
        "table",
        "formula",
        "text",
        "map",
        "drawing",
        "other",
    ]
    content_role: Literal["content", "decorative", "service", "unclear"]
    crop_issue: Literal["none", "cut_off", "extra_text", "multiple_objects", "empty", "unreadable"]
    title: str
    summary: str
    visible_objects: list[str]
    relations: list[str]
    labels: list[str]
    unreadable: list[str]
    details: list[str]
    table_markdown: str
    latex: str
    context_note: str
    confidence: float = Field(ge=0, le=1)


class CloudElement(BaseModel):
    """Один элемент страницы в ответе модели."""

    kind: Literal[
        "heading",
        "paragraph",
        "list",
        "table",
        "formula",
        "image",
        "header",
        "footer",
        "margin_note",
        "caption",
        "code",
    ]
    text: str
    # Список, а не кортеж: строгая схема ответа у провайдеров не понимает
    # ограничений на длину массива, поэтому длина проверяется уже здесь.
    bbox: list[float]
    level: int | None
    confidence: float = Field(ge=0, le=1)


class CloudPage(BaseModel):
    """Страница целиком, как её увидела модель."""

    elements: list[CloudElement]
    page_confidence: float = Field(ge=0, le=1)


class CloudRegion(BaseModel):
    """Ответ про один вырез страницы."""

    index: int
    kind: Literal["formula", "table", "figure", "text"]
    content: str
    confidence: float = Field(ge=0, le=1)


class CloudRegions(BaseModel):
    regions: list[CloudRegion]


# Виды элементов у модели богаче наших: колонтитул и маргиналия — это всё равно
# абзацы, но помечать их отдельно модели проще, чем угадывать, куда их деть.
PAGE_KINDS: dict[str, ElementKind] = {
    "heading": "heading",
    "paragraph": "paragraph",
    "list": "list",
    "table": "table",
    "formula": "formula",
    "image": "image",
    "header": "paragraph",
    "footer": "paragraph",
    "margin_note": "paragraph",
    "caption": "paragraph",
    "code": "paragraph",
}
REGION_KINDS: dict[str, ElementKind] = {
    "formula": "formula",
    "table": "table",
    "figure": "image",
    "text": "paragraph",
}


def latex_issues(text: str) -> list[str]:
    """Что не так с формулами внутри текста.

    Формула, которую фронтенд не отрисует, — это брак распознавания, и ловить
    его надо здесь, а не глазами в просмотрщике. Проверки намеренно дешёвые:
    настоящий разбор TeX тут не нужен, нужен признак «сюда надо посмотреть».
    """
    issues: list[str] = []
    if text.count("$$") % 2:
        issues.append("unbalanced_display_math")
    if (text.count("$") - 2 * text.count("$$")) % 2:
        issues.append("unbalanced_inline_math")
    if text.count("{") != text.count("}"):
        issues.append("unbalanced_braces")
    opened: list[str] = []
    for command, name in TEX_ENVIRONMENT_RE.findall(text):
        if command == "begin":
            opened.append(name)
        elif not opened or opened.pop() != name:
            issues.append("unbalanced_environment")
            break
    if opened:
        issues.append("unbalanced_environment")
    return issues


def wrap_bare_latex(text: str) -> str:
    """Обернуть формулу, которую модель забыла обрамить `$`/`$$`.

    Инструкция просит выносные формулы в `$$...$$`, но на практике модель
    иногда пишет корректный LaTeX отдельным абзацем без единого `$` вовсе —
    прогон бенчмарка показал это на нескольких страницах подряд. KaTeX такой
    текст не тронет: снаружи это просто строка с обратными слешами. Оборачиваем,
    только если `$` в тексте нет вообще — уже размеченный ответ не трогаем,
    а частичная разметка (одна формула в $, другая без) встречается редко и
    сигнализирует не то же самое, что чистый пропуск. Многострочный текст с
    `|` не трогаем совсем — это ячейка таблицы Markdown, не формула: ячейка
    законно несёт свою формулу без `$`, и обёртка всей таблицы в `$$...$$`
    из-за одной такой ячейки сломала бы обе вещи разом — так уже случилось
    на прогоне бенчмарка. Настоящий многострочный `\\begin{aligned}` пирог с
    `|` внутри не пишет почти никто, а недооборот тут дешевле, чем разбитая
    таблица.
    """
    if "$" in text or ("\n" in text and "|" in text) or not BARE_LATEX_RE.search(text):
        return text
    return f"$${text}$$"


def _data_url(image: bytes, media_type: str | None = None) -> str:
    """`data:`-URL картинки; тип без подсказки — по сигнатуре (JPEG или PNG)."""
    kind = media_type or ("image/jpeg" if image.startswith(JPEG_SIGNATURE) else "image/png")
    return f"data:{kind};base64,{base64.b64encode(image).decode()}"


def _pixel_size(image: bytes) -> tuple[float, float]:
    """Размер присланного растра в пикселях. Не прочитался — считаем неизвестным."""
    try:
        with Image.open(BytesIO(image)) as opened:
            return float(opened.width), float(opened.height)
    except (OSError, ValueError):
        return 0.0, 0.0


def _clamped_bbox(
    values: Sequence[float], pixel_width: float = 0.0, pixel_height: float = 0.0
) -> tuple[float, float, float, float] | None:
    """Координаты модели в нашу долю страницы или `None`, если их нет вовсе.

    Инструкция просит доли `0..1`, но модели сплошь и рядом отвечают в пикселях
    присланного растра или в условной сетке `0..1000`: прогон бенчмарка на
    `gemini-2.5-flash-lite` не дал ни одной нормализованной рамки из трёхсот.
    Читать такой ответ как доли нельзя — после клампа все четыре числа
    становятся `1.0`, рамка схлопывается, и элемент остаётся без координат: без
    вырезки, без рамки на оригинале и с полосой во всю ширину вместо места на
    странице. Поэтому масштаб определяется по самим числам, а не по вере в
    инструкцию.
    """
    if len(values) != 4:
        return None
    raw = [float(value) for value in values]
    if any(value < 0 for value in raw):
        return None
    scale_x, scale_y = _bbox_scale(raw, pixel_width, pixel_height)
    x0, y0, x1, y1 = (
        max(0.0, min(1.0, raw[0] / scale_x)),
        max(0.0, min(1.0, raw[1] / scale_y)),
        max(0.0, min(1.0, raw[2] / scale_x)),
        max(0.0, min(1.0, raw[3] / scale_y)),
    )
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _bbox_scale(
    raw: Sequence[float], pixel_width: float, pixel_height: float
) -> tuple[float, float]:
    """Во что делить координаты модели: доли, пиксели растра или сетка 0..1000."""
    if max(raw) <= 1.0:
        return 1.0, 1.0
    if pixel_width > 0 and pixel_height > 0 and raw[2] <= pixel_width and raw[3] <= pixel_height:
        return pixel_width, pixel_height
    # Сетка 0..1000 — вторая по распространённости договорённость у зрительных
    # моделей. Берётся, когда числа не влезают в присланный растр либо его
    # размер прочитать не удалось.
    return 1000.0, 1000.0


def _fallback_bbox(index: int, total: int) -> tuple[float, float, float, float]:
    """Заглушка координат: элементы раскладываются полосами сверху вниз.

    Так же поступает разбор простого текста — фрагмент всё равно должен на что-то
    указывать, иначе просмотрщик не покажет его вовсе.
    """
    return (0.0, index / max(1, total), 1.0, (index + 1) / max(1, total))


@dataclass
class CloudRecognizer:
    """Распознавание внешней моделью для одного разбора материала.

    Держит сессию БД, потому что через неё работают и шлюз, и учёт стоимости.
    Живёт ровно столько, сколько идёт разбор одного материала — воркер
    обязан вызвать :meth:`close` после последней страницы (`finally`, не в
    конце счастливого пути), иначе общий event loop останется висеть до
    сборки мусора.
    """

    session: Session
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD
    # Тот же шов, что и у самого шлюза: подменяется в тестах, в работе `None`.
    transport: OpenAICompatibleTransport | None = None
    # Паузы между повторами вызова. В работе — боевые из шлюза; тесты передают
    # пустую последовательность, чтобы не ждать по-настоящему.
    retry_backoff: Sequence[float] = RETRY_BACKOFF_SECONDS
    # Снимок моделей запуска. `None` — модель роли по умолчанию (старые задачи
    # без снимка и одноразовые проверки).
    page_model: AiModelSelection | None = None
    description_model: AiModelSelection | None = None
    # Денежный и счётный предел запуска: резерв до сети, расход по `usage`.
    budget: BudgetContext | None = None
    image_retry_backoff: Sequence[float] = IMAGE_RETRY_BACKOFF
    # Одновременных вызовов модели; 1 — строго по очереди.
    concurrency: int = DEFAULT_CONCURRENCY
    # Один event loop на весь разбор материала, а не на каждый вызов модели.
    # `asyncio.run()` в `_ask` создавал и закрывал свой loop на каждой странице
    # и на каждой пачке вырезов; `AsyncOpenAI`-клиент внутри шлюза переживал
    # закрытие своего loop'а, и сборщик мусора пытался закрыть его соединения
    # уже на чужом (следующем) loop'е — воркер получал россыпь
    # `RuntimeError: Event loop is closed` в логе на каждом облачном разборе.
    _loop: asyncio.AbstractEventLoop | None = field(
        default=None, init=False, repr=False, compare=False
    )
    # Сколько кусков подряд не прочиталось. Считается подряд, а не всего:
    # разрозненные осечки — это свойство модели, а сплошная полоса — авария.
    _failures: int = field(default=0, init=False, repr=False, compare=False)
    # Видимые факты по точному хешу выреза: повтор той же картинки в этом
    # запуске не оплачивается второй раз.
    _visible: dict[str, DescribedImage] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _images_stopped: bool = field(default=False, init=False, repr=False, compare=False)
    # Страницы, прочитанные наперёд (`prefetch_pages`): ответ или исключение,
    # которое поднимется, только когда разбор дойдёт до этой страницы.
    _prefetched: dict[int, ParsedPage | BaseException] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _slots: asyncio.Semaphore | None = field(default=None, init=False, repr=False, compare=False)

    def close(self) -> None:
        """Закрыть общий event loop. Без вызова он держит ресурсы до GC."""
        if self._loop is not None:
            self._loop.close()
            self._loop = None
            self._slots = None

    def recognize_page(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        """Прочитать страницу целиком: разметка, порядок чтения и формулы."""
        ready = self._prefetched.pop(page_number, None)
        if ready is None:
            return self._run(self._page_async(image, page_number, width, height))
        if isinstance(ready, BaseException):
            raise ready
        return ready

    def prefetch_pages(self, pages: Sequence[PageImage]) -> None:
        """Прочитать несколько страниц разом, пока разбор занят предыдущими.

        Скан книги — это сотни одинаковых вызовов подряд, и почти всё время
        разбора уходит на ожидание ответа. Ответы складываются по номеру
        страницы и отдаются `recognize_page` в обычном порядке; ошибка страницы
        (исчерпанный предел, отказ ключа) поднимается тоже только на ней, так
        что страницы до неё сохраняются как раньше. Прочитанные наперёд, но не
        сохранённые из-за паузы страницы не пропадают: при продолжении их отдаст
        кэш шлюза по содержимому.
        """
        todo = [page for page in pages if page.page_number not in self._prefetched]
        outcomes = self._gather(
            [
                self._page_async(page.image, page.page_number, page.width, page.height)
                for page in todo
            ]
        )
        for page, outcome in zip(todo, outcomes, strict=True):
            self._prefetched[page.page_number] = outcome

    async def _page_async(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        try:
            answer = await self._ask_async(
                [
                    AiTextPart(text=PAGE_INSTRUCTION),
                    AiImagePart(image_url=AiImageUrl(url=_data_url(image))),
                ],
                CloudPage,
                page_number,
                role=ROLE,
                model=self.page_model,
            )
        except PageUnreadable as error:
            return _unreadable_page(page_number, width, height, str(error))
        return self._page(answer.value, page_number, width, height, _pixel_size(image))

    def recognize_regions(
        self, regions: Sequence[RegionRequest], page_number: int
    ) -> list[RecognizedRegion]:
        """Прочитать вырезы страницы, не трогая уже готовый текстовый слой.

        Пачки уходят одновременно. Пачка, на которой модель сорвалась, просто
        пропускается: текст страницы уже прочитан из файла и от этого не
        страдает, а формулы останутся вырезами оригинала — ровно как в «Быстро».
        """
        batches = [
            regions[start : start + MAX_REGIONS_PER_REQUEST]
            for start in range(0, len(regions), MAX_REGIONS_PER_REQUEST)
        ]
        answers = self._gather(
            [
                self._ask_async(
                    self._region_parts(batch), CloudRegions, page_number,
                    role=ROLE, model=self.page_model,
                )
                for batch in batches
            ]
        )
        result: list[RecognizedRegion] = []
        for batch, answer in zip(batches, answers, strict=True):
            if isinstance(answer, PageUnreadable):
                continue
            if isinstance(answer, BaseException):
                raise answer
            known = {region.index for region in batch}
            result.extend(
                RecognizedRegion(
                    index=item.index,
                    kind=REGION_KINDS.get(item.kind, "image"),
                    text=item.content,
                    confidence=item.confidence,
                )
                for item in answer.value.regions
                if item.index in known
            )
        return result

    @staticmethod
    def _region_parts(regions: Sequence[RegionRequest]) -> list[AiTextPart | AiImagePart]:
        """Инструкция, а дальше пары «подпись с индексом — картинка выреза»."""
        parts: list[AiTextPart | AiImagePart] = [AiTextPart(text=REGION_INSTRUCTION)]
        for region in regions:
            parts.append(AiTextPart(text=f"Вырез index={region.index}, вид: {region.kind}."))
            parts.append(
                AiImagePart(
                    image_url=AiImageUrl(url=_data_url(region.image, region.media_type))
                )
            )
        return parts

    def describe_images(self, images: Sequence[ImageRequest]) -> list[DescribedImage]:
        """Описать вырезы-изображения: один вызов на видимое содержание.

        Новые вырезы описываются одновременно. Вырез с уже описанным в этом
        запуске хешем получает те же видимые факты без вызова; контекстное
        название у него своё — его подпись. Сорвавшийся вызов не роняет разбор:
        изображение получает статус ошибки и остаётся вырезом оригинала.
        """
        first: dict[str, ImageRequest] = {}
        for request in images:
            if request.crop_hash not in self._visible:
                first.setdefault(request.crop_hash, request)
        outcomes: dict[str, DescribedImage] = {}
        if first and not self._images_stopped:
            answers = self._gather([self._describe_async(request) for request in first.values()])
            for request, answer in zip(first.values(), answers, strict=True):
                if isinstance(answer, BaseException):
                    raise answer
                outcomes[request.crop_hash] = answer
                if answer.description is not None:
                    self._visible[request.crop_hash] = answer
        result: list[DescribedImage] = []
        for request in images:
            if first.get(request.crop_hash) is request and request.crop_hash in outcomes:
                result.append(outcomes[request.crop_hash])
            elif request.crop_hash in self._visible:
                result.append(_reused(self._visible[request.crop_hash], request))
            elif request.crop_hash in outcomes:
                result.append(replace(outcomes[request.crop_hash], index=request.index))
            else:
                result.append(DescribedImage(request.index, None, "unreviewed", (BUDGET_REASON,)))
        return result

    async def _describe_async(self, request: ImageRequest) -> DescribedImage:
        try:
            answer = await self._ask_async(
                self._image_parts(request),
                CloudImageDescription,
                request.page_number,
                role=IMAGE_ROLE,
                model=self.description_model,
                retry_backoff=self.image_retry_backoff,
            )
        except PageUnreadable as error:
            return DescribedImage(
                request.index, None, "needs_review", ("model_error",), error=str(error)
            )
        except ProjectDomainError as error:
            if not error.code.startswith("run_budget"):
                raise
            # Предел запуска исчерпан на описаниях: текст страниц важнее,
            # поэтому разбор идёт дальше, а изображения остаются без описания
            # и попадут в «Описать изображения» готового материала.
            log.warning("описания изображений остановлены пределом запуска: %s", error)
            self._images_stopped = True
            return DescribedImage(request.index, None, "unreviewed", (BUDGET_REASON,))
        return replace(
            validate_description(answer.value, request.index),
            run_id=str(answer.run_id),
            model_id=answer.actual_model_id or answer.requested_model_id,
        )

    @staticmethod
    def _image_parts(request: ImageRequest) -> list[AiTextPart | AiImagePart]:
        """Инструкция, страница, подпись и соседний текст, затем сам вырез."""
        lines = [f"Страница {request.page_number}."]
        if request.caption:
            lines.append(f"Подпись рядом с изображением: «{request.caption}».")
        if request.context:
            lines.append(f"Соседний текст (только для ориентира): «{request.context}».")
        return [
            AiTextPart(text=IMAGE_INSTRUCTION),
            AiTextPart(text="\n".join(lines)),
            AiImagePart(image_url=AiImageUrl(url=_data_url(request.image, request.media_type))),
        ]

    def _run[R](self, work: Coroutine[Any, Any, R]) -> R:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(work)

    def _gather[R](
        self, works: Sequence[Coroutine[Any, Any, R]]
    ) -> list[R | BaseException]:
        """Выполнить вызовы одновременно; исключение каждого — на его месте в ответе.

        Сессия БД одна на все вызовы, и это безопасно: работа с ней синхронная и
        идёт между точками ожидания сети, так что два вызова в ней не
        пересекаются. Одновременность ограничена `concurrency`.
        """

        async def everything() -> list[R | BaseException]:
            return await asyncio.gather(*works, return_exceptions=True)

        if not works:
            return []
        return self._run(everything())

    async def _ask_async[T: BaseModel](
        self,
        parts: list[AiTextPart | AiImagePart],
        response_model: type[T],
        page_number: int,
        *,
        role: str,
        model: AiModelSelection | None,
        retry_backoff: Sequence[float] | None = None,
    ) -> AiResult[T]:
        """Один вызов шлюза.

        `confirmed=True` не обходит лимиты: дневной и разовый потолок стоимости
        проверяются всё равно, а предел запуска — через `budget`. Он значит
        только, что подтверждать каждую страницу отдельно некому — пользователь
        подтвердил запуск целиком, когда выбрал режим «Облако» и увидел оценку.
        Исчерпанный предел запуска (`ProjectDomainError`) пробрасывается как есть:
        следующий вызов упёрся бы в него же.
        """
        request = AiTextRequest(
            role=role,
            messages=[AiMessage(role="user", content=parts)],
            response_model=response_model,
            source_fingerprint={"page": page_number},
            request_model_override=model,
            confirmed=True,
            budget_context=self.budget,
        )
        if self._slots is None:
            self._slots = asyncio.Semaphore(max(1, self.concurrency))
        backoff = self.retry_backoff if retry_backoff is None else retry_backoff
        try:
            async with self._slots:
                result = await ModelGateway(self.session, self.transport, backoff).complete(
                    request
                )
        except AiGatewayError as error:
            self._failures += 1
            if error.code not in SURVIVABLE_CODES or self._failures >= MAX_CONSECUTIVE_FAILURES:
                raise
            log.warning(
                "страница %s не прочитана моделью (%s), разбор продолжается: %s",
                page_number,
                error.code,
                error,
            )
            raise PageUnreadable(str(error)) from error
        self._failures = 0
        return result

    def _page(
        self,
        answer: CloudPage,
        page_number: int,
        width: float,
        height: float,
        pixels: tuple[float, float] = (0.0, 0.0),
    ) -> ParsedPage:
        """Собрать нашу страницу из ответа модели, проверив всё, что можно проверить.

        :param width: ширина страницы в единицах документа (пункты PDF).
        :param pixels: размер присланного растра — по нему приводятся к долям
            координаты, которые модель вернула в пикселях.
        """
        elements: list[ParsedElement] = []
        diagnostics: list[str] = []
        broken_boxes = 0
        for index, item in enumerate(answer.elements):
            text = wrap_bare_latex(item.text.strip())
            if not text:
                continue
            bbox = _clamped_bbox(item.bbox, *pixels)
            reliable = bbox is not None
            if bbox is None:
                broken_boxes += 1
                bbox = _fallback_bbox(index, len(answer.elements))
            issues = latex_issues(text)
            diagnostics.extend(issues)
            elements.append(
                ParsedElement(
                    PAGE_KINDS.get(item.kind, "paragraph"),
                    text,
                    bbox,
                    item.level,
                    _confidence(item.confidence, text, issues),
                    recognition_source="vl",
                    bbox_reliable=reliable,
                )
            )
        if broken_boxes:
            diagnostics.append(f"bbox_missing:{broken_boxes}")
            log.warning(
                "модель вернула %s элементов без координат на странице %s",
                broken_boxes,
                page_number,
            )
        reported = [
            item.confidence for item in elements if item.confidence is not None
        ]
        confidence = min([answer.page_confidence, *reported])
        quality = "ocr" if confidence >= self.quality_threshold and not diagnostics else "ocr_low"
        return ParsedPage(
            page_number,
            width,
            height,
            _markdown(elements),
            "\n".join(item.text for item in elements if item.kind != "image"),
            quality,
            tuple(elements),
            tuple(dict.fromkeys(diagnostics)),
            confidence,
        )


def validate_description(answer: CloudImageDescription, index: int) -> DescribedImage:
    """Проверить ответ про вырез и решить, что с ним делать.

    Ответ, прошедший схему, всё равно может быть непригоден: пустой, с обрезанной
    рамкой, с таблицей без разделителя или формулой, которую KaTeX не соберёт.
    Такое сохраняется со статусом «требует проверки», а не выдаётся за знание;
    пустой ответ не сохраняется вовсе.
    """
    title = answer.title.strip()
    summary = answer.summary.strip()
    if not title and not summary:
        return DescribedImage(index, None, "needs_review", ("empty_answer",), error="empty")
    reasons: list[str] = []
    if len(summary) < MIN_SUMMARY_CHARS:
        reasons.append("summary_short")
    if answer.crop_issue != "none":
        reasons.extend(("crop_suspect", f"crop_{answer.crop_issue}"))
    table = answer.table_markdown.strip()
    if table and not TABLE_SEPARATOR_RE.search(table):
        reasons.append("table_invalid")
    latex = answer.latex.strip().strip("$").strip()
    if latex and latex_issues(f"$${latex}$$"):
        reasons.append("latex_invalid")
    if answer.unreadable or UNREADABLE_MARK in summary:
        reasons.append("unreadable_parts")
    if answer.confidence < IMAGE_REVIEW_CONFIDENCE:
        reasons.append("low_confidence")
    description = ImageDescription(
        kind=answer.kind,
        title=title,
        summary=summary,
        objects=_clean(answer.visible_objects),
        relations=_clean(answer.relations),
        labels=_clean(answer.labels),
        unreadable=_clean(answer.unreadable),
        details=_clean(answer.details),
        table_markdown="" if "table_invalid" in reasons else table,
        latex="" if "latex_invalid" in reasons else latex,
        context_note=answer.context_note.strip(),
        confidence=answer.confidence,
    )
    return DescribedImage(
        index,
        description,
        "needs_review" if reasons else "unreviewed",
        tuple(reasons),
        ROLE_HINTS.get(answer.content_role),
    )


def _clean(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(item.strip() for item in items if item.strip())


def _reused(known: DescribedImage, request: ImageRequest) -> DescribedImage:
    """Видимые факты повтора без вызова; контекст — собственная подпись вхождения."""
    description = known.description
    if description is not None:
        note = f"Подпись: {request.caption}" if request.caption else ""
        description = replace(description, context_note=note)
    return replace(
        known,
        index=request.index,
        description=description,
        reasons=tuple(dict.fromkeys((*known.reasons, "reused_by_hash"))),
    )


def _unreadable_page(
    page_number: int, width: float, height: float, reason: str
) -> ParsedPage:
    """Страница, которую модель не прочитала, — но материал всё равно собран.

    Пустой текст и `ocr_low` вместо исключения: разбор шестидесяти страниц не
    должен пропадать целиком из-за одного ответа, который не разобрать. Страница
    попадает в «нужно проверить», причина уходит в диагностику, и перезапустить
    её можно диапазоном, не трогая остальные.
    """
    return ParsedPage(
        page_number,
        width,
        height,
        "",
        "",
        "ocr_low",
        (),
        ("cloud_page_unreadable", f"cloud_error:{reason[:120]}"),
        0.0,
    )


def _confidence(reported: float, text: str, issues: Sequence[str]) -> float:
    """Уверенность элемента с поправкой на то, что видно в самом тексте."""
    if issues or UNREADABLE_MARK in text:
        return min(reported, SUSPECT_CONFIDENCE)
    return reported


def _markdown(elements: Sequence[ParsedElement]) -> str:
    lines: list[str] = []
    for element in elements:
        if element.kind == "heading":
            lines.append(f"{'#' * (element.level or 2)} {element.text}")
        elif element.kind == "list":
            lines.append(f"{'    ' * ((element.level or 1) - 1)}{element.text}")
        else:
            lines.append(element.text)
    return "\n\n".join(lines)
