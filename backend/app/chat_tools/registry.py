"""Неизменяемый реестр Tools: контракт, доступность, но без бизнес-логики.

`ToolSpec.handler` — единственная точка, где Tool трогает данные; всё
остальное (проверка проекта/сессии/режима, подтверждение, журнал) общее и
живёт в `executor.py`. Заблокированные specs ниже не имеют `handler`:
`ToolExecutor` их не выполнит, что бы ни пришло в запросе (AI-CHATS.md §17.4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.chat_tools.schemas import MaterialSearchInput, MaterialSearchOutput
from app.models import ChatSession

ToolEffect = Literal["read", "write", "external"]
ToolConfirmation = Literal["never", "always"]


@dataclass(frozen=True)
class ToolContext:
    session: Session
    project_id: UUID
    chat: ChatSession


ToolHandler = Callable[[ToolContext, BaseModel], BaseModel]


@dataclass(frozen=True)
class ToolSpec:
    key: str
    title: str
    description: str
    modes: frozenset[str]
    effect: ToolEffect
    confirmation: ToolConfirmation
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    output_kind: str
    handler: ToolHandler | None = None
    available: bool = True
    unavailable_reason: str | None = None


def _handle_search_project_materials(ctx: ToolContext, value: BaseModel) -> BaseModel:
    # Отложенный импорт: bindings.service зависит от app.models так же, как и
    # мы, но подключать его на модульном уровне здесь незачем.
    from app.bindings.service import search_project_materials

    assert isinstance(value, MaterialSearchInput)
    node_id = value.node_id or ctx.chat.program_node_id
    hits = search_project_materials(
        ctx.session,
        ctx.project_id,
        value.query,
        node_id=node_id,
        limit=value.limit,
    )
    items = []
    for hit in hits[: value.limit]:
        if not hit.fragment_ids:
            continue
        items.append(
            {
                "fragment_id": hit.fragment_ids[0],
                "material_id": hit.material_id,
                "material_name": hit.material_name,
                "block_title": hit.block_title,
                "page_from": hit.page_from,
                "page_to": hit.page_to,
                "excerpt": hit.text[:400],
                "already_bound": hit.already_bound,
            }
        )
    return MaterialSearchOutput(items=items)


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.key: spec
    for spec in (
        ToolSpec(
            key="search_project_materials",
            title="Найти в материалах",
            description="Лексический поиск по уже обработанным материалам проекта (BM25).",
            modes=frozenset({"exam"}),
            effect="read",
            confirmation="never",
            input_model=MaterialSearchInput,
            output_model=MaterialSearchOutput,
            output_kind="material_search_results",
            handler=_handle_search_project_materials,
            available=True,
        ),
        # Будущие Tools публикуются без handler: ToolExecutor их не выполнит
        # ни при каком запросе (AI-CHATS.md §9.4/§17.4/§21.2) — только показывает
        # причину недоступности в палитре.
        ToolSpec(
            key="search_external_sources",
            title="Найти источники",
            description="Поиск статей, видео и публикаций во внешнем интернете.",
            modes=frozenset({"exam", "study"}),
            effect="external",
            confirmation="always",
            input_model=MaterialSearchInput,
            output_model=MaterialSearchOutput,
            output_kind="source_search_results",
            handler=None,
            available=False,
            unavailable_reason="tool_not_implemented",
        ),
        ToolSpec(
            key="import_found_source",
            title="Сохранить оригинал",
            description="Загрузить найденный источник в Материалы проекта.",
            modes=frozenset({"exam", "study"}),
            effect="write",
            confirmation="always",
            input_model=MaterialSearchInput,
            output_model=MaterialSearchOutput,
            output_kind="source_import_result",
            handler=None,
            available=False,
            unavailable_reason="tool_not_implemented",
        ),
        ToolSpec(
            key="summarize_found_source",
            title="Сделать сводку",
            description="Построить краткую сводку по уже сохранённому источнику.",
            modes=frozenset({"exam", "study"}),
            effect="external",
            confirmation="always",
            input_model=MaterialSearchInput,
            output_model=MaterialSearchOutput,
            output_kind="source_summary_result",
            handler=None,
            available=False,
            unavailable_reason="tool_not_implemented",
        ),
    )
}


def get_tool_spec(key: str) -> ToolSpec | None:
    return TOOL_SPECS.get(key)


def list_tool_specs() -> list[ToolSpec]:
    return list(TOOL_SPECS.values())
