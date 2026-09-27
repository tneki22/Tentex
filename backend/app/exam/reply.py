"""Подготовка обычного ответа чата: контекст, бюджет, запрос к модели и оценка.

Подготовка ничего не пишет в базу. Роутер сначала готовит ход, при нужде
возвращает оценку на подтверждение и только потом записывает реплику
пользователя и открывает поток — поэтому отказ до потока не оставляет в
ленте вопроса без ответа, а подтверждение привязано к `request_hash`
именно того запроса, который уйдёт модели.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.schemas import AiMessage, AiModelSelection, AiPreflight
from app.ai.settings import resolve_model
from app.exam import sources as chat_sources
from app.exam.context import ChatContext, build_context
from app.exam.prompts import build_chat_reply_prompt
from app.models import (
    ChatMessage,
    ChatMessageRole,
    ChatMode,
    ChatPayloadKind,
    ChatSession,
    ChatStreamState,
)
from app.projects.errors import ProjectDomainError
from app.retrieval.chunking import count_tokens

ROLE = "exam_chat_reply"
#: Предел входа по умолчанию и доля источников в нём. Считаются локальной
#: оценкой `count_tokens` — той же, что у поиска: оценка шлюза (байты/3) для
#: русского текста завышена примерно вдвое и занижала бы контекст.
DEFAULT_BUDGET_TOKENS = 12_000
SOURCES_SHARE = 0.5
#: Меньше этого источнику нет смысла оставаться даже обрезанным.
MIN_TRUNCATED_TOKENS = 120


@dataclass(frozen=True)
class TurnOptions:
    """Что пользователь попросил в этом ходе. Повтор хода берёт их из снимка реплики."""

    text: str
    operation: str = "discuss"
    scope: str = "topic_project"
    material_ids: list[UUID] = field(default_factory=list)
    knowledge_policy: str = "sources_only"

    def snapshot(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "scope": self.scope,
            "material_ids": [str(item) for item in self.material_ids],
            "knowledge_policy": self.knowledge_policy,
        }

    @classmethod
    def from_message(cls, message: ChatMessage, fallback: TurnOptions) -> TurnOptions:
        turn = (message.context_snapshot or {}).get("turn")
        if not isinstance(turn, dict):
            return fallback
        return cls(
            text=message.text,
            operation=str(turn.get("operation", fallback.operation)),
            scope=str(turn.get("scope", fallback.scope)),
            material_ids=[UUID(item) for item in turn.get("material_ids", [])],
            knowledge_policy=str(turn.get("knowledge_policy", fallback.knowledge_policy)),
        )


@dataclass(frozen=True)
class ReplyBudget:
    limit: int
    #: Предел, при котором ничего не сокращается.
    needed: int
    #: Потолок предела по окну модели; None — окно неизвестно.
    maximum: int | None

    @property
    def over(self) -> bool:
        return self.needed > self.limit


@dataclass(frozen=True)
class PreparedReply:
    request: AiTextRequest[Any]
    preflight: AiPreflight
    budget: ReplyBudget
    sources: list[dict[str, Any]]
    manifest: list[dict[str, Any]]
    reasons: list[str]
    user_snapshot: dict[str, Any]


@dataclass
class _Item:
    """Одна часть контекста в очереди бюджета."""

    kind: str
    title: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)
    included: bool = False
    truncated: bool = False
    reason: str | None = None
    tokens: int = 0
    #: Размер до сокращения — из него считается предел «без сокращений».
    full_tokens: int = 0

    def __post_init__(self) -> None:
        self.tokens = self.full_tokens = count_tokens(self.text)


def _history_pairs(tail: list[ChatMessage]) -> list[tuple[ChatMessage, ChatMessage]]:
    """Завершённые пары «вопрос — ответ»: служебное, пустое и неудачное не идёт."""
    pairs: list[tuple[ChatMessage, ChatMessage]] = []
    pending: ChatMessage | None = None
    for message in tail:
        plain = message.payload_kind == ChatPayloadKind.NONE and bool(message.text.strip())
        if message.role == ChatMessageRole.USER:
            pending = message if plain else None
        elif message.role == ChatMessageRole.EXAMINER:
            if plain and pending and message.stream_state == ChatStreamState.COMPLETE:
                pairs.append((pending, message))
            pending = None
    return pairs


def _source_block(source: dict[str, Any]) -> str:
    also_in = source.get("also_in") or []
    # Тот же текст в других материалах — одно место: модель узнаёт, что
    # источники здесь совпадают, а не видит два одинаковых S-ID.
    also = f' also_in="{"; ".join(also_in)}"' if also_in else ""
    stale = ' version="old"' if source.get("stale") else ""
    return (
        f'<retrieval_source id="{source["id"]}" material="{source["material"]}" '
        f'locator="{source["locator"]}"{also}{stale}>\n{source["text"]}\n</retrieval_source>'
    )


def _truncate(text: str, tokens: int) -> str:
    """Обрезать текст примерно до `tokens` по оценке `count_tokens`."""
    total = count_tokens(text)
    if total <= tokens:
        return text
    return text[: max(1, len(text) * tokens // total)].rstrip() + " …"


def _allocate(items: list[_Item], remaining: int, *, cap: int | None = None) -> int:
    """Включить части по порядку, пока хватает места. Первую не влезшую часть
    группы обрезать, а не пропускать: это самое релевантное место."""
    budget = remaining if cap is None else min(remaining, cap)
    used = 0
    for item in items:
        if item.tokens <= budget - used:
            item.included = True
            used += item.tokens
            continue
        left = budget - used
        if used == 0 and left >= MIN_TRUNCATED_TOKENS:
            item.text = _truncate(item.text, left)
            item.tokens = count_tokens(item.text)
            item.included = item.truncated = True
            used += item.tokens
            continue
        item.reason = "budget"
    return used


def _model_window(session: Session, override: AiModelSelection | None) -> int | None:
    try:
        return resolve_model(session, ROLE, override).model.context_length
    except ProjectDomainError:
        return None


def _override(chat: ChatSession) -> AiModelSelection | None:
    if not chat.model_override:
        return None
    return AiModelSelection(
        provider_id=chat.model_override["provider_id"],
        model_id=chat.model_override["model_id"],
    )


def _history_messages_all(session: Session, chat: ChatSession) -> list[ChatMessage]:
    return list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat.id)
            .order_by(ChatMessage.sequence)
        )
    )


@dataclass
class _Parts:
    """Части контекста по приоритету бюджета: эталон → свидетельства → история → профиль."""

    reference: list[_Item]
    evidence: list[_Item]
    history: list[_Item]
    profile: list[_Item]

    @property
    def all(self) -> list[_Item]:
        return [*self.reference, *self.evidence, *self.history, *self.profile]

    def allocate(self, limit: int, fixed_tokens: int) -> int:
        """Разложить предел и вернуть предел, при котором ничего не сокращается."""
        remaining = max(limit - fixed_tokens, 0)
        remaining -= _allocate(self.reference, remaining)
        remaining -= _allocate(self.evidence, remaining, cap=int(limit * SOURCES_SHARE))
        remaining -= _allocate(self.history, remaining)
        _allocate(self.profile, remaining)
        evidence_full = sum(item.full_tokens for item in self.evidence)
        return max(
            fixed_tokens + sum(item.full_tokens for item in self.all),
            math.ceil(evidence_full / SOURCES_SHARE),
        )


async def _find_sources(
    session: Session,
    chat: ChatSession,
    options: TurnOptions,
    tail: list[ChatMessage],
    earlier: list[ChatMessage],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Места из поиска со стабильными S-ID плюс источники, о которых спросили по номеру."""
    found = await chat_sources.find_sources(
        session,
        project_id=chat.project_id,
        node_id=chat.program_node_id,
        text=options.text,
        tail=tail,
        scope=options.scope,
        material_ids=options.material_ids,
        operation=options.operation,
    )
    ids = chat_sources.SourceIds.from_history(earlier)
    entries = ids.assign(found.entries)
    return entries + ids.mentioned(session, options.text, entries), found.notes


