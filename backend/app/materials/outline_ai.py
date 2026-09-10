"""Четвёртый источник оглавления — модель по явной кнопке (Работа 4.4 плана
мастера учебника). Вызывается только когда закладок, печатной страницы и
распознанных заголовков не хватило; сам по себе ничего не пишет в программу —
только предлагает список пунктов для проверки на шаге 3.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pymupdf as fitz
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.schemas import AiMessage, AiUsage
from app.materials import library
from app.materials.outline import MAX_LEADING_CANDIDATES, TRAILING_CANDIDATES
from app.materials.schemas import OutlineItem
from app.materials.storage import material_path

# Кандидатных страниц может набраться на весь учебник — ограничиваем
# суммарный текст, а не гоним в модель материал целиком.
MAX_PROMPT_CHARS = 24_000

SYSTEM_PROMPT = (
    "Ты восстанавливаешь структуру учебника по присланным страницам, когда "
    "закладок PDF и печатного оглавления не нашлось. Верни плоский список "
    "пунктов: level — глубина вложенности от 1 до 4, title — формулировка "
    "раздела или темы без номера страницы, page — номер страницы начала "
    "этого раздела в исходном документе. Не выдумывай пункты, которых нет "
    "на присланных страницах; порядок пунктов — как в тексте."
)


class OutlineModelSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OutlineItem]


class OutlineModelRunRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    items: list[OutlineItem]
    usage: AiUsage
    requested_model_id: str
    actual_model_id: str
    cached: bool


def _candidate_text(path: Path, page_count: int) -> str:
    with fitz.open(path) as document:
        total = min(page_count, document.page_count)
        leading = range(1, min(MAX_LEADING_CANDIDATES, total) + 1)
        trailing = range(max(1, total - TRAILING_CANDIDATES + 1), total + 1)
        pages = sorted({*leading, *trailing})
        budget = MAX_PROMPT_CHARS
        chunks: list[str] = []
        for page_number in pages:
            text = document[page_number - 1].get_text("text").strip()
            if not text:
                continue
            piece = f"\n--- страница {page_number} ---\n{text}"
            if len(piece) > budget:
                break
            chunks.append(piece)
            budget -= len(piece)
        return "".join(chunks)


async def run(
    session: Session, gateway: ModelGateway, project_id: UUID | None, material_id: UUID
) -> OutlineModelRunRead:
    material = library.material_or_404(session, material_id)
    text = _candidate_text(material_path(material.storage_path), material.page_count or 0)
    request = AiTextRequest(
        role="study_outline_extract",
        project_id=project_id,
        messages=[
            AiMessage(role="system", content=SYSTEM_PROMPT),
            AiMessage(role="user", content=f"<pages>\n{text}\n</pages>"),
        ],
        response_model=OutlineModelSuggestion,
        # Вызов явный (кнопка «Оглавление с ИИ»), вход ограничен MAX_PROMPT_CHARS —
        # отдельного экрана подтверждения стоимости для этого действия нет.
        confirmed=True,
    )
    result = await gateway.complete(request)
    return OutlineModelRunRead(
        run_id=result.run_id,
        items=result.value.items,
        usage=result.usage,
        requested_model_id=result.requested_model_id,
        actual_model_id=result.actual_model_id,
        cached=result.cached,
    )
