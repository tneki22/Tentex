"""Отбор внешних моделей, пригодных для распознавания страниц.

Каталог провайдера — это сотни моделей, из которых страницу учебника прочитают
единицы. Правило отбора должно жить в одном месте, потому что его задают три
разных вопроса: что показать в списке на экране «Распознавание», что пустить
в разбор и что ответить, когда выбранная модель не подошла.

Порядок отбора — от жёсткого к мягкому:

1. **Принимает изображение.** Единственное безусловное требование: без `image`
   во входных модальностях разговаривать не о чем.
2. **Умеет структурный ответ.** Разбор держится на JSON по схеме; без
   `response_format` модель отвечает прозой, и половина страниц теряется на
   разборе ответа. Пустой список параметров в каталоге — это «неизвестно», а не
   «не умеет»: у моделей, добавленных вручную, он всегда пуст.
3. **Хватает контекста и потолка ответа.** Страница в плитках — около полутора
   тысяч токенов на входе; плотная страница учебника с формулами — до двух
   тысяч на выходе.
4. **Цена за страницу.** Считается не по строчке прайса, а по фактическому
   расходу: столько-то плиток на входе, столько-то токенов на выходе. Разница
   между моделями получается в десятки раз, и видеть её надо до разбора.
5. **Прогон на бенчмарке.** Всё, что выше, только сужает список; какая модель
   действительно читает русскую математику, показывает `tentex-ocr-bench`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Типичная страница A4, снятая под распознавание: шесть плиток 768×768 плюс
# инструкция. Числа нужны, чтобы сравнивать модели между собой одной линейкой,
# поэтому они постоянные, а не измеряются по конкретному файлу.
PAGE_INPUT_TOKENS = 1850
# Плотная страница учебника с формулами и таблицей в Markdown.
PAGE_OUTPUT_TOKENS = 1300

# Контекста меньше не хватит на страницу вместе со схемой ответа.
MIN_CONTEXT_LENGTH = 32_000
# Потолок ответа ниже этого обрежет страницу на середине формулы.
MIN_OUTPUT_TOKENS = 4_000


@dataclass(frozen=True)
class CloudModelHint:
    """Модель, которую стоит попробовать первой, и чем именно она берёт."""

    model_id: str
    note: str


# Подсказки для списка на экране. Это не белый список: выбрать можно любую
# модель, принимающую картинки, — здесь только то, с чего разумно начать.
# Идентификаторы приведены как у OpenRouter; у прямого подключения к провайдеру
# они короче, поэтому сравнение идёт по вхождению, а не по равенству.
RECOMMENDED: tuple[CloudModelHint, ...] = (
    CloudModelHint(
        "qwen/qwen3.8-flash",
        "Дёшево и уверенно читает документы: разумный выбор по умолчанию.",
    ),
    CloudModelHint(
        "qwen/qwen3.7-flash",
        "Ещё дешевле предыдущей, качество ниже на плотных формулах.",
    ),
    CloudModelHint(
        "google/gemini-3.8-flash",
        "Лучше всех держит формулы и сложную вёрстку, но дороже остальных.",
    ),
    CloudModelHint(
        "qwen/qwen3-vl-30b-a3b-instruct",
        "Специализированная зрительная модель: сильна на таблицах и схемах.",
    ),
    CloudModelHint(
        "mistral-small-2603",
        "Работает и на бесплатном тарифе Mistral напрямую, без OpenRouter.",
    ),
    CloudModelHint(
        "dots-studio/dots-3-note-preview:free",
        "Бесплатная и заточена под разбор документов. Ограничена по числу запросов.",
    ),
)


@dataclass(frozen=True)
class CloudModelVerdict:
    """Годится ли модель для распознавания страниц и почему."""

    suitable: bool
    reason: str
    recommended_note: str
    price_per_page_usd: Decimal | None


def _recommendation(model_id: str) -> str:
    lowered = model_id.lower()
    for hint in RECOMMENDED:
        if hint.model_id in lowered or lowered.endswith(hint.model_id):
            return hint.note
    return ""


def price_per_page(
    prompt_price_usd: Decimal | None, completion_price_usd: Decimal | None
) -> Decimal | None:
    """Во что обойдётся одна страница у этой модели. `None` — цена неизвестна."""
    if prompt_price_usd is None or completion_price_usd is None:
        return None
    return prompt_price_usd * PAGE_INPUT_TOKENS + completion_price_usd * PAGE_OUTPUT_TOKENS


def verdict(
    *,
    model_id: str,
    input_modalities: list[str],
    supported_parameters: list[str],
    context_length: int | None,
    max_completion_tokens: int | None,
    prompt_price_usd: Decimal | None,
    completion_price_usd: Decimal | None,
) -> CloudModelVerdict:
    """Проверить модель по правилу отбора из шапки модуля.

    Возвращает решение вместе с причиной: она же показывается на экране рядом с
    моделью, поэтому формулируется для человека, а не для лога.
    """
    price = price_per_page(prompt_price_usd, completion_price_usd)
    note = _recommendation(model_id)
    if "image" not in input_modalities:
        return CloudModelVerdict(False, "Не принимает изображения", note, price)
    if supported_parameters and "response_format" not in supported_parameters:
        return CloudModelVerdict(False, "Не умеет отвечать по схеме", note, price)
    if context_length is not None and context_length < MIN_CONTEXT_LENGTH:
        return CloudModelVerdict(False, "Слишком короткий контекст для страницы", note, price)
    if max_completion_tokens is not None and max_completion_tokens < MIN_OUTPUT_TOKENS:
        return CloudModelVerdict(False, "Слишком низкий потолок ответа", note, price)
    return CloudModelVerdict(True, "", note, price)
