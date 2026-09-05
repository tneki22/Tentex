"""Вид источника: чем показывать материал и есть ли у него исходная страница.

Модуль вынесен из `materials.library` отдельно, потому что вид источника нужен
и поиску (`bindings.search`), а `library` сам импортирует `bindings` — прямая
ссылка замкнула бы импорт в кольцо. Здесь только модели и никаких сервисов.
"""

from typing import Literal

from app.models import Material, MaterialSourceKind

MaterialPresentationKind = Literal[
    "pdf", "image", "document", "plain_text", "web", "youtube", "audio"
]

DOCUMENT_MEDIA_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}

#: Виды, у которых есть растр страницы (`GET .../pages/{n}/image`). Остальным
#: этот эндпоинт отвечает 422 `page_image_unavailable`, и интерфейс должен знать
#: об этом заранее, а не выяснять провоцированием ошибки.
PAGE_IMAGE_KINDS: frozenset[MaterialPresentationKind] = frozenset({"pdf", "image"})


def presentation_kind(material: Material) -> MaterialPresentationKind:
    """Один производный вид вместо проверок MIME по всему фронтенду."""
    if material.source_kind == MaterialSourceKind.YOUTUBE:
        return "youtube"
    if material.source_kind == MaterialSourceKind.AUDIO or material.media_type.startswith("audio/"):
        return "audio"
    if material.source_kind == MaterialSourceKind.URL:
        return "web"
    if material.media_type == "application/pdf":
        return "pdf"
    if material.media_type.startswith("image/"):
        return "image"
    if material.media_type in DOCUMENT_MEDIA_TYPES:
        return "document"
    # Неизвестный формат сюда не доходит: загрузка отклоняет его в storage.
    return "plain_text"