def _collect_parts(
    ctx: ChatContext, sources: list[dict[str, Any]], tail: list[ChatMessage]
) -> _Parts:
    # Привязанный фрагмент, который уже лежит внутри найденного места, второй
    # раз не передаётся: одно и то же место не должно занимать бюджет дважды.
    covered = {item for source in sources for item in source.get("fragment_ids", [])}
    evidence = [
        _Item(
            "fragment",
            f"{fragment.material_name}, стр. {fragment.page_number}",
            fragment.text,
            {"material": fragment.material_name, "page": fragment.page_number},
        )
        for fragment in ctx.fragments
        if str(fragment.fragment_id) not in covered
    ] + [
        _Item("retrieval_source", f"{source['id']} · {source['material']}", source["text"], source)
        for source in sources
    ]
    # Новые пары первыми: при нехватке места уходит самая старая история.
    history = []
    for user, answer in reversed(_history_pairs(tail)):
        answer_text = chat_sources.legacy_citations(answer)
        history.append(
            _Item(
                "history_pair",
                "Реплика истории",
                f"{user.text}\n{answer_text}",
                {"user": user.text, "answer": answer_text},
            )
        )
    profile_text = json.dumps(ctx.profile, ensure_ascii=False) if ctx.profile else ""
    return _Parts(
        reference=(
            [_Item("reference_answer", "Эталон", ctx.reference_text)] if ctx.reference_text else []
        ),
        evidence=evidence,
        history=history,
        profile=[_Item("profile", "Профиль", profile_text)] if ctx.profile else [],
    )


