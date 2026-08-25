"""Подбор вопроса программы по заголовку раздела ответов.

Посимвольное сравнение нормализованных строк ломается от одной буквы: «о
индексах» в файле ответов и «об индексах» в списке вопросов — один и тот же
вопрос, а раздел падал в «не нашли». Сравнение здесь нечёткое, но дешёвое и
объяснимое: пересечение значимых лемм плюс посимвольное сходство строк.

Ни модели, ни векторов: эмбеддинги приезжают на этапе 6 и решают другую задачу —
поиск по большому материалу, а не сверку двух коротких формулировок (PLAN.md,
вертикаль «Экзамен с ИИ», срез A).

Что не уверены — не привязываем молча: такой заголовок возвращается со списком
кандидатов, и вопрос за пользователем.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from uuid import UUID

from app.materials.lexicon import lemmatize, normalize, query_terms
from app.models import ReferenceAnswerMatchMethod

# Отделитель после номера может и не стоять: «Вопрос 21 Использование индексов»
# — такой же заголовок, как «Вопрос 21. Использование индексов».
LEADING_MARKER_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:"
    r"(?:(?:вопрос|задача|задание)\s*(?:№|#)?\s*\d+(?:\.\d+)*\s*(?:[.):—–-]\s*|\s+))"
    r"|(?:\d+(?:\.\d+)*\s*[.)]\s*))",
    re.IGNORECASE,
)
PUNCTUATION_RE = re.compile(r"[,;:.!?«»\"'()\[\]{}/\\—–\-]+")


def normalize_answer_heading(value: str) -> str:
    """Заголовок раздела ответов и формулировка вопроса сравниваются по этой форме.

    Пунктуация выбрасывается целиком: «Ключи, как средство создания связей» в списке
    вопросов и «Ключи как средство создания связей» в ответах — один и тот же вопрос,
    и расходиться из-за запятой они не должны.
    """
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    normalized = LEADING_MARKER_RE.sub("", normalized)
    normalized = PUNCTUATION_RE.sub(" ", normalized)
    return " ".join(normalized.split())


# Порог автопривязки подобран на файле ответов пользователя: «о индексах» против
# «об индексах» даёт 0.97, «Транзакции» против «Транзакции и блокировки» — 0.56.
AUTO_THRESHOLD = 0.86
# Порог показа кандидата ниже порога привязки и намеренно щедрый: выбрать из пяти
# строк дешевле, чем искать вопрос в списке на полсотни.
SUGGEST_THRESHOLD = 0.45
# Если второй кандидат дышит в затылок первому — выбор за пользователем.
CONFIDENT_MARGIN = 0.04
# Насколько похожими должны быть два слова, чтобы считаться одним.
LEMMA_MATCH = 0.8
MAX_CANDIDATES = 5


@dataclass(frozen=True, slots=True)
class HeadingCandidate:
    node_id: UUID
    title: str
    score: float


@dataclass(frozen=True, slots=True)
class HeadingMatch:
    """Результат подбора: либо узлы, либо кандидаты на выбор — но не оба сразу."""

    node_ids: tuple[UUID, ...] = ()
    method: ReferenceAnswerMatchMethod | None = None
    score: float = 0.0
    candidates: tuple[HeadingCandidate, ...] = ()

    @property
    def matched(self) -> bool:
        return bool(self.node_ids)


@dataclass(frozen=True, slots=True)
class _Entry:
    node_id: UUID
    title: str
    normalized: str
    lemmas: frozenset[str]


def _significant_lemmas(normalized: str) -> frozenset[str]:
    """Леммы считаются от нормализованной формы, а не от сырого заголовка.

    Иначе «Вопрос 21 Использование индексов» приносит в набор слова `вопрос` и `21`,
    которых у формулировки вопроса нет, и пересечение падает с 1.0 до 0.67 на ровном
    месте — на каждом нумерованном заголовке сразу.
    """
    terms = query_terms(normalized)
    if terms:
        return frozenset(terms)
    return frozenset(lemmatize(normalize(normalized)))


@lru_cache(maxsize=65_536)
def _lemma_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _soft_overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Пересечение, в котором лемме засчитывается почти такая же пара.

    Одна опечатка не должна обнулять слово целиком: «трёхзвенная» против
    «трезвенной» и «нереляционные» против «не реляционных» — это тот же вопрос, а
    строгое пересечение множеств теряет на них треть совпадения.
    """
    matched = 0.0
    remaining = list(right)
    for lemma in left:
        best_score, best_index = 0.0, -1
        for position, other in enumerate(remaining):
            score = _lemma_similarity(lemma, other)
            if score > best_score:
                best_score, best_index = score, position
        if best_index >= 0 and best_score >= LEMMA_MATCH:
            matched += best_score
            remaining.pop(best_index)
    union = len(left) + len(right) - matched
    return matched / union if union > 0 else 0.0


