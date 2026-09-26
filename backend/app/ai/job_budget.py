"""Предел одного платного запуска, записанный в checkpoint фоновой задачи.

Разбор «Облако» и «Описать изображения» ограничены сразу числом вызовов и
суммой. Резерв верхней оценки пишется до сети отдельной короткой транзакцией,
фактический расход — по `usage` провайдера. Попытка, после которой ответа нет
(timeout, обрыв), остаётся потраченной по резерву: провайдер мог списать деньги.
Состояние переживает паузу и перезапуск воркера, потому что живёт в строке
задачи, а не в памяти.

Хранится агрегатом, а не списком квитанций: у книги в тысячу страниц список
рос бы на каждый вызов и переписывался бы целиком при каждом чекпоинте.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.provider import ProviderUsage
from app.db import job_write_transaction
from app.models import BackgroundJob
from app.projects.errors import ProjectConflictError

KEY = "budget"


def budget_state(
    *, max_cost_usd: Decimal | None, max_calls: int | None, allow_unknown_price: bool
) -> dict[str, Any]:
    """Начальное состояние предела для checkpoint новой задачи."""
    return {
        "max_cost_usd": str(max_cost_usd) if max_cost_usd is not None else None,
        "max_calls": max_calls,
        "allow_unknown_price": allow_unknown_price,
        "calls": 0,
        "spent_usd": "0",
        "uncertain_calls": 0,
        "open": {},
    }


def spent(state: dict[str, Any]) -> Decimal:
    """Потраченное вместе с незакрытыми резервами."""
    reserved = sum(Decimal(str(value or 0)) for value in (state.get("open") or {}).values())
    return Decimal(str(state.get("spent_usd") or 0)) + reserved


class JobBudget:
    """`BudgetContext` шлюза поверх checkpoint одной фоновой задачи."""

    def __init__(self, session: Session, job_id: UUID) -> None:
        self.session = session
        self.job_id = job_id

    def reserve(self, tokens: int, cost: Decimal | None) -> str:
        """Зарезервировать попытку или остановить запуск до запроса провайдеру."""
        with job_write_transaction(self.session, self.job_id):
            job = self.session.get(BackgroundJob, self.job_id)
            if job is None:
                raise ProjectConflictError("Задача запуска не найдена", code="run_budget_missing")
            checkpoint = dict(job.checkpoint)
            state = dict(checkpoint.get(KEY) or budget_state(
                max_cost_usd=None, max_calls=None, allow_unknown_price=True
            ))
            limit_calls = state.get("max_calls")
            if limit_calls is not None and int(state.get("calls") or 0) >= int(limit_calls):
                raise ProjectConflictError(
                    f"Достигнут предел запуска: вызовов {state.get('calls')} из {limit_calls}",
                    code="run_budget_exhausted",
                    context={"limit": "calls", "value": limit_calls},
                )
            limit_cost = state.get("max_cost_usd")
            if cost is None and not state.get("allow_unknown_price"):
                raise ProjectConflictError(
                    "Цена модели неизвестна — запуск остановлен до вызова",
                    code="run_budget_unknown_price",
                )
            if (
                limit_cost is not None
                and cost is not None
                and spent(state) + cost > Decimal(str(limit_cost))
            ):
                raise ProjectConflictError(
                    f"Достигнут предел запуска: ${spent(state):.4f} из ${Decimal(limit_cost):.4f}",
                    code="run_budget_exhausted",
                    context={"limit": "cost_usd", "value": str(limit_cost)},
                )
            receipt = str(uuid4())
            state["calls"] = int(state.get("calls") or 0) + 1
            state["open"] = {**(state.get("open") or {}), receipt: str(cost or 0)}
            checkpoint[KEY] = state
            job.checkpoint = checkpoint
            return receipt

    def settle(self, receipt_id: str, usage: ProviderUsage | None) -> None:
        """Закрыть резерв фактом; неизвестный расход остаётся равным резерву."""
        with job_write_transaction(self.session, self.job_id):
            self.session.expire_all()
            job = self.session.get(BackgroundJob, self.job_id)
            if job is None:
                return
            checkpoint = dict(job.checkpoint)
            state = dict(checkpoint.get(KEY) or {})
            open_reserves = dict(state.get("open") or {})
            reserved = open_reserves.pop(receipt_id, None)
            if reserved is None:
                return
            actual = usage.cost_usd if usage is not None else None
            if actual is None:
                actual = Decimal(str(reserved))
                state["uncertain_calls"] = int(state.get("uncertain_calls") or 0) + 1
            state["spent_usd"] = str(Decimal(str(state.get("spent_usd") or 0)) + actual)
            state["open"] = open_reserves
            checkpoint[KEY] = state
            job.checkpoint = checkpoint