def _build_messages(
    system: str, head: list[str], parts: _Parts, notes: list[str], text: str
) -> tuple[list[AiMessage], list[dict[str, Any]]]:
    """Сообщения модели и вошедшие источники.

    Порядок: система → история → данные хода → вопрос. История стоит перед
    меняющимися данными, чтобы её префикс кэшировался у провайдера.
    """
    grounding = list(head)
    if parts.profile and parts.profile[0].included:
        grounding.append(f"<profile_data>\n{parts.profile[0].text}\n</profile_data>")
    if parts.reference and parts.reference[0].included:
        grounding.append(f"<reference_data>\n{parts.reference[0].text}\n</reference_data>")
    sources: list[dict[str, Any]] = []
    for item in parts.evidence:
        if not item.included:
            continue
        if item.kind == "fragment":
            heading = f'material="{item.payload["material"]}" page="{item.payload["page"]}"'
            grounding.append(f"<fragment_data {heading}>\n{item.text}\n</fragment_data>")
        else:
            source = {**item.payload, "text": item.text, "truncated": item.truncated}
            sources.append(source)
            grounding.append(_source_block(source))
    grounding.extend(f"<retrieval_note>{note}</retrieval_note>" for note in notes)

    messages = [AiMessage(role="system", content=system)]
    for item in reversed([item for item in parts.history if item.included]):
        messages.append(AiMessage(role="user", content=item.payload["user"]))
        messages.append(AiMessage(role="assistant", content=item.payload["answer"]))
    messages.append(AiMessage(role="user", content="\n\n".join(grounding)))
    messages.append(AiMessage(role="user", content=text))
    return messages, sources


def _window_maximum(
    session: Session, request: AiTextRequest[Any], preflight: AiPreflight
) -> int | None:
    """Потолок предела по окну модели, в локальной оценке токенов.

    Окно — в токенах модели, предел — в `count_tokens`. Пересчёт по отношению
    двух оценок этого же запроса держит потолок с запасом.
    """
    window = _model_window(session, request.request_model_override)
    if not window:
        return None
    local = max(sum(count_tokens(str(m.content)) for m in request.messages), 1)
    ratio = local / max(preflight.estimated_input_tokens, 1)
    return max(int((window - preflight.estimated_output_tokens) * ratio), 0)


def _manifest(parts: _Parts, retrieval_off: bool) -> list[dict[str, Any]]:
    """Что вошло, что сокращено и что исключено — для окна подтверждения."""
    manifest = [
        {
            "kind": item.kind,
            "title": item.title,
            "tokens": item.tokens,
            "included": item.included,
            "truncated": item.truncated,
            "reason": item.reason,
        }
        for item in parts.all
    ]
    if retrieval_off:
        manifest.append({
            "kind": "retrieval_source", "title": "Поиск по материалам", "tokens": 0,
            "included": False, "truncated": False, "reason": "excluded_by_user",
        })
    return manifest


