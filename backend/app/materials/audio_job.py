"""Разбор аудиоматериала в воркере: ход работы и чекпоинт по кускам записи.

У страницы PDF прогресс — «страниц 3 из 60», у записи страница одна, и такой
счётчик всю расшифровку простоял бы на нуле. Поэтому здесь `total` — минуты
записи, а `done` — сколько минут уже расшифровано; подпись «минут» задаёт
реестр фоновых задач.
"""

from __future__ import annotations

import math
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db import job_write_transaction, retry_on_locked
from app.materials.parsers.audio import TranscriptionCancelled, parse_audio
from app.materials.parsers.base import ParsedPage
from app.materials.parsers.cloud_asr import CloudTranscriber, transcribe_cloud
from app.models import BackgroundJob, BackgroundJobState, ParserMode, utc_now

# Не чаще: реплики локального Whisper приходят каждые несколько секунд, а каждая
# запись хода — это транзакция единственного писателя SQLite.
PROGRESS_INTERVAL_SECONDS = 3.0


class _Progress:
    """Пишет ход расшифровки в задачу и заодно узнаёт, что её отменили."""

    def __init__(self, session: Session, task_id: UUID) -> None:
        self.session = session
        self.task_id = task_id
        self._last = 0.0
        self._total_minutes = 0

    def __call__(self, done_seconds: float, total_seconds: float) -> bool:
        total = max(1, math.ceil(total_seconds / 60)) if total_seconds > 0 else 0
        # Первая запись и смена итога проходят сразу: без них строка задачи
        # остаётся на «страниц 0 из 1», пока не пройдёт первый интервал.
        now = time.monotonic()
        if total == self._total_minutes and now - self._last < PROGRESS_INTERVAL_SECONDS:
            return True
        self._last, self._total_minutes = now, total
        return retry_on_locked(lambda: self._write(done_seconds, total))

    def _write(self, done_seconds: float, total_minutes: int) -> bool:
        with job_write_transaction(self.session, self.task_id):
            task = self.session.get(BackgroundJob, self.task_id)
            # Задачи нет — её отменили из панели: расшифровку надо бросить.
            if task is None or task.state != BackgroundJobState.RUNNING:
                return False
            if total_minutes:
                task.total = total_minutes
                task.done = min(total_minutes, int(done_seconds // 60))
            now = utc_now()
            task.heartbeat_at = now
            task.updated_at = now
            return True


def _saved_chunks(session: Session, task_id: UUID) -> dict[int, dict[str, Any]]:
    task = session.get(BackgroundJob, task_id)
    # Значения снимаются до rollback: он истощает атрибуты, а следующая запись
    # должна начинаться с чистой транзакции (см. `process_parse_job`).
    stored = dict((task.checkpoint.get("audio") or {}).get("chunks", {})) if task else {}
    session.rollback()
    return {int(index): chunk for index, chunk in stored.items()}


def _save_chunk(session: Session, task_id: UUID, index: int, chunk: dict[str, Any]) -> None:
    def write() -> None:
        with job_write_transaction(session, task_id):
            task = session.get(BackgroundJob, task_id)
            if task is None:
                return
            audio = dict(task.checkpoint.get("audio") or {})
            audio["chunks"] = {**audio.get("chunks", {}), str(index): chunk}
            task.checkpoint = {**task.checkpoint, "audio": audio}

    retry_on_locked(write)


def transcribe_pages(
    session: Session, task_id: UUID, path: Path, mode: ParserMode | None
) -> Iterator[ParsedPage]:
    """Единственная страница транскрипта; ничего не отдаёт, если задачу отменили.

    Отмена — не ошибка: воркер после пустого итератора вызовет `_finish`, а тот
    молча уходит, когда задачи в реестре уже нет.
    """
    progress = _Progress(session, task_id)
    try:
        if mode == ParserMode.CLOUD:
            transcriber = CloudTranscriber(session)
            try:
                # Уборка не должна маскировать настоящую ошибку расшифровки: на Windows
                # отображённый в память файл держится до конца разбора трассы.
                with tempfile.TemporaryDirectory(
                    prefix="tentex-asr-", ignore_cleanup_errors=True
                ) as raw:
                    yield transcribe_cloud(
                        path,
                        transcriber,
                        Path(raw),
                        done=_saved_chunks(session, task_id),
                        save_chunk=lambda index, chunk: _save_chunk(session, task_id, index, chunk),
                        progress=progress,
                    )
            finally:
                transcriber.close()
        else:
            yield parse_audio(path, progress)
    except TranscriptionCancelled:
        return
