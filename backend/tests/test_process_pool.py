"""Процессы переживают серию задач, освобождаются в простое и возвращаются по запросу."""

import operator
import os
import time
from concurrent.futures.process import BrokenProcessPool

import pytest

from app.process_pool import IdleProcessPool


def _slow_pid(delay: float) -> int:
    time.sleep(delay)
    return os.getpid()


def _wait_unloaded(pool: IdleProcessPool) -> None:
    deadline = time.monotonic() + 5
    while pool.loaded and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not pool.loaded


def test_idle_pool_releases_process_and_restarts():
    pool = IdleProcessPool(idle_seconds=0.1)
    try:
        assert not pool.loaded
        first = pool.submit(os.getpid).result(timeout=10)
        assert first != os.getpid()
        assert pool.submit(os.getpid).result(timeout=10) == first
        _wait_unloaded(pool)
        assert pool.submit(os.getpid).result(timeout=10) != first
    finally:
        pool.close()
    assert not pool.loaded


def test_idle_timer_does_not_interrupt_running_or_queued_work():
    pool = IdleProcessPool(idle_seconds=0.05)
    try:
        first = pool.submit(_slow_pid, 0.15)
        second = pool.submit(_slow_pid, 0.15)
        pid = first.result(timeout=10)
        time.sleep(0.08)
        assert pool.loaded
        assert second.result(timeout=10) == pid
        _wait_unloaded(pool)
    finally:
        pool.close()


def test_remote_error_does_not_break_following_tasks():
    pool = IdleProcessPool(idle_seconds=1)
    try:
        with pytest.raises(ZeroDivisionError):
            pool.submit(operator.truediv, 1, 0).result(timeout=10)
        assert pool.submit(operator.add, 2, 3).result(timeout=10) == 5
    finally:
        pool.close()


def test_close_waits_for_work_and_next_lifespan_can_start():
    pool = IdleProcessPool(idle_seconds=0.05)
    pending = pool.submit(_slow_pid, 0.1)
    pool.close()
    assert pending.result() != os.getpid()
    assert not pool.loaded
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit(os.getpid)
    pool.start()
    try:
        assert pool.submit(operator.add, 1, 2).result(timeout=10) == 3
    finally:
        pool.close()


def test_crashed_child_is_replaced_for_next_task():
    pool = IdleProcessPool(idle_seconds=1)
    try:
        with pytest.raises(BrokenProcessPool):
            pool.submit(os._exit, 1).result(timeout=10)
        assert pool.submit(operator.add, 2, 3).result(timeout=10) == 5
    finally:
        pool.close()
