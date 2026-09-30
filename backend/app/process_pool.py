"""Ленивый пул тяжёлых вычислений, освобождающий память после простоя.

Удаление Python-ссылок не выгружает нативные библиотеки OCR/PyTorch. Завершение
процесса возвращает и веса, и их аллокаторы; серия задач сохраняет прогрев.
"""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from threading import Lock, Timer, current_thread
from typing import Any

log = logging.getLogger("tentex.process_pool")


class IdleProcessPool:
    """Закрывать пул только после завершения всех задач и непрерывного простоя."""

    def __init__(
        self, *, idle_seconds: float, max_workers: int = 1,
        initializer: Callable[[], None] | None = None,
    ) -> None:
        self._idle_seconds = idle_seconds
        self._max_workers = max_workers
        self._initializer = initializer
        self._lock = Lock()
        self._executor: ProcessPoolExecutor | None = None
        self._timer: Timer | None = None
        self._pending = 0
        self._closed = False

    @property
    def loaded(self) -> bool:
        """Состояние без запуска процесса: healthcheck не продлевает прогрев."""
        with self._lock:
            return self._executor is not None

    def start(self) -> None:
        """Разрешить следующий lifespan приложения без запуска дочернего процесса."""
        with self._lock:
            self._closed = False

    def submit[T](self, operation: Callable[..., T], *args: Any) -> Future[T]:
        """Передать сериализуемый вызов; очередная задача отменяет таймер простоя."""
        # Аргументы разнородны: тип результата сохраняет Future[T].
        with self._lock:
            if self._closed:
                raise RuntimeError("process pool is closed")
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._executor is None:
                self._executor = self._create_executor()
            try:
                future = self._executor.submit(operation, *args)
            except BrokenProcessPool:
                # Не повторяем уже начатую работу: её Future передаст ошибку
                # владельцу. Следующая задача получает новый исправный процесс.
                log.warning("replacing crashed process pool before the next task")
                self._executor.shutdown(wait=False)
                self._executor = self._create_executor()
                future = self._executor.submit(operation, *args)
            self._pending += 1
        # Уже выполненный Future вызывает callback синхронно: вне self._lock.
        future.add_done_callback(self._finished)
        return future

    def _create_executor(self) -> ProcessPoolExecutor:
        return ProcessPoolExecutor(
            max_workers=self._max_workers, mp_context=get_context("spawn"),
            initializer=self._initializer,
        )

    def _finished(self, _: Future) -> None:
        with self._lock:
            self._pending -= 1
            if self._pending or self._closed or self._idle_seconds == 0:
                return
            timer = Timer(self._idle_seconds, self._expire)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def _expire(self) -> None:
        with self._lock:
            # Отменённый таймер может уже ждать lock. Проверяем его идентичность,
            # чтобы он не закрыл пул, прогретый более поздней задачей.
            if self._timer is not current_thread() or self._pending:
                return
            executor, self._executor = self._executor, None
            self._timer = None
        if executor is not None:
            executor.shutdown(wait=True)

    def close(self) -> None:
        """Дождаться принятых задач и закрыть дочерние процессы при остановке."""
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True)
