"""`retry_on_locked` — общий приём повтора при `database is locked`/`is busy`.

24.09.2026 от этой же ошибки падал `upgrade_database()` (api и worker гонялись
за миграцией на одновременном `docker compose restart`) и `registry.resolve_job`
(снятие задачи с панели ловило чужую блокировку записи). Здесь — сам механизм
на фиктивной операции, без реальной БД: гонка воспроизводится в
`test_db_write_contention.py`, а сценарии `resolve_job`/`cancel_job` — в
`test_background_review.py`.
"""

import pytest
from sqlalchemy.exc import OperationalError

from app.db import retry_on_locked


def _locked_error() -> OperationalError:
    return OperationalError("UPDATE t SET x = 1", {}, Exception("database is locked"))


def test_succeeds_without_retry_when_operation_does_not_fail() -> None:
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        return "ok"

    assert retry_on_locked(operation) == "ok"
    assert calls["count"] == 1


def test_retries_past_a_transient_lock_and_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.db as db_module

    monkeypatch.setattr(db_module.time, "sleep", lambda _: None)
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise _locked_error()
        return "ok"

    assert retry_on_locked(operation) == "ok"
    assert calls["count"] == 3


def test_gives_up_after_the_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.db as db_module

    monkeypatch.setattr(db_module.time, "sleep", lambda _: None)

    def always_locked() -> None:
        raise _locked_error()

    with pytest.raises(OperationalError):
        retry_on_locked(always_locked, attempts=2)


def test_does_not_retry_an_unrelated_operational_error() -> None:
    calls = {"count": 0}

    def operation() -> None:
        calls["count"] += 1
        raise OperationalError("SELECT 1", {}, Exception("no such table: ghost"))

    with pytest.raises(OperationalError):
        retry_on_locked(operation)
    assert calls["count"] == 1
