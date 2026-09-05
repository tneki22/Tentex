"""Нормализация и лемматизация текста для поискового индекса FTS5.

Один общий `MorphAnalyzer` на процесс: конструктор весит секунду и мегабайты
памяти, создавать его на каждый фрагмент нельзя (см. план подготовительной
вертикали, раздел «Морфология и построение индекса»).
"""

import re
from functools import lru_cache

import pymorphy3

_TOKEN_RE = re.compile(r"[0-9a-zA-Zа-яА-ЯёЁ]+", re.UNICODE)
_CYRILLIC_RE = re.compile(r"[а-яё]")

# Короткий собственный список служебных частей речи, без внешних наборов.
_STOP_WORDS = frozenset(
    {
        "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а",
        "то", "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же",
        "вы", "за", "бы", "по", "только", "ее", "мне", "было", "вот",
        "от", "меня", "еще", "нет", "о", "из", "ему", "теперь",
        "когда", "даже", "ну", "вдруг", "ли", "если", "уже", "или", "ни",
        "быть", "был", "него", "до", "вас", "нибудь", "опять", "уж", "вам",
        "сказал", "ведь", "там", "потом", "себя", "ничего", "им", "для",
        "мы", "тебя", "их", "чем", "была", "сам", "чтобы", "без", "будто",
        "человек", "чего", "раз", "тоже", "себе", "под", "будет", "ж",
        "тогда", "кто", "этот", "того", "потому", "этого", "какой", "совсем",
        "ним", "здесь", "этом", "один", "почти", "мой", "тем", "чтоб",
        "нее", "сейчас", "были", "куда", "зачем", "всех", "никогда",
        "можно", "при", "об", "это", "эти", "эта",
    }
)

# Слова, которыми задают вопрос, а не отвечают на него: в учебнике они стоят
# где угодно и только шумят. Содержательные «определение», «пример», «свойство»
# сюда не попадают — их частотность и так гасит IDF внутри BM25.
_QUESTION_WORDS = frozenset(
    {
        "такой", "каков", "который", "свой", "дать", "перечислить", "привести",
        "назвать", "рассказать", "изложить", "сформулировать", "охарактеризовать",
    }
)

_SKIP_WORDS = _STOP_WORDS | _QUESTION_WORDS

#: Короче двух букв префикс не сужает выдачу — искать по нему нечего.
MIN_PREFIX_LENGTH = 2

_analyzer: pymorphy3.MorphAnalyzer | None = None


def _get_analyzer() -> pymorphy3.MorphAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = pymorphy3.MorphAnalyzer()
    return _analyzer


def fold(token: str) -> str:
    """Нижний регистр и ё→е — единственная нормализация, общая для индекса и запроса.

    Токенизатор `unicode61` сам приводит регистр, но ё и е считает разными
    буквами, поэтому «чёт» не нашло бы «чётность» через сырую колонку.
    """
    return token.lower().replace("ё", "е")


def normalize(text: str) -> list[str]:
    """Токены: буквы и цифры, нижний регистр, ё сведено к е."""
    return [fold(match.group(0)) for match in _TOKEN_RE.finditer(text)]


def tokenize_with_positions(text: str) -> list[tuple[str, int, int]]:
    """Токены с позициями в исходном тексте — для серверной подсветки совпадений."""
    return [
        (fold(match.group(0)), match.start(), match.end())
        for match in _TOKEN_RE.finditer(text)
    ]


@lru_cache(maxsize=100_000)
def _lemmatize_token(token: str) -> str:
    if not _CYRILLIC_RE.search(token):
        return token
    return _get_analyzer().parse(token)[0].normal_form.replace("ё", "е")


def lemmatize(tokens: list[str]) -> list[str]:
    """pymorphy3 для кириллицы, как есть для латиницы и чисел."""
    return [_lemmatize_token(token) for token in tokens]


def index_text(text: str) -> str:
    """Строка лемм через пробел — то, что пишется в колонку `lemmas` индекса."""
    return " ".join(lemmatize(normalize(text)))


def norm_text(text: str) -> str:
    """Строка нормализованных словоформ — колонка `norm`, по ней идёт префикс.

    Леммы для префикса не годятся: pymorphy3 доугадывает огрызок до другого
    слова («мил» → «мила»), поэтому «мил» не был бы началом ни одной леммы.
    """
    return " ".join(normalize(text))


def query_terms(query: str) -> list[str]:
    """Леммы запроса без служебных слов. Пустой или целиком служебный запрос даёт []."""
    lemmas = lemmatize(normalize(query))
    return [lemma for lemma in lemmas if lemma not in _SKIP_WORDS]


def prefix_term(query: str) -> str | None:
    """Последний токен запроса как недопечатанное слово, если он не слишком короток."""
    tokens = normalize(query)
    if not tokens or len(tokens[-1]) < MIN_PREFIX_LENGTH:
        return None
    return tokens[-1]
