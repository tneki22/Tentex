"""«Дополнить урок»: предложение модели к готовому уроку (FR-L2).

Модель видит урок блоками `B1…Bn` по порядку: у куска — метка `S*`, страницы и
текст абзацами с якорями `¶1…` (место разреза), у пояснения — оформление и
текст, у медиа — подпись. Длинный урок режется на порции; каждая порция получает
оглавление всего урока одной строкой на блок. Снимок урока замораживается в
задаче: операции сверяются с ним, а при применении — с уроком как он есть.
Результат — предложение в `checkpoint.result`, применяет его `proposals.apply`.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.job_budget import KEY as BUDGET_KEY
from app.ai.job_budget import JobBudget, budget_state, spent
from app.ai.schemas import AiMessage, AiModelSelection
from app.ai.settings import AiGatewayError, resolve_model
from app.background.schemas import BackgroundJobStartRead
from app.db import project_write_transaction
from app.lessons import ai_context
from app.lessons import refs as refs_module
from app.lessons.ai_prompts import EnrichReply, enrich_instructions
from app.lessons.ai_schemas import (
    LessonEnrichOrder,
    LessonEnrichPreflightRead,
    LessonEnrichWrite,
    LessonProposalOp,
    LessonProposalRead,
    LessonProposalSource,
)
from app.lessons.ai_steps import update_checkpoint
from app.lessons.ai_writer import labels_in_order, rewrite_citations
from app.lessons.service import (
    _require_lesson,
    _require_lessons_project,
    _require_revision,
    _source_name,
)
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Lesson,
    LessonBasis,
    LessonBlock,
    LessonBlockKind,
    LessonRefRole,
    LessonSourceRef,
    LessonTopic,
    Material,
    MaterialFragment,
    ProgramNode,
    Project,
    ProjectMaterial,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError
from app.retrieval.chunking import count_tokens

ROLE = "lesson_enrich"
SUBTYPE = "enrich"
PORTION_TOKENS = 6_000
MAX_PORTIONS = {"economy": 1, "full": 4}
OUTPUT_TOKENS = 4_000
#: Выбранный блок получает соседей по обе стороны — иначе вставке не за что держаться.
FOCUS_WINDOW = 2
TOC_WORDS = 12
CALLS_SLACK = 2
#: Операция и поле, где у неё текст: пустой текст предлагать нечего.
TEXT_OPS = {
    "insert_note": "body_md",
    "rewrite_note": "body_md",
    "rename_lesson": "text",
    "set_goal": "text",
}


# --- снимок урока ------------------------------------------------------------------------


def _source_view(session: Session, project_id: UUID, ref: LessonSourceRef) -> dict[str, Any]:
    material = session.get(Material, ref.material_id) if ref.material_id else None
    link = session.get(ProjectMaterial, (project_id, ref.material_id)) if material else None
    name = _source_name(material, link, ref.source_name_snapshot)
    view: dict[str, Any] = {
        "source_name": name, "page_from": ref.page_from, "page_to": ref.page_to,
        "anchors": {}, "text": "",
    }
    if material is None or link is None or ref.region_bbox is not None:
        view["text"] = "(кусок недоступен как текст — область страницы или материал убран)"
        return view
    order = refs_module.load_order(session, material, ref.page_from, ref.page_to)
    ids = refs_module.content_fragment_ids(order, refs_module.bounds_of(ref))
    texts = dict(session.execute(
        select(MaterialFragment.id, MaterialFragment.text).where(MaterialFragment.id.in_(ids))
    ).tuples().all()) if ids else {}
    lines = []
    for number, fragment_id in enumerate(ids, start=1):
        text = " ".join((texts.get(fragment_id) or "").split())
        if not text:
            continue
        anchor = f"¶{number}"
        view["anchors"][anchor] = str(fragment_id)
        lines.append(f"{anchor} {text}")
    view["text"] = "\n".join(lines) or "(текст не распознан)"
    return view


def lesson_view(session: Session, lesson: Lesson) -> list[dict[str, Any]]:
    """Блоки урока для модели: метки `B*`, у кусков — `S*` и якоря абзацев."""
    blocks = list(session.scalars(
        select(LessonBlock).where(LessonBlock.lesson_id == lesson.id)
        .order_by(LessonBlock.sort_order)
    ))
    view: list[dict[str, Any]] = []
    source_number = 0
    for index, block in enumerate(blocks, start=1):
        item: dict[str, Any] = {
            "label": f"B{index}", "block_id": str(block.id), "kind": block.kind.value,
            "variant": block.variant.value if block.variant else None,
        }
        if block.kind == LessonBlockKind.SOURCE:
            ref = session.scalar(select(LessonSourceRef).where(
                LessonSourceRef.block_id == block.id, LessonSourceRef.role == LessonRefRole.CONTENT,
            ))
            if ref is None:
                continue
            source_number += 1
            item.update(_source_view(session, lesson.project_id, ref), source=f"S{source_number}")
        elif block.kind == LessonBlockKind.MEDIA:
            item["text"] = f"(медиа) {block.body_md or ''}".strip()
        else:
            item["text"] = block.body_md or ""
        item["tokens"] = count_tokens(item["text"])
        view.append(item)
    return view


def _toc_line(item: dict[str, Any]) -> str:
    if item["kind"] == "source":
        pages = (f"стр. {item['page_from']}" if item["page_from"] == item["page_to"]
                 else f"стр. {item['page_from']}–{item['page_to']}")
        return f"{item['label']} · кусок {item['source']} · {item['source_name']} · {pages}"
    words = " ".join(item["text"].split()[:TOC_WORDS])
    kind = {"note": "пояснение", "media": "медиа", "activity": "задание"}[item["kind"]]
    variant = f" ({item['variant']})" if item.get("variant") else ""
    return f"{item['label']} · {kind}{variant} · {words}"


def _block_text(item: dict[str, Any]) -> str:
    if item["kind"] == "source":
        return (f"[{item['label']} · кусок {item['source']} · {item['source_name']}, "
                f"стр. {item['page_from']}–{item['page_to']}]\n{item['text']}")
    kind = {"note": "пояснение", "media": "медиа", "activity": "задание"}[item["kind"]]
    variant = f", оформление {item['variant']}" if item.get("variant") else ""
    return f"[{item['label']} · {kind}{variant}]\n{item['text']}"


def portions(view: list[dict[str, Any]], depth: str, focus: str | None) -> list[list[int]]:
    """Порции урока по бюджету; с выбранным блоком — одна порция вокруг него."""
    if focus is not None:
        position = next((i for i, item in enumerate(view) if item["block_id"] == focus), None)
        if position is None:
            raise ProjectDomainError("Блок урока не найден", status=404, code="not_found")
        start = max(0, position - FOCUS_WINDOW)
        return [list(range(start, min(len(view), position + FOCUS_WINDOW + 1)))]
    result: list[list[int]] = [[]]
    used = 0
    for index, item in enumerate(view):
        if result[-1] and used + item["tokens"] > PORTION_TOKENS:
            result.append([])
            used = 0
        result[-1].append(index)
        used += item["tokens"]
    return [portion for portion in result if portion][: MAX_PORTIONS[depth]]


# --- промпт -----------------------------------------------------------------------------


def _brief(session: Session, project: Project, lesson: Lesson, order: LessonEnrichOrder
           ) -> dict[str, Any]:
    node_id = session.scalar(
        select(LessonTopic.program_node_id).where(LessonTopic.lesson_id == lesson.id)
        .order_by(LessonTopic.sort_order).limit(1)
    )
    node = session.get(ProgramNode, node_id)
    assert node is not None
    template = (lesson.build_meta or {}).get("template")
    return ai_context.build_brief(
        session, project=project, node=node,
        order={
            "template": template, "level": None, "basis": order.basis.value,
            "minutes": lesson.duration_minutes, "wishes": order.request.strip(),
        },
        materials=[],
        material_state=ai_context.MaterialState("материал урока — его куски ниже"),
        use_conspect=False,
    )


def enrich_request(
    project_id: UUID, brief: dict[str, Any], view: list[dict[str, Any]], portion: list[int],
    order: LessonEnrichOrder, model: AiModelSelection | None, **context: Any,
) -> AiTextRequest[EnrichReply]:
    focus = next((view[i]["label"] for i in portion if view[i]["block_id"] == str(order.block_id)),
                 None) if order.block_id else None
    user = "\n\n".join([
        f"<brief>\n{ai_context.render_brief(brief, compact=True)}\n</brief>",
        "<toc>\n" + "\n".join(_toc_line(item) for item in view) + "\n</toc>",
        "<lesson>\n" + "\n\n".join(_block_text(view[i]) for i in portion) + "\n</lesson>",
        f"<request>\n{order.request.strip() or 'Дополни урок, где это нужно читателю.'}\n"
        "</request>",
        "Предложи изменения только для блоков из <lesson>.",
    ])
    labels = {view[i]["source"]: view[i] for i in portion if view[i]["kind"] == "source"}
    return AiTextRequest(
        role=ROLE,
        messages=[
            AiMessage(role="system", content=enrich_instructions(order.basis.value, focus)),
            AiMessage(role="user", content=user),
        ],
        response_model=EnrichReply,
        project_id=project_id,
        context_manifest=[
            {"kind": "stage", "stage": "enrich"},
            {"kind": "brief", "sha256": hashlib.sha256(
                ai_context.render_brief(brief, compact=True).encode()).hexdigest()},
            *({"kind": "lesson_block", "id": view[i]["label"], "block_id": view[i]["block_id"]}
              for i in portion),
            *({"kind": "lesson_source", "id": label, "block_id": item["block_id"]}
              for label, item in labels.items()),
        ],
        request_model_override=model,
        confirmed=True,
        parameters={"max_output_tokens": OUTPUT_TOKENS},
        **context,
    )


# --- оценка и постановка ------------------------------------------------------------------


async def preflight(
    session: Session, project_id: UUID, lesson_id: UUID, order: LessonEnrichOrder
) -> LessonEnrichPreflightRead:
    project = _require_lessons_project(session, project_id, writable=False)
    lesson = _require_lesson(session, project_id, lesson_id)
    view = lesson_view(session, lesson)
    parts = portions(view, order.depth, str(order.block_id) if order.block_id else None)
    brief = _brief(session, project, lesson, order)
    try:
        resolved = resolve_model(session, ROLE, order.model)
        gateway = ModelGateway(session)
        estimates = [
            await gateway.preflight(enrich_request(project_id, brief, view, part, order,
                                                   order.model))
            for part in parts
        ]
    except AiGatewayError as error:
        return LessonEnrichPreflightRead(
            portions=len(parts), calls=len(parts), input_tokens=0, cost_usd=None,
            models_available=False, models_unavailable_reason=error.detail,
            model_label=None, price_known=False,
        )
    costs = [item.estimated_cost_usd for item in estimates]
    cost = None if any(item is None for item in costs) else sum(costs, Decimal(0))
    return LessonEnrichPreflightRead(
        portions=len(parts), calls=len(parts),
        input_tokens=sum(item.estimated_input_tokens for item in estimates),
        cost_usd=cost, models_available=True, models_unavailable_reason=None,
        model_label=resolved.model.display_name or resolved.model_id,
        price_known=cost is not None,
    )


async def start(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonEnrichWrite
) -> BackgroundJobStartRead:
    project = _require_lessons_project(session, project_id, writable=True)
    lesson = _require_lesson(session, project_id, lesson_id)
    _require_revision(lesson, command.expected_revision)
    view = lesson_view(session, lesson)
    if not view:
        raise ProjectConflictError("В уроке пока нечего дополнять", code="lesson_ai_empty")
    parts = portions(view, command.depth, str(command.block_id) if command.block_id else None)
    brief = _brief(session, project, lesson, command)
    resolved = resolve_model(session, ROLE, command.model)
    selection = command.model or AiModelSelection(
        provider_id=resolved.provider.id, model_id=resolved.model_id
    )
    gateway = ModelGateway(session)
    costs = [
        (await gateway.preflight(enrich_request(
            project_id, brief, view, part, command, selection))).estimated_cost_usd
        for part in parts
    ]
    cost = None if any(item is None for item in costs) else sum(costs, Decimal(0))
    if cost is None and not command.confirm_unknown_price:
        raise ProjectConflictError(
            "Цена модели неизвестна: подтвердите запуск без оценки стоимости",
            code="ai_price_unknown", context={"model_id": resolved.model_id},
        )
    node_id = session.scalar(
        select(LessonTopic.program_node_id).where(LessonTopic.lesson_id == lesson.id)
        .order_by(LessonTopic.sort_order).limit(1)
    )
    with project_write_transaction(session, project_id):
        job = BackgroundJob(
            kind=BackgroundJobKind.AI_LESSON, project_id=project_id,
            state=BackgroundJobState.QUEUED, done=0, total=len(parts),
            checkpoint={
                "subtype": SUBTYPE,
                "command": command.model_dump(mode="json"),
                "lesson_id": str(lesson.id),
                "program_node_id": str(node_id),
                "topic_title": lesson.title,
                "lesson_revision": lesson.revision,
                "view": view,
                "portions": parts,
                "brief": brief,
                "model": selection.model_dump(mode="json"),
                "model_label": resolved.model.display_name or resolved.model_id,
                BUDGET_KEY: budget_state(
                    max_cost_usd=command.max_cost_usd or cost,
                    max_calls=len(parts) + CALLS_SLACK,
                    allow_unknown_price=command.confirm_unknown_price,
                ),
            },
            diagnostics=[], pause_requested=False,
        )
        session.add(job)
        session.flush()
        return BackgroundJobStartRead(job_id=job.id)


# --- выполнение и проверка операций ------------------------------------------------------


def _checked_ops(reply: EnrichReply, view: list[dict[str, Any]], portion: list[int],
                 basis: LessonBasis, run_id: UUID | None,
                 dropped: list[str]) -> list[LessonProposalOp]:
    """Операции против снимка урока: чужой блок, чужой абзац и чужая метка отбрасываются."""
    by_label = {view[i]["label"]: view[i] for i in portion}
    sources = {item["source"]: item for item in by_label.values() if item["kind"] == "source"}
    result: list[LessonProposalOp] = []
    for op in reply.operations:
        target = by_label.get(op.block) if op.block else None
        problem = None
        if op.op in {"insert_note", "rewrite_note", "set_collapsed"} and target is None:
            problem = f"блока {op.block} нет в переданной части урока"
        elif op.op == "rewrite_note" and target["kind"] != "note":
            problem = f"{op.block} — не пояснение: куски модель не переписывает"
        elif op.op == "set_collapsed" and (target["kind"] != "source" or op.collapsed is None):
            problem = f"{op.block} — не кусок учебника"
        elif op.op in TEXT_OPS and not (getattr(op, TEXT_OPS[op.op]) or "").strip():
            problem = "пустой текст"
        after_fragment = None
        if problem is None and op.cut_after:
            anchors = target.get("anchors", {}) if target else {}
            ordered = list(anchors)
            if op.op != "insert_note" or op.cut_after not in anchors:
                problem = f"абзаца {op.cut_after} нет в {op.block}"
            elif op.cut_after != ordered[-1]:
                after_fragment = UUID(anchors[op.cut_after])
        if problem is not None:
            dropped.append(f"{op.op}: {problem}")
            continue
        body = op.body_md.strip() if op.body_md else None
        supports: list[str] = []
        if body is not None:
            found = labels_in_order(body)
            if basis == LessonBasis.MODEL_ONLY:
                body = rewrite_citations(body, {})
            else:
                unknown = [label for label in found if label not in sources]
                if unknown:
                    dropped.append("Ссылки вне переданных кусков убраны: " + ", ".join(unknown))
                body = rewrite_citations(body, {label: label for label in sources})
                supports = [label for label in found if label in sources]
        note_basis = (
            (basis if supports or basis == LessonBasis.MODEL_ONLY else LessonBasis.MODEL_ONLY)
            if body is not None else None
        )
        result.append(LessonProposalOp(
            id=uuid4().hex[:12], op=op.op,
            block_id=UUID(target["block_id"]) if target else None,
            after_fragment_id=after_fragment, variant=op.variant, body_md=body,
            supports=supports, basis=note_basis, collapsed=op.collapsed,
            text=op.text.strip() if op.text else None, reason=op.reason, run_id=run_id,
        ))
    return result


async def run(session: Session, gateway: ModelGateway, job_id: UUID) -> LessonProposalRead:
    job = session.get(BackgroundJob, job_id)
    assert job is not None and job.project_id is not None
    checkpoint = job.checkpoint
    command = LessonEnrichWrite.model_validate(checkpoint["command"])
    view = checkpoint["view"]
    parts = checkpoint["portions"]
    model = AiModelSelection.model_validate(checkpoint["model"])
    done: dict[str, dict] = dict(checkpoint.get("replies") or {})
    for index, part in enumerate(parts):
        if str(index) in done:
            continue
        result = await gateway.complete(enrich_request(
            job.project_id, checkpoint["brief"], view, part, command, model,
            job_id=job_id, budget_context=JobBudget(session, job_id),
        ))
        done[str(index)] = {**result.value.model_dump(mode="json"), "run_id": str(result.run_id)}
        update_checkpoint(session, job_id, replies=done, done=len(done))
    session.expire_all()
    job = session.get(BackgroundJob, job_id)
    assert job is not None
    dropped: list[str] = []
    ops: list[LessonProposalOp] = []
    summaries: list[str] = []
    for index, part in enumerate(parts):
        stored = dict(done[str(index)])
        run_id = UUID(stored.pop("run_id")) if stored.get("run_id") else None
        reply = EnrichReply.model_validate(stored)
        summaries.append(reply.summary)
        ops += _checked_ops(reply, view, part, command.basis, run_id, dropped)
    sources = [
        LessonProposalSource(
            label=item["source"], block_id=UUID(item["block_id"]),
            source_name=item["source_name"], page_from=item["page_from"],
            page_to=item["page_to"],
        )
        for item in view if item["kind"] == "source"
    ]
    return LessonProposalRead(
        lesson_id=UUID(checkpoint["lesson_id"]),
        program_node_id=UUID(checkpoint["program_node_id"]),
        lesson_revision=int(checkpoint["lesson_revision"]),
        summary=" ".join(item for item in summaries if item),
        basis=command.basis, ops=ops, sources=sources, dropped=dropped,
        cost_usd=spent(job.checkpoint.get(BUDGET_KEY) or {}),
    )