async def prepare_reply(
    session: Session,
    gateway: ModelGateway,
    chat: ChatSession,
    options: TurnOptions,
    *,
    budget_tokens: int | None = None,
    before_sequence: int | None = None,
) -> PreparedReply:
    """Собрать ход: контекст в пределе, источники со стабильными S-ID, оценку шлюза.

    `before_sequence` — повтор хода: история берётся только до его реплики,
    чтобы вопрос не попал в запрос дважды.
    """
    ctx: ChatContext = build_context(session, chat, for_judge=False)
    tail = [m for m in ctx.tail if before_sequence is None or m.sequence < before_sequence]
    limit = budget_tokens or chat.context_budget_tokens or DEFAULT_BUDGET_TOKENS
    study = chat.mode == ChatMode.STUDY
    retrieval_on = study and (chat.context_flags or {}).get("retrieval", True)

    sources: list[dict[str, Any]] = []
    notes: list[str] = []
    if retrieval_on:
        earlier = [
            m for m in _history_messages_all(session, chat)
            if before_sequence is None or m.sequence < before_sequence
        ]
        sources, notes = await _find_sources(session, chat, options, tail, earlier)

    system = build_chat_reply_prompt(
        chat.persona,
        chat.strictness,
        chat.mode,
        chat.model_parameters.get("max_output_tokens") if chat.model_parameters else None,
        options.operation,
    )
    policy = (
        "<knowledge_policy>Только переданные источники.</knowledge_policy>"
        if options.knowledge_policy == "sources_only"
        else "<knowledge_policy>Общие знания модели разрешены, но вынеси их в отдельный "
        "раздел «Дополнение модели» без фиктивных цитат.</knowledge_policy>"
    )
    head = [f"Вопрос: {ctx.question}", policy]
    fixed_tokens = sum(count_tokens(part) for part in [system, *head, options.text, *notes])
    parts = _collect_parts(ctx, sources, tail)
    needed = parts.allocate(limit, fixed_tokens)
    messages, included_sources = _build_messages(system, head, parts, notes, options.text)

    request: AiTextRequest[Any] = AiTextRequest(
        role=ROLE,
        messages=messages,
        project_id=chat.project_id,
        context_manifest=[
            *ctx.manifest,
            {"kind": "budget", "limit": limit, "needed": needed},
            *(
                {"kind": "retrieval_source", **{k: v for k, v in s.items() if k != "text"}}
                for s in included_sources
            ),
        ],
        request_model_override=_override(chat),
        parameters=chat.model_parameters or {},
        source_fingerprint={"chat_id": str(chat.id)},
    )
    preflight = await gateway.preflight(request)
    budget = ReplyBudget(
        limit=limit, needed=needed, maximum=_window_maximum(session, request, preflight)
    )
    reasons = list(preflight.confirmation_reasons) if preflight.confirmation_required else []
    if budget.over:
        reasons.append("context_over_budget")
    return PreparedReply(
        request=request,
        preflight=preflight,
        budget=budget,
        sources=included_sources,
        manifest=_manifest(parts, study and not retrieval_on),
        reasons=reasons,
        user_snapshot={**ctx.snapshot, "turn": options.snapshot()},
    )


def _money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


class ChatConfirmationRequired(ProjectDomainError):
    """Ход ждёт подтверждения: цена, большой контекст или сокращение по пределу.

    В `context` — всё для окна подтверждения: причины, оценка, предел и что
    сокращено; `expanded` — оценка того же хода без сокращений, если окно
    модели его вмещает.
    """

    def __init__(self, prepared: PreparedReply, expanded: PreparedReply | None) -> None:
        preflight = prepared.preflight
        super().__init__(
            "Перед отправкой нужно подтвердить стоимость или объём контекста",
            status=409,
            code="ai_confirmation_required",
            context={
                "request_hash": preflight.request_hash,
                "reasons": prepared.reasons,
                "model_id": preflight.model_id,
                "provider_label": preflight.provider_label,
                "estimated_input_tokens": preflight.estimated_input_tokens,
                "estimated_output_tokens": preflight.estimated_output_tokens,
                "estimated_cost_usd": _money(preflight.estimated_cost_usd),
                "estimated_cost_rub": _money(preflight.estimated_cost_rub),
                # Неверные ссылки исправляются одним повторным вызовом — худший
                # случай вдвое дороже, и это видно до отправки.
                "max_cost_usd": _money(
                    preflight.estimated_cost_usd * 2
                    if preflight.estimated_cost_usd is not None else None
                ),
                "max_cost_rub": _money(
                    preflight.estimated_cost_rub * 2
                    if preflight.estimated_cost_rub is not None else None
                ),
                "budget": {
                    "limit": prepared.budget.limit,
                    "needed": prepared.budget.needed,
                    "maximum": prepared.budget.maximum,
                },
                "manifest": [
                    item for item in prepared.manifest if item["truncated"] or not item["included"]
                ],
                "expanded": (
                    {
                        "request_hash": expanded.preflight.request_hash,
                        "budget_tokens": expanded.budget.limit,
                        "estimated_cost_usd": _money(expanded.preflight.estimated_cost_usd),
                        "estimated_cost_rub": _money(expanded.preflight.estimated_cost_rub),
                    }
                    if expanded is not None
                    else None
                ),
            },
        )
