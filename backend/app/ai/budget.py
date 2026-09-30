"""Порт общего бюджета: шлюз учитывает каждую попытку, включая неудачные."""

from decimal import Decimal
from typing import Protocol

from app.ai.provider import ProviderUsage


class BudgetContext(Protocol):
    """Резерв записывается до сети; незакрытый резерв после аварии остаётся расходом."""

    def reserve(self, tokens: int, cost: Decimal | None) -> str:
        """Вернуть устойчивый ID попытки либо остановить до запроса провайдеру."""
        ...

    def settle(self, receipt_id: str, usage: ProviderUsage | None) -> None:
        """Неизвестный расход сохраняется явно и не освобождает резерв."""
        ...
