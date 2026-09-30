"""Бюджет исследования живёт в receipts участков и переживает перезапуск worker."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.coverage.lifecycle import fenced
from app.db import job_write_transaction
from app.models import CoverageTask
from app.projects.errors import ProjectConflictError

# Какой именно предел остановил запуск: «budget_limit» без этого ничего не объясняет.
LIMIT_TITLE = {"calls": "вызовов", "tokens": "токенов", "cost_usd": "расход $"}


def _exhausted(limits, used, tokens, cost):
    """Возвращает исчерпанный предел до обращения к сети, а не общий признак."""
    if used["calls"] >= limits["max_calls"]:
        return "calls", used["calls"], limits["max_calls"]
    if used["tokens"] + tokens > limits["max_total_tokens"]:
        return "tokens", used["tokens"], limits["max_total_tokens"]
    money = limits.get("max_cost_usd")
    if money is not None and (cost is None or used["cost_usd"] + cost > Decimal(str(money))):
        return "cost_usd", round(used["cost_usd"], 4), money
    return None


def budget_usage(session, run_id) -> dict:
    """Зарезервированная/неизвестная попытка никогда не становится бесплатной."""
    # Счёт ведётся по receipts, а целая задача несёт ещё checkpoint с сохранённым
    # ответом модели. Бюджет спрашивают перед каждым вызовом, и лишние килобайты
    # JSON на участок превращались в заметную паузу между пакетами.
    receipts = [
        r
        for (call_receipts,) in session.execute(
            select(CoverageTask.call_receipts).where(CoverageTask.run_id == run_id)
        )
        for r in call_receipts
    ]
    return {
        "calls": len(receipts),
        "tokens": sum(r["tokens"] for r in receipts),
        "cost_usd": sum(Decimal(str(r["cost_usd"] or 0)) for r in receipts),
        "uncertain_calls": sum(r["uncertain"] for r in receipts),
    }


class ResearchBudget:
    """Короткие writer-транзакции вместо удержания блокировки на время сети."""

    def __init__(self, session, token, task_id):
        self.session, self.token, self.task_id = session, token, task_id

    def reserve(self, tokens, cost):
        """Общий предел включает все участки, retries и schema-repair шлюза."""
        with job_write_transaction(self.session):
            run, _ = fenced(self.session, self.token)
            task = self.session.get(CoverageTask, self.task_id)
            if task is None or task.run_id != run.id:
                raise ValueError("budget_task_scope")
            used = budget_usage(self.session, run.id)
            exhausted = _exhausted(run.limits, used, tokens, cost)
            if exhausted is not None:
                kind, spent, limit = exhausted
                raise ProjectConflictError(
                    f"Достигнут предел исследования: {LIMIT_TITLE[kind]} {spent} из {limit}",
                    code="coverage_budget_exhausted",
                    context={"limit": kind, "spent": str(spent), "value": str(limit)},
                )
            receipt_id = str(uuid4())
            task.call_receipts = [
                *task.call_receipts,
                {
                    "id": receipt_id,
                    "tokens": tokens,
                    "cost_usd": str(cost) if cost is not None else None,
                    "uncertain": True,
                    "state": "reserved",
                },
            ]
            return receipt_id

    def settle(self, receipt_id, usage):
        """После потери lease расход всё равно записывается; это не публикация связей."""
        with job_write_transaction(self.session):
            self.session.expire_all()
            task = self.session.get(CoverageTask, self.task_id)
            receipts = [dict(r) for r in task.call_receipts]
            receipt = next(r for r in receipts if r["id"] == receipt_id)
            if receipt["state"] == "settled":
                return
            receipt["state"] = "settled"
            if usage is not None:
                receipt["tokens"] = usage.input_tokens + usage.output_tokens
                if usage.cost_usd is not None:
                    receipt["cost_usd"] = str(usage.cost_usd)
                    receipt["uncertain"] = False
            task.call_receipts = receipts
