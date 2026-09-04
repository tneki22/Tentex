"""Начальные коэффициенты мастера — общий источник для календаря и клиентской оценки."""

import json
from pathlib import Path

HEURISTICS = json.loads(Path(__file__).with_name("heuristics.json").read_text(encoding="utf-8"))


def initial_minutes(kind: str, starting_level: str, target_level: str, *, practice=False) -> int:
    """Эвристика обозначает ожидаемое время, а не измеренную сложность или готовность."""
    return max(
        1,
        round(
            HEURISTICS["minutes"][kind]
            * HEURISTICS["starting_level"][starting_level]
            * HEURISTICS["target_level"][target_level]
            * (HEURISTICS["practice_multiplier"] if practice else 1)
        ),
    )
