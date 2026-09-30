"""Как известные embedding-модели ждут запрос и документ.

Модель обучена на определённой форме входа, и без неё вектор хуже: E5 без
`query:`/`passage:` и Qwen3-Embedding без инструкции в запросе заметно теряют
в поиске, а Qwen3 с mean pooling вместо last-token выдаёт почти случайный порядок.
Рецепт подставляется при создании профиля, если шаблоны не заданы вручную.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

DEFAULT_TEMPLATE = "{text}"

#: Инструкцию Qwen3 авторы советуют писать по-английски и для других языков.
QWEN3_QUERY_TEMPLATE = (
    "Instruct: Given a question or topic, retrieve passages from study materials "
    "that answer it\nQuery:{text}"
)
#: У E5-instruct тот же смысл инструкции, но после `Query:` стоит пробел.
E5_INSTRUCT_QUERY_TEMPLATE = (
    "Instruct: Given a question or topic, retrieve passages from study materials "
    "that answer it\nQuery: {text}"
)


@dataclass(frozen=True)
class EmbeddingRecipe:
    pooling: str
    query_template: str
    document_template: str


def model_recipe(model_id: str) -> EmbeddingRecipe | None:
    """Рецепт по идентификатору модели: HF `owner/name` или имя в LM Studio."""
    name = model_id.lower()
    if "qwen3-embedding" in name:
        return EmbeddingRecipe("last_token", QWEN3_QUERY_TEMPLATE, DEFAULT_TEMPLATE)
    if "e5" in name.replace("/", "-").split("-"):
        if "instruct" in name:
            return EmbeddingRecipe("mean", E5_INSTRUCT_QUERY_TEMPLATE, DEFAULT_TEMPLATE)
        return EmbeddingRecipe("mean", "query: {text}", "passage: {text}")
    if "bge-m3" in name:
        return EmbeddingRecipe("cls", DEFAULT_TEMPLATE, DEFAULT_TEMPLATE)
    return None


class ModelSupport(StrEnum):
    """Что Tentex знает о модели: будет ли с ней нормально работать поиск по смыслу."""

    #: Прогнана на контрольных запросах по настоящей Библиотеке.
    VERIFIED = "verified"
    #: Шаблоны и pooling известны из карточки модели, прогона на корпусе не было.
    RECIPE = "recipe"
    #: Рекомендована для коротких текстов; фактическое обрезание зависит от runtime.
    SHORT_WINDOW = "short_window"
    #: Reranker и прочие модели, которые не строят векторы.
    NOT_EMBEDDING = "not_embedding"
    UNKNOWN = "unknown"


#: Проверено 26.09.2026: 10 контрольных запросов, старая и новая нарезка.
_VERIFIED = ("multilingual-e5-base",)
#: Короткий режим SentenceTransformer; внутренний /embed читает лимит токенизатора.
_SHORT_WINDOW = ("minilm", "paraphrase-")


def model_support(model_id: str) -> ModelSupport:
    name = model_id.lower()
    if "rerank" in name:
        return ModelSupport.NOT_EMBEDDING
    if any(marker in name for marker in _VERIFIED):
        return ModelSupport.VERIFIED
    if any(marker in name for marker in _SHORT_WINDOW):
        return ModelSupport.SHORT_WINDOW
    if model_recipe(model_id) is not None:
        return ModelSupport.RECIPE
    return ModelSupport.UNKNOWN
