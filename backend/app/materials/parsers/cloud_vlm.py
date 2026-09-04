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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.provider import OpenAICompatibleTransport
from app.ai.schemas import AiImagePart, AiImageUrl, AiMessage, AiTextPart
from app.materials.parsers.base import (
    ElementKind,
    ParsedElement,
    ParsedPage,
    RecognizedRegion,
    RegionRequest,
)
from app.ocr.engines import DEFAULT_QUALITY_THRESHOLD

log = logging.getLogger("tentex.worker")

ROLE = "material_page_recognition"

# Сколько вырезов уходит одним запросом. Больше — ответ упирается в потолок
# токенов и обрывается на середине формулы, меньше — платим за инструкцию
# столько же раз, сколько на странице формул.
MAX_REGIONS_PER_REQUEST = 6

# Метка нечитаемого места: модель ставит её вместо догадки, а мы по ней
# опускаем уверенность элемента, даже если сама модель этого не сделала.
UNREADABLE_MARK = "⟨?⟩"
# Потолок уверенности для элемента с оговоркой: дальше страница уходит в
# «требует проверки», а не в готовый материал.
SUSPECT_CONFIDENCE = 0.4

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
3. Таблицы — в Markdown, в ячейке допустим LaTeX.
4. Порядок элементов — порядок чтения. Две колонки: сначала левая целиком, потом правая.
5. Колонтитул, номер страницы и маргиналия — отдельные элементы своего вида,
   не части соседнего абзаца.
6. Нечитаемое место передавай как ⟨?⟩ и ставь этому элементу confidence ниже 0.5.
7. bbox — доля от размера страницы: [x0, y0, x1, y1] в диапазоне 0..1,
   считая от левого верхнего угла."""

REGION_INSTRUCTION = """Тебе даны вырезы со страницы учебного документа.
Текст страницы уже прочитан, нужно прочитать только эти куски.
Верни JSON по схеме и ничего кроме него.

1. Формулу передавай в LaTeX без окружения: `\\int_a^b f(x)\\,dx = F(b) - F(a)`.
   Номер формулы, напечатанный рядом, ставь в \\tag{...}.
2. Таблицу передавай в Markdown, в ячейке допустим LaTeX.
3. График, схему или фотографию описывай одной фразой по-русски: что изображено.
4. Обычный текст переписывай дословно.
5. index в ответе — тот же, что и в подписи к вырезу; порядок ответов неважен.
6. Нечитаемое место передавай как ⟨?⟩ и ставь confidence ниже 0.5."""


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


def _data_url(image: bytes, media_type: str = "image/png") -> str:
    return f"data:{media_type};base64,{base64.b64encode(image).decode()}"


def _clamped_bbox(values: Sequence[float]) -> tuple[float, float, float, float] | None:
    """Координаты модели в наших пределах или `None`, если они бессмысленны."""
    if len(values) != 4:
        return None
    x0, y0, x1, y1 = (max(0.0, min(1.0, float(value))) for value in values)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


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
    # Один event loop на весь разбор материала, а не на каждый вызов модели.
    # `asyncio.run()` в `_ask` создавал и закрывал свой loop на каждой странице
    # и на каждой пачке вырезов; `AsyncOpenAI`-клиент внутри шлюза переживал
    # закрытие своего loop'а, и сборщик мусора пытался закрыть его соединения
    # уже на чужом (следующем) loop'е — воркер получал россыпь
    # `RuntimeError: Event loop is closed` в логе на каждом облачном разборе.
    _loop: asyncio.AbstractEventLoop | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def close(self) -> None:
        """Закрыть общий event loop. Без вызова он держит ресурсы до GC."""
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    def recognize_page(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        """Прочитать страницу целиком: разметка, порядок чтения и формулы."""
        answer = self._ask(
            [
                AiTextPart(text=PAGE_INSTRUCTION),
                AiImagePart(image_url=AiImageUrl(url=_data_url(image))),
            ],
            CloudPage,
            page_number,
        )
        return self._page(answer, page_number, width, height)

    def recognize_regions(
        self, regions: Sequence[RegionRequest], page_number: int
    ) -> list[RecognizedRegion]:
        """Прочитать вырезы страницы, не трогая уже готовый текстовый слой."""
        result: list[RecognizedRegion] = []
        for start in range(0, len(regions), MAX_REGIONS_PER_REQUEST):
            batch = regions[start : start + MAX_REGIONS_PER_REQUEST]
            answer = self._ask(self._region_parts(batch), CloudRegions, page_number)
            known = {region.index for region in batch}
            result.extend(
                RecognizedRegion(
                    index=item.index,
                    kind=REGION_KINDS.get(item.kind, "image"),
                    text=item.content,
                    confidence=item.confidence,
                )
                for item in answer.regions
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

    def _ask[T: BaseModel](
        self,
        parts: list[AiTextPart | AiImagePart],
        response_model: type[T],
        page_number: int,
    ) -> T:
        """Один вызов шлюза.

        `confirmed=True` не обходит лимиты: дневной и разовый потолок стоимости
        проверяются всё равно. Он значит только, что подтверждать каждую
        страницу отдельно некому — пользователь подтвердил разбор целиком,
        когда выбрал режим «Облако» и запустил обработку материала.
        """
        request = AiTextRequest(
            role=ROLE,
            messages=[AiMessage(role="user", content=parts)],
            response_model=response_model,
            source_fingerprint={"page": page_number},
            confirmed=True,
        )
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        result = self._loop.run_until_complete(
            ModelGateway(self.session, self.transport).complete(request)
        )
        return result.value

    def _page(
        self, answer: CloudPage, page_number: int, width: float, height: float
    ) -> ParsedPage:
        """Собрать нашу страницу из ответа модели, проверив всё, что можно проверить."""
        elements: list[ParsedElement] = []
        diagnostics: list[str] = []
        broken_boxes = 0
        for index, item in enumerate(answer.elements):
            text = wrap_bare_latex(item.text.strip())
            if not text:
                continue
            bbox = _clamped_bbox(item.bbox)
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
