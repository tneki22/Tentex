"""Проверка ответа на задание урока по ключу — без модели (FR-L11).

Чистые функции: форма, условие (`payload`), ключ и ответ → итог по пунктам.
Пункт — вариант, пропуск, позиция или пара: частичный зачёт считается по ним.
Открытый ответ сюда не попадает — его проверяет судья экзамена.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.models import AttemptOutcome, StudyTaskForm

NUMBER = re.compile(r"^[-+−]?\d+(?:[.,]\d+)?(?:[eе][-+]?\d+)?")
EDGE_PUNCTUATION = " \t\n.,;:!?«»\"'()[]"


class AnswerShapeError(ValueError):
    """Ответ не той формы: не тот ключ, не тот тип или не то число пунктов."""


@dataclass(frozen=True)
class CheckResult:
    outcome: AttemptOutcome
    # Доля верного, 0…1.
    score: float
    # Верен ли каждый пункт: вариант, пропуск, позиция в порядке или пара.
    items: list[bool]
    summary: str


def normalize(text: str) -> str:
    """Регистр, ё→е, пробелы и знаки по краям не влияют на ответ."""
    value = " ".join(str(text).casefold().replace("ё", "е").split())
    return value.strip(EDGE_PUNCTUATION)


def parse_number(text: Any) -> float | None:
    """Число из ответа: запятая или точка, пробелы разрядов, единица после числа."""
    if isinstance(text, bool):
        return None
    if isinstance(text, int | float):
        return float(text) if math.isfinite(text) else None
    raw = str(text).strip().replace(" ", "").replace(" ", "").replace(" ", "")
    match = NUMBER.match(raw)
    if match is None:
        return None
    value = match.group(0).replace("−", "-").replace(",", ".").replace("е", "e")
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _outcome(score: float) -> AttemptOutcome:
    if score >= 1 - 1e-9:
        return AttemptOutcome.PASSED
    return AttemptOutcome.PARTIAL if score > 0 else AttemptOutcome.FAILED


def _indices(value: Any, size: int, name: str) -> list[int]:
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise AnswerShapeError(f"{name}: нужен список номеров")
    if any(item < 0 or item >= size for item in value):
        raise AnswerShapeError(f"{name}: номер вне списка")
    return value


def _single(payload: dict, key: dict, answer: dict) -> CheckResult:
    options = payload["options"]
    choice = answer.get("choice")
    if not isinstance(choice, int) or not 0 <= choice < len(options):
        raise AnswerShapeError("choice: нужен номер варианта")
    right = choice == key["correct"][0]
    items = [index == choice and right for index in range(len(options))]
    return CheckResult(_outcome(1.0 if right else 0.0), 1.0 if right else 0.0, items,
                       "Верно." if right else "Неверно.")


def _multiple(payload: dict, key: dict, answer: dict) -> CheckResult:
    options = payload["options"]
    chosen = set(_indices(answer.get("choices"), len(options), "choices"))
    correct = set(key["correct"])
    hits = len(chosen & correct)
    extra = len(chosen - correct)
    # Лишний выбор снимает столько же, сколько даёт верный: «отметить всё» не проходит.
    score = max(0.0, (hits - extra) / len(correct))
    items = [(index in chosen) == (index in correct) for index in range(len(options))]
    parts = [f"верных отмечено {hits} из {len(correct)}"]
    if extra:
        parts.append(f"лишних {extra}")
    return CheckResult(_outcome(score), score, items, ", ".join(parts).capitalize() + ".")


def _pure_number(text: str) -> float | None:
    """Число, если весь ответ ключа — число: «10BASE-T» числом 10 не считается."""
    raw = str(text).strip().replace(" ", "").replace(" ", "")
    return parse_number(raw) if NUMBER.fullmatch(raw) else None


def _blank_right(given: str, accepted: list[str]) -> bool:
    if normalize(given) in {normalize(item) for item in accepted}:
        return True
    number = parse_number(given)
    return number is not None and any(
        (other := _pure_number(item)) is not None and math.isclose(number, other, rel_tol=1e-9)
        for item in accepted
    )


def _blanks(payload: dict, key: dict, answer: dict) -> CheckResult:
    given = answer.get("blanks")
    accepted = key["answers"]
    if not isinstance(given, list) or len(given) != len(accepted):
        raise AnswerShapeError(f"blanks: нужно {len(accepted)} ответов")
    items = [_blank_right(str(value or ""), options) for value, options in zip(
        given, accepted, strict=True)]
    score = sum(items) / len(items)
    return CheckResult(_outcome(score), score, items,
                       f"Верно пропусков: {sum(items)} из {len(items)}.")


def _numeric(payload: dict, key: dict, answer: dict) -> CheckResult:
    number = parse_number(answer.get("value"))
    if number is None:
        raise AnswerShapeError("value: нужно число")
    expected = float(key["value"])
    tolerance = float(key.get("tolerance") or 0)
    allowed = abs(expected) * tolerance if key.get("relative") else tolerance
    # Без допуска сравнение всё равно терпит ошибку округления записи числа.
    right = abs(number - expected) <= max(allowed, abs(expected) * 1e-9, 1e-12)
    return CheckResult(_outcome(1.0 if right else 0.0), 1.0 if right else 0.0, [right],
                       "Верно." if right else "Неверно.")


def _ordering(payload: dict, key: dict, answer: dict) -> CheckResult:
    size = len(payload["items"])
    order = _indices(answer.get("order"), size, "order")
    if sorted(order) != list(range(size)):
        raise AnswerShapeError("order: нужна перестановка всех шагов")
    items = [given == expected for given, expected in zip(order, key["order"], strict=True)]
    score = sum(items) / size
    return CheckResult(_outcome(score), score, items,
                       f"На своём месте шагов: {sum(items)} из {size}.")


def _matching(payload: dict, key: dict, answer: dict) -> CheckResult:
    size = len(payload["left"])
    pairs = answer.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != size:
        raise AnswerShapeError(f"pairs: нужно {size} ответов")
    if not all(item is None or (isinstance(item, int) and 0 <= item < len(payload["right"]))
               for item in pairs):
        raise AnswerShapeError("pairs: номер вне списка")
    items = [given == expected for given, expected in zip(pairs, key["match"], strict=True)]
    score = sum(items) / size
    return CheckResult(_outcome(score), score, items,
                       f"Верных пар: {sum(items)} из {size}.")


CHECKERS = {
    StudyTaskForm.SINGLE_CHOICE: _single,
    StudyTaskForm.MULTIPLE_CHOICE: _multiple,
    StudyTaskForm.FILL_BLANKS: _blanks,
    StudyTaskForm.NUMERIC: _numeric,
    StudyTaskForm.ORDERING: _ordering,
    StudyTaskForm.MATCHING: _matching,
}


def check(form: StudyTaskForm, payload: dict, key: dict, answer: dict) -> CheckResult:
    """Итог ответа по ключу; неподходящая форма ответа — `AnswerShapeError`."""
    checker = CHECKERS.get(form)
    if checker is None:
        raise AnswerShapeError("Открытый ответ проверяет модель, а не ключ")
    if not isinstance(answer, dict):
        raise AnswerShapeError("Ответ — объект")
    return checker(payload, key, answer)
