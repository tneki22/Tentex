"""Устная попытка: запись, расшифровка, метрики и сдача в экзаменационный чат."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import MAX_AUDIO_BYTES, ModelGateway
from app.ai.provider import TimedWord
from app.ai.settings import AiGatewayError
from app.config import settings
from app.db import project_write_transaction
from app.exam import attempts, chat
from app.models import ChatMessage, Grade, OralRecording, utc_now
from app.projects.errors import ProjectConflictError, ProjectDomainError

DRAFT_TTL = timedelta(hours=24)
PAUSE_SECONDS = 0.5
MAX_DURATION_MS = 300_000


def _audio_file(relative: str) -> Path:
    """Разрешать только относительные пути внутри хранилища установки."""
    root = settings.storage_dir.resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ProjectDomainError("Недопустимый путь записи", status=422, code="oral_audio_path")
    return path


def cleanup_expired(session: Session) -> int:
    """Удалить истёкшие черновики и аудио; текст сданных ответов сохранить."""
    now = utc_now()
    with session.begin():
        rows = list(session.scalars(select(OralRecording).where(
            OralRecording.audio_expires_at <= now,
            (OralRecording.audio_path.is_not(None)) | (OralRecording.attempt_id.is_(None)),
        )))
        paths = [row.audio_path for row in rows if row.audio_path]
        for row in rows:
            if row.attempt_id is None:
                session.delete(row)
            else:
                row.audio_path = None
    for relative in paths:
        _audio_file(relative).unlink(missing_ok=True)
    return len(rows)


def speech_metrics(words: tuple[TimedWord, ...], duration_ms: int) -> dict[str, object]:
    """Считать только показатели, для которых есть настоящие пословные метки."""
    metrics: dict[str, object] = {"duration_ms": duration_ms}
    if not words or duration_ms <= 0:
        return metrics
    ordered = sorted(words, key=lambda item: item.start)
    duration = duration_ms / 1000
    if ordered[0].start < 0 or ordered[-1].end > duration + 1:
        return metrics
    gaps = [
        max(0.0, next_word.start - word.end)
        for word, next_word in zip(ordered, ordered[1:], strict=False)
    ]
    pauses = [gap for gap in gaps if gap > PAUSE_SECONDS]
    spoken = sum(max(0.0, word.end - word.start) for word in ordered)
    span = max(ordered[-1].end - ordered[0].start, 0.001)
    metrics.update({
        "pace_wpm": round(len(ordered) * 60 / span),
        "time_to_first_word_ms": round(ordered[0].start * 1000),
        "pause_count": len(pauses),
        "pause_duration_ms": round(sum(pauses) * 1000),
        "silence_share": round(max(0.0, min(1.0, 1 - spoken / duration)), 3),
    })
    return metrics


def _recording(
    session: Session, project_id: UUID, chat_id: UUID, recording_id: UUID
) -> OralRecording:
    row = session.get(OralRecording, recording_id)
    if row is None or row.project_id != project_id or row.chat_id != chat_id:
        raise ProjectDomainError(
            "Устная запись не найдена", status=404, code="oral_recording_not_found"
        )
    return row


async def create_draft(
    session: Session, gateway: ModelGateway, project_id: UUID, chat_id: UUID,
    audio: bytes, audio_format: str, duration_ms: int,
) -> OralRecording:
    """Распознать запись один раз и сохранить черновик до исправления текста."""
    chat._require_exam_project(session, project_id)
    chat._require_session(session, project_id, chat_id)
    if not 0 < duration_ms <= MAX_DURATION_MS:
        raise ProjectDomainError(
            "Запись должна быть не длиннее пяти минут", status=422, code="oral_duration_invalid"
        )
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ProjectDomainError(
            "Запись пуста или слишком велика", status=413, code="oral_audio_size"
        )
    result = await gateway.transcribe(
        audio, audio_format, project_id=project_id, timestamps=True,
    )
    if not result.text:
        raise ProjectDomainError("Речь не распознана", status=422, code="oral_transcript_empty")
    recording_id = uuid4()
    relative = f"oral/{project_id}/{recording_id}.{audio_format}"
    path = _audio_file(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    try:
        with project_write_transaction(session, project_id):
            row = OralRecording(
                id=recording_id, project_id=project_id, chat_id=chat_id,
                audio_path=relative, audio_format=audio_format,
                audio_duration_ms=duration_ms, transcript=result.text,
                words=[
                    {"word": word.word, "start": word.start, "end": word.end}
                    for word in result.words
                ],
                metrics=speech_metrics(result.words, duration_ms),
                audio_expires_at=utc_now() + DRAFT_TTL,
            )
            session.add(row)
            session.flush()
        return row
    except Exception:
        path.unlink(missing_ok=True)
        raise


async def submit_draft(
    session: Session, gateway: ModelGateway, project_id: UUID, chat_id: UUID,
    recording_id: UUID, text: str, answer_mode: str | None,
) -> attempts.AnswerResult:
    """Сдать исправленный транскрипт один раз; ошибку судьи можно повторить."""
    with session.begin():
        row = _recording(session, project_id, chat_id, recording_id)
        if row.attempt_id is None and row.audio_expires_at <= utc_now():
            raise ProjectDomainError("Черновик устарел", status=410, code="oral_draft_expired")
        attempt_id = row.attempt_id
        duration_ms = row.audio_duration_ms
    if attempt_id is None:
        try:
            result = await attempts.submit_answer(
                session, gateway, project_id, chat_id, text,
                answer_mode=answer_mode, active_seconds=duration_ms // 1000,
                oral=True, oral_recording_id=recording_id, check_now=False,
            )
            attempt_id = result.attempt.id
        except ProjectConflictError as error:
            if error.code != "oral_recording_already_submitted":
                raise
            session.rollback()
            return await submit_draft(
                session, gateway, project_id, chat_id, recording_id, text, answer_mode
            )
    else:
        with session.begin():
            attempt = attempts._require_attempt(session, project_id, attempt_id)
            grade = session.get(Grade, attempt_id)
            messages = list(session.scalars(select(ChatMessage).where(
                (ChatMessage.attempt_id == attempt_id)
                | (ChatMessage.grade_attempt_id == attempt_id)
            ).order_by(ChatMessage.sequence)))
        result = attempts.AnswerResult(attempt=attempt, grade=grade, messages=messages)
    if result.grade is not None:
        return result
    try:
        grade = await attempts.check_attempt(session, gateway, project_id, attempt_id)
    except AiGatewayError:
        session.rollback()
        return result
    with session.begin():
        messages = list(session.scalars(select(ChatMessage).where(
            (ChatMessage.attempt_id == attempt_id)
            | (ChatMessage.grade_attempt_id == attempt_id)
        ).order_by(ChatMessage.sequence)))
    return attempts.AnswerResult(attempt=result.attempt, grade=grade, messages=messages)


def audio_path(session: Session, project_id: UUID, recording_id: UUID) -> Path:
    """Вернуть запись только своего проекта и до истечения срока."""
    with session.begin():
        row = session.get(OralRecording, recording_id)
        if row is None or row.project_id != project_id or row.audio_path is None:
            raise ProjectDomainError("Аудио недоступно", status=404, code="oral_audio_missing")
        if row.audio_expires_at <= utc_now():
            raise ProjectDomainError(
                "Срок хранения аудио истёк", status=410, code="oral_audio_expired"
            )
        path = _audio_file(row.audio_path)
    if not path.is_file():
        raise ProjectDomainError("Аудио недоступно", status=404, code="oral_audio_missing")
    return path
