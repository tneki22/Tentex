"""Детерминированные ступени проверки экзаменационного ответа."""

from collections import Counter
from dataclasses import dataclass

from app.materials import lexicon
from app.models import AttemptOutcome, GradeMethod

KEY_TERMS_LIMIT = 12
PASS_COVERAGE = 0.8
FAIL_COVERAGE = 0.25


@dataclass(frozen=True)
class RubricPoint:
    point: str
    quote: str | None = None
    quote_start: int | None = None
    quote_end: int | None = None


@dataclass(frozen=True)
class CheckResult:
    outcome: AttemptOutcome
    method: GradeMethod | None
    credited: list[RubricPoint]
    missed: list[RubricPoint]
    wrong: list[RubricPoint]
    summary: str
    decided: bool


def _canonical(text: str) -> str:
    """Регистр, пробелы, пунктуация и ё/е сведены для точного сравнения."""
    return " ".join(lexicon.normalize(text)).replace("ё", "е")


def key_terms(reference: str, question: str) -> list[str]:
    """Главные леммы эталона без служебных слов и слов самого вопроса."""
    asked = set(lexicon.query_terms(question))
    counts = Counter(term for term in lexicon.query_terms(reference) if term not in asked)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _ in ranked[:KEY_TERMS_LIMIT]]


def locate_quote(answer: str, quote: str) -> tuple[int, int] | None:
    """Возвращает только проверенные по исходному ответу смещения цитаты."""
    if not quote:
        return None

    exact_start = answer.find(quote)
    if exact_start >= 0:
        return exact_start, exact_start + len(quote)

    answer_tokens = lexicon.tokenize_with_positions(answer)
    quote_tokens = lexicon.tokenize_with_positions(quote)
    if not answer_tokens or not quote_tokens or len(quote_tokens) > len(answer_tokens):
        return None

    wanted = [token.replace("ё", "е") for token, _, _ in quote_tokens]
    window_size = len(wanted)
    for index in range(len(answer_tokens) - window_size + 1):
        window = [
            token.replace("ё", "е")
            for token, _, _ in answer_tokens[index : index + window_size]
        ]
        if window == wanted:
            return answer_tokens[index][1], answer_tokens[index + window_size - 1][2]
    return None


def _credited_point(answer: str, term: str) -> RubricPoint:
    answer_tokens = lexicon.tokenize_with_positions(answer)
    answer_lemmas = lexicon.lemmatize([token for token, _, _ in answer_tokens])
    for lemma, (_, start, end) in zip(answer_lemmas, answer_tokens, strict=True):
        if lemma == term:
            return RubricPoint(
                point=term,
                quote=answer[start:end],
                quote_start=start,
                quote_end=end,
            )
    return RubricPoint(point=term)


def deterministic_check(answer: str, reference: str | None, question: str) -> CheckResult:
    """Проверяет ответ без сети и сообщает, нужен ли следующий уровень лесенки."""
    if reference is None or not reference.strip():
        return CheckResult(
            outcome=AttemptOutcome.UNSCORED,
            method=None,
            credited=[],
            missed=[],
            wrong=[],
            summary="Эталон не задан: система не может проверить ответ сама",
            decided=False,
        )

    if _canonical(answer) == _canonical(reference):
        return CheckResult(
            outcome=AttemptOutcome.PASSED,
            method=GradeMethod.EXACT_MATCH,
            credited=[
                RubricPoint(
                    point="Ответ совпадает с эталоном",
                    quote=answer,
                    quote_start=0,
                    quote_end=len(answer),
                )
            ],
            missed=[],
            wrong=[],
            summary="Ответ совпадает с эталоном",
            decided=True,
        )

    terms = key_terms(reference, question)
    if not terms:
        return CheckResult(
            outcome=AttemptOutcome.UNSCORED,
            method=None,
            credited=[],
            missed=[],
            wrong=[],
            summary="В эталоне недостаточно содержательных терминов для проверки",
            decided=False,
        )

    answer_terms = set(lexicon.query_terms(answer))
    found = [term for term in terms if term in answer_terms]
    omitted = [term for term in terms if term not in answer_terms]
    coverage = len(found) / len(terms)
    credited = [_credited_point(answer, term) for term in found]
    missed = [RubricPoint(point=term) for term in omitted]

    if coverage >= PASS_COVERAGE:
        return CheckResult(
            outcome=AttemptOutcome.PASSED,
            method=GradeMethod.KEY_TERMS,
            credited=credited,
            missed=missed,
            wrong=[],
            summary="Ответ содержит достаточно ключевых терминов эталона",
            decided=True,
        )

    outcome = (
        AttemptOutcome.PARTIAL if coverage > FAIL_COVERAGE else AttemptOutcome.FAILED
    )
    return CheckResult(
        outcome=outcome,
        method=GradeMethod.KEY_TERMS,
        credited=credited,
        missed=missed,
        wrong=[],
        summary=(
            "Предварительная проверка нашла только часть ключевых терминов"
            if outcome is AttemptOutcome.PARTIAL
            else "Предварительная проверка не нашла достаточно ключевых терминов"
        ),
        decided=False,
    )
