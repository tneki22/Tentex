"""Попытки, оценки и неизменяемая лесенка проверки экзаменационного ответа."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.schemas import AiUsage
from app.ai.settings import AiGatewayError
from app.exam import chat as chat_service
from app.exam.checking import CheckResult, RubricPoint, deterministic_check
from app.exam.context import ChatContext, build_context
from app.exam.judge import JudgeResult, judge_attempt
from app.models import (
    Attempt,
    AttemptOutcome,
    ChatMessage,
    ChatMessageRole,
    ChatPayloadKind,
    ChatSession,
    Grade,
    GradeMethod,
    ReferenceAnswer,
    utc_now,
)
from app.projects.errors import ProjectDomainError

AI_FALLBACK_CODES = {
    "ai_disabled",
    "ai_role_disabled",
    "ai_provider_unavailable",
    "ai_timeout",
    "ai_daily_limit",
}


@dataclass(frozen=True)
class AttemptWithGrade:
    attempt: Attempt
    grade: Grade | None


@dataclass(frozen=True)
class AnswerResult:
    attempt: Attempt
    grade: Grade
    messages: list[ChatMessage]


def _reference_revision(ctx: ChatContext) -> int | None:
    return next(
        (
            item.get("revision")
            for item in ctx.manifest
            if item.get("kind") == "reference_answer"
        ),
        None,
    )


def _context_snapshot(ctx: ChatContext) -> dict[str, Any]:
    """Полный снимок нужен повторной проверке, даже если эталон позже изменится."""
    return {
        **ctx.snapshot,
        "question": ctx.node.title,
        "reference_text": ctx.reference_text,
        "reference_revision": _reference_revision(ctx),
        "fragments": [
            {
                "fragment_id": str(fragment.fragment_id),
                "material_id": str(fragment.material_id),
                "material_name": fragment.material_name,
                "page_number": fragment.page_number,
                "text": fragment.text,
            }
            for fragment in ctx.fragments
        ],
        "manifest": ctx.manifest,
    }


def _point_payload(points: list[RubricPoint]) -> list[dict[str, Any]]:
    return [asdict(point) for point in points]


def _fallback_summary(result: CheckResult, error: AiGatewayError) -> str:
    reason = {
        "ai_disabled": "внешние модели выключены",
        "ai_role_disabled": "проверка ответа моделью выключена",
        "ai_provider_unavailable": "провайдер модели недоступен",
        "ai_timeout": "провайдер не ответил вовремя",
        "ai_daily_limit": "дневной лимит моделей исчерпан",
    }[error.code]
    return f"{result.summary}. Это предварительный разбор по терминам: {reason}."


def _verdict_payload(
    *,
    outcome: AttemptOutcome,
    method: GradeMethod | None,
    credited: list[RubricPoint],
    missed: list[RubricPoint],
    wrong: list[RubricPoint],
    summary: str,
    usage: AiUsage | None,
    cached: bool,
    actual_model_id: str | None,
) -> dict[str, Any]:
    return {
        "outcome": outcome.value,
        "method": method.value if method is not None else None,
        "credited": _point_payload(credited),
        "missed": _point_payload(missed),
        "wrong": _point_payload(wrong),
        "summary": summary,
        "usage": (
            usage.model_dump(mode="json")
            if usage is not None
            else {
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "provider_cached_tokens": 0,
                "actual_cost_usd": "0",
                "actual_cost_rub": "0",
            }
        ),
        "cached": cached,
        "actual_model_id": actual_model_id,
        "self_assessment": None,
    }


def _require_attempt(session: Session, project_id: UUID, attempt_id: UUID) -> Attempt:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.project_id != project_id:
        raise ProjectDomainError(
            "Попытка не найдена", status=404, code="attempt_not_found"
        )
    return attempt


def _answer_message(session: Session, attempt_id: UUID) -> ChatMessage | None:
    return session.scalar(
        select(ChatMessage).where(ChatMessage.attempt_id == attempt_id).limit(1)
    )


def _save_grade(
    session: Session,
    attempt: Attempt,
    *,
    outcome: AttemptOutcome,
    method: GradeMethod | None,
    credited: list[RubricPoint],
    missed: list[RubricPoint],
    wrong: list[RubricPoint],
    summary: str,
    ai_run_id: UUID | None = None,
    usage: AiUsage | None = None,
    cached: bool = False,
    actual_model_id: str | None = None,
) -> Grade:
    payload = _verdict_payload(
        outcome=outcome,
        method=method,
        credited=credited,
        missed=missed,
        wrong=wrong,
        summary=summary,
        usage=usage,
        cached=cached,
        actual_model_id=actual_model_id,
    )
    with session.begin():
        grade = Grade(
            attempt_id=attempt.id,
            outcome=outcome,
            method=method,
            credited_points=payload["credited"],
            missed_points=payload["missed"],
            wrong_points=payload["wrong"],
            summary=summary,
            ai_run_id=ai_run_id,
        )
        session.add(grade)
        answer_message = _answer_message(session, attempt.id)
        if answer_message is not None:
            chat = session.get(ChatSession, answer_message.session_id)
            assert chat is not None
            chat_service._append_message_row(
                session,
                chat,
                role=ChatMessageRole.EXAMINER,
                payload_kind=ChatPayloadKind.VERDICT,
                payload=payload,
                ai_run_id=ai_run_id,
                grade_attempt_id=attempt.id,
            )
        session.flush()
        session.refresh(grade)
    return grade


async def submit_answer(
    session: Session,
    gateway: ModelGateway,
    project_id: UUID,
    chat: ChatSession | UUID,
    text: str,
) -> AnswerResult:
    chat_id = chat.id if isinstance(chat, ChatSession) else chat
    with session.begin():
        chat_service._require_exam_project(session, project_id)
        chat_row = chat_service._require_session(session, project_id, chat_id)
        node = chat_service._require_chat_node(
            session, project_id, chat_row.program_node_id
        )
        ctx = build_context(session, chat_row, for_judge=True)
        source_only_answer = session.get(
            ReferenceAnswer, (project_id, chat_row.program_node_id)
        )
        if (
            source_only_answer is not None
            and source_only_answer.is_active
            and source_only_answer.source_material_id is not None
            and not source_only_answer.text.strip()
        ):
            raise ProjectDomainError(
                "Эталон находится только в изображении источника; текстовая проверка недоступна",
                status=409,
                code="textual_check_unavailable",
            )
        ordinal = (
            session.scalar(
                select(func.count(Attempt.id)).where(
                    Attempt.project_id == project_id,
                    Attempt.program_node_id == chat_row.program_node_id,
                )
            )
            or 0
        ) + 1
        snapshot = _context_snapshot(ctx)
        attempt = Attempt(
            project_id=project_id,
            program_node_id=chat_row.program_node_id,
            ordinal=ordinal,
            text=text,
            persona=chat_row.persona,
            strictness=chat_row.strictness,
            context_snapshot=snapshot,
        )
        session.add(attempt)
        session.flush()
        answer_message = chat_service._append_message_row(
            session,
            chat_row,
            role=ChatMessageRole.USER,
            payload_kind=ChatPayloadKind.ANSWER_FORM,
            payload={
                "question": node.title,
                "ordinal": ordinal,
                "submitted_at": utc_now().isoformat(),
                "text": text,
            },
            context_snapshot=snapshot,
            attempt_id=attempt.id,
        )
        session.refresh(attempt)

    grade = await check_attempt(session, gateway, project_id, attempt.id)
    with session.begin():
        verdict_message = session.scalar(
            select(ChatMessage).where(ChatMessage.grade_attempt_id == attempt.id).limit(1)
        )
    messages = [answer_message]
    if verdict_message is not None:
        messages.append(verdict_message)
    return AnswerResult(attempt=attempt, grade=grade, messages=messages)


async def check_attempt(
    session: Session,
    gateway: ModelGateway,
    project_id: UUID,
    attempt_id: UUID,
) -> Grade:
    with session.begin():
        chat_service._require_exam_project(session, project_id)
        attempt = _require_attempt(session, project_id, attempt_id)
        existing = session.get(Grade, attempt.id)
        if existing is not None:
            return existing
        snapshot = dict(attempt.context_snapshot)
        answer = attempt.text

    result = deterministic_check(
        answer,
        snapshot.get("reference_text"),
        str(snapshot.get("question", "")),
    )
    if result.decided:
        return _save_grade(
            session,
            attempt,
            outcome=result.outcome,
            method=result.method,
            credited=result.credited,
            missed=result.missed,
            wrong=result.wrong,
            summary=result.summary,
        )

    try:
        judged = await judge_attempt(gateway, attempt)
    except AiGatewayError as error:
        # Ошибки preflight оставляют только read-транзакцию. SessionLocal работает
        # с expire_on_commit=False, поэтому commit закрывает её, не делая ранее
        # загруженные project/chat объекты неожиданно expired для вызывающего кода.
        session.commit()
        if error.code not in AI_FALLBACK_CODES:
            raise
        return _save_grade(
            session,
            attempt,
            outcome=result.outcome,
            method=GradeMethod.KEY_TERMS,
            credited=result.credited,
            missed=result.missed,
            wrong=result.wrong,
            summary=_fallback_summary(result, error),
        )

    return _save_judged_grade(session, attempt, judged)


def _save_judged_grade(
    session: Session, attempt: Attempt, result: JudgeResult
) -> Grade:
    return _save_grade(
        session,
        attempt,
        outcome=result.outcome,
        method=GradeMethod.AI_JUDGE,
        credited=result.credited,
        missed=result.missed,
        wrong=result.wrong,
        summary=result.summary,
        ai_run_id=result.ai_run_id,
        usage=result.usage,
        cached=result.cached,
        actual_model_id=result.actual_model_id,
    )


def set_self_assessment(
    session: Session,
    project_id: UUID,
    attempt_id: UUID,
    outcome: AttemptOutcome,
) -> Grade:
    if outcome is AttemptOutcome.UNSCORED:
        raise ProjectDomainError(
            "Для самооценки выберите результат",
            status=422,
            code="self_assessment_unscored",
        )
    with session.begin():
        chat_service._require_exam_project(session, project_id)
        attempt = _require_attempt(session, project_id, attempt_id)
        grade = session.get(Grade, attempt.id)
        if grade is None:
            raise ProjectDomainError(
                "Сначала проверьте попытку",
                status=409,
                code="attempt_grade_missing",
            )
        grade.self_assessment = outcome
        if grade.outcome is AttemptOutcome.UNSCORED:
            grade.method = GradeMethod.SELF_ASSESSMENT
        verdict_message = session.scalar(
            select(ChatMessage).where(ChatMessage.grade_attempt_id == attempt.id).limit(1)
        )
        if verdict_message is not None:
            verdict_message.payload = {
                **verdict_message.payload,
                "method": grade.method.value if grade.method is not None else None,
                "self_assessment": outcome.value,
            }
        grade.updated_at = utc_now()
        session.flush()
        session.refresh(grade)
    return grade


def list_attempts(
    session: Session, project_id: UUID, node_id: UUID
) -> list[AttemptWithGrade]:
    chat_service._require_exam_project(session, project_id)
    chat_service._require_chat_node(session, project_id, node_id)
    rows = session.execute(
        select(Attempt, Grade)
        .outerjoin(Grade, Grade.attempt_id == Attempt.id)
        .where(
            Attempt.project_id == project_id,
            Attempt.program_node_id == node_id,
        )
        .order_by(Attempt.created_at.desc())
    )
    return [AttemptWithGrade(attempt, grade) for attempt, grade in rows]


def get_attempt(
    session: Session, project_id: UUID, attempt_id: UUID
) -> AttemptWithGrade:
    chat_service._require_exam_project(session, project_id)
    attempt = _require_attempt(session, project_id, attempt_id)
    return AttemptWithGrade(attempt, session.get(Grade, attempt.id))