def _score(normalized: str, left_lemmas: frozenset[str], entry: _Entry) -> float:
    """Половина за пересечение смысла, половина за похожесть написания.

    Одних лемм мало: «Ключи» и «Ключи и индексы» дают половину пересечения, но это
    разные вопросы. Одного посимвольного сходства мало: у «Дисциплина: Нереляционные
    базы данных» и настоящего вопроса про те же базы оно доходит до 0.67.
    """
    overlap = _soft_overlap(left_lemmas, entry.lemmas)
    ratio = SequenceMatcher(None, normalized, entry.normalized).ratio()
    return 0.5 * overlap + 0.5 * ratio


class HeadingIndex:
    """Индекс формулировок вопросов, по которому ищется заголовок раздела."""

    def __init__(self, nodes: Iterable[tuple[UUID, str]]) -> None:
        self._exact: dict[str, list[UUID]] = {}
        self._entries: list[_Entry] = []
        self._entries_by_id: dict[UUID, _Entry] = {}
        self._by_lemma: dict[str, list[int]] = {}
        for node_id, title in nodes:
            normalized = normalize_answer_heading(title)
            self._exact.setdefault(normalized, []).append(node_id)
            entry = _Entry(node_id, title, normalized, _significant_lemmas(normalized))
            self._entries_by_id[node_id] = entry
            index = len(self._entries)
            self._entries.append(entry)
            for lemma in entry.lemmas:
                self._by_lemma.setdefault(lemma, []).append(index)

    def __len__(self) -> int:
        return len(self._entries)

    def rank(self, heading: str) -> tuple[HeadingCandidate, ...]:
        """Return all plausible questions without applying the auto-link threshold."""
        normalized = normalize_answer_heading(heading)
        if not normalized:
            return ()

        exact = self._exact.get(normalized)
        if exact:
            return tuple(
                HeadingCandidate(node_id, self._entries_by_id[node_id].title, 1.0)
                for node_id in exact
            )

        lemmas = _significant_lemmas(normalized)
        if not lemmas:
            return ()

        # Сравниваем только с теми вопросами, у которых есть хоть одно общее слово:
        # иначе на каждый заголовок приходится весь список вопросов.
        seen: set[int] = set()
        for lemma in lemmas:
            seen.update(self._by_lemma.get(lemma, ()))
        if not seen:
            return ()

        return tuple(sorted(
            (
                HeadingCandidate(
                    self._entries[index].node_id,
                    self._entries[index].title,
                    _score(normalized, lemmas, self._entries[index]),
                )
                for index in seen
            ),
            key=lambda candidate: (-candidate.score, candidate.title),
        ))

    def match(self, heading: str) -> HeadingMatch:
        normalized = normalize_answer_heading(heading)
        if not normalized:
            return HeadingMatch()

        exact = self._exact.get(normalized)
        if exact:
            # Формулировка, повторяющаяся в программе, привязывается ко всем повторам:
            # ответ у них один и тот же, а дубль — проблема программы, а не привязки.
            return HeadingMatch(tuple(exact), ReferenceAnswerMatchMethod.EXACT_TITLE, 1.0)

        scored = list(self.rank(heading))
        if not scored:
            return HeadingMatch()
        best = scored[0]
        runner_up = scored[1].score if len(scored) > 1 else 0.0
        if best.score >= AUTO_THRESHOLD and best.score - runner_up >= CONFIDENT_MARGIN:
            return HeadingMatch((best.node_id,), ReferenceAnswerMatchMethod.FUZZY_TITLE, best.score)
        return HeadingMatch(
            candidates=tuple(
                candidate
                for candidate in scored[:MAX_CANDIDATES]
                if candidate.score >= SUGGEST_THRESHOLD
            ),
            score=best.score,
        )
