"""Корзина «ждут проверки»: задача с предложением кончается не тогда, когда
модель замолчала, а когда человек посмотрел результат.

До этого завершённая задача просто исчезала из панели (там только активные), и
вернуться к готовому плану было неоткуда — приходилось звать модель заново и
платить за тот же вопрос второй раз.
"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app.db as db_module
from app.background import registry
from app.models import BackgroundJob, BackgroundJobKind, BackgroundJobState, utc_now
from app.projects.errors import ProjectConflictError


def _fail_session_begin_once(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Заставить первый `session.begin()` внутри реестра словить чужую блокировку."""
    monkeypatch.setattr(db_module.time, "sleep", lambda _: None)
    original_begin = session.begin
    calls = {"count": 0}

    def flaky_begin(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError("UPDATE background_jobs", {}, Exception("database is locked"))
        return original_begin(*args, **kwargs)

    monkeypatch.setattr(session, "begin", flaky_begin)


def _job(
    session: Session,
    kind: BackgroundJobKind,
    *,
    state: BackgroundJobState = BackgroundJobState.COMPLETED,
    result: bool = True,
) -> BackgroundJob:
    job = BackgroundJob(
        id=uuid4(),
        kind=kind,
        state=state,
        done=0,
        total=0,
        checkpoint={"result": {"rows": []}} if result else {},
        diagnostics=[],
        created_at=utc_now(),
        updated_at=utc_now(),
        completed_at=utc_now() if state == BackgroundJobState.COMPLETED else None,
    )
    session.add(job)
    session.commit()
    # Реестр в бою получает сессию, которая задачу ещё не читала: его первое
    # чтение открывает транзакцию само, и запись поверх неё когда-то падала.
    # Без этой строки тест шёл бы по объекту из памяти и той ошибки не видел.
    session.expunge_all()
    return job


def test_finished_proposal_waits_for_the_user(session: Session) -> None:
    job = _job(session, BackgroundJobKind.AI_ANSWER_SECTIONS)

    assert registry.get_job(session, job.id).needs_review is True
    assert [row.id for row in registry.list_jobs(session, pending_review=True)] == [job.id]


def test_self_applying_job_never_waits(session: Session) -> None:
    """`link_answers` применяет результат сам — подтверждать нечего."""
    job = _job(session, BackgroundJobKind.LINK_ANSWERS)

    assert registry.get_job(session, job.id).needs_review is False
    assert registry.list_jobs(session, pending_review=True) == []


def test_job_without_saved_result_is_not_offered(session: Session) -> None:
    """Звать в диалог, которому нечего показать, — хуже, чем молчать."""
    job = _job(session, BackgroundJobKind.AI_GROUPING, result=False)

    assert registry.get_job(session, job.id).needs_review is False
    assert registry.list_jobs(session, pending_review=True) == []


def test_both_filters_give_the_union_the_panel_shows(session: Session) -> None:
    running = _job(session, BackgroundJobKind.PARSE, state=BackgroundJobState.RUNNING)
    waiting = _job(session, BackgroundJobKind.AI_GROUPING)
    _job(session, BackgroundJobKind.AI_GROUPING, state=BackgroundJobState.CANCELLED)

    listed = {row.id for row in registry.list_jobs(session, active_only=True, pending_review=True)}
    assert listed == {running.id, waiting.id}


def test_failed_job_waits_in_attention_bucket_until_dismissed(session: Session) -> None:
    failed = _job(session, BackgroundJobKind.RETRIEVAL_INDEX, state=BackgroundJobState.FAILED)

    assert [row.id for row in registry.list_jobs(session, failed_only=True)] == [failed.id]

    dismissed = registry.resolve_job(session, failed.id)
    assert dismissed.reviewed_at is not None
    assert registry.list_jobs(session, failed_only=True) == []


def test_resolve_clears_the_bucket_and_repeats_harmlessly(session: Session) -> None:
    """Диалог применения и панель зовут `resolve` независимо друг от друга."""
    job = _job(session, BackgroundJobKind.AI_IMPORT_REPAIR)

    first = registry.resolve_job(session, job.id)
    assert first.needs_review is False
    assert first.reviewed_at is not None

    assert registry.resolve_job(session, job.id).reviewed_at == first.reviewed_at
    assert registry.list_jobs(session, pending_review=True) == []
    # Результат никуда не делся: отметка снимает напоминание, а не данные.
    assert registry.get_job_result(session, job.id) == {"rows": []}


def test_running_ai_job_is_cancelled_on_a_session_that_already_read_it(
    session: Session,
) -> None:
    """Отмена задачи ИИ: `session.begin()` поверх автоматически начатого
    чтения раньше валил запрос с `A transaction is already begun`."""
    job = _job(session, BackgroundJobKind.AI_GROUPING, state=BackgroundJobState.RUNNING)

    assert registry.cancel_job(session, job.id).pause_requested is True


def test_resolve_job_retries_past_a_transient_lock(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24.09.2026: чужая блокировка записи роняла `resolve_job` 500-й — теперь
    `retry_on_locked` берёт свежий снимок и пробует ещё раз."""
    job = _job(session, BackgroundJobKind.AI_GROUPING, state=BackgroundJobState.FAILED)
    _fail_session_begin_once(session, monkeypatch)

    resolved = registry.resolve_job(session, job.id)
    assert resolved.reviewed_at is not None


def test_cancel_job_retries_past_a_transient_lock(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session, BackgroundJobKind.AI_GROUPING, state=BackgroundJobState.QUEUED)
    _fail_session_begin_once(session, monkeypatch)

    cancelled = registry.cancel_job(session, job.id)
    assert cancelled.state == BackgroundJobState.CANCELLED


def test_resolve_rejects_unfinished_job(session: Session) -> None:
    job = _job(session, BackgroundJobKind.AI_GROUPING, state=BackgroundJobState.RUNNING)

    with pytest.raises(ProjectConflictError) as error:
        registry.resolve_job(session, job.id)
    assert error.value.code == "background_job_not_completed"
