"""Терминальные и промежуточные записи фоновых retrieval-задач.

Между стартом такой задачи и записью её результата проходят минуты: скачивание
модели, embeddings целого корпуса, map-reduce по материалу. За это время база
уходит вперёд, и SQLite отказывается повышать устаревший снимок соединения до
записи — `PRAGMA busy_timeout` этот отказ не покрывает. Поэтому каждая запись
здесь начинается с нового снимка, резервирует единственного писателя до чтения и
повторяется при отказе: иначе выполненная работа отмечается как провал, как это
случилось с установкой модели 20.09.2026.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.db import job_write_transaction, retry_on_locked
from app.models import BackgroundJob, BackgroundJobState, utc_now


def write_job[T](
    session: Session, job_id: UUID, apply: Callable[[Session, BackgroundJob], T]
) -> T | None:
    """Выполнить `apply` над задачей в собственной write-транзакции с ретраями.

    `apply` может читать и менять что угодно: транзакция уже резервирует
    писателя, а повтор начинается с чистого снимка, поэтому обращения внутри
    должны быть идемпотентными. Возвращает `None`, если задачи больше нет.
    """

    def operation() -> T | None:
        if session.in_transaction():
            session.rollback()
        with job_write_transaction(session, job_id):
            job = session.get(BackgroundJob, job_id)
            if job is None:
                return None
            return apply(session, job)

    return retry_on_locked(operation)


def finish(job: BackgroundJob, state: BackgroundJobState, *, error: str | None = None) -> None:
    """Проставить терминальные поля задачи и снять лиз."""
    job.state = state
    if error is not None:
        job.error = error
    if state == BackgroundJobState.COMPLETED:
        job.done = job.total
    job.completed_at = utc_now()
    job.lease_owner = None
    job.lease_expires_at = None
    job.updated_at = utc_now()
