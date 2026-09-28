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


#: Словарь синонимов терминологии (как synonym filter в Lucene): программа
#: курса и учебник называют одно понятие по-разному. Пара попадает сюда только
#: после проверки на реальных материалах: программа ОС спрашивает про
#: «взаимоблокировку», учебник Кузнецова говорит «тупик».
TERM_SYNONYMS: dict[str, str] = {"взаимоблокировка": "тупик"}


def with_synonyms(query: str) -> str:
    """Заменить термины запроса их названием из учебника, остальное не трогать."""
    parts: list[str] = []
    position = 0
    for token, start, end in tokenize_with_positions(query):
        synonym = TERM_SYNONYMS.get(_lemmatize_token(token))
        if synonym:
            parts += [query[position:start], synonym]
            position = end
    return "".join([*parts, query[position:]])


#: Части речи, которые называют предмет вопроса. Глагол («утверждает»,
#: «называют») задаёт форму вопроса, а в ответе стоит иначе или отсутствует.
_CONTENT_POS = frozenset({"NOUN", "ADJF", "ADJS", "COMP", "PRTF"})


def content_terms(query: str) -> list[str]:
    """Леммы существительных, прилагательных, латиницы, чисел и слов вне словаря.

    Часть речи незнакомого слова pymorphy3 угадывает («Херфиндаля» — деепричастие),
    поэтому такое слово считается содержательным всегда. Запрос из одних глаголов
    и служебных слов возвращает все свои леммы.
    """
    analyzer = _get_analyzer()
    lemmas = [
        lemma
        for token in normalize(query)
        if (lemma := _lemmatize_token(token)) not in _SKIP_WORDS
        and (
            not _CYRILLIC_RE.search(token)
            or not analyzer.word_is_known(token)
            or analyzer.parse(token)[0].tag.POS in _CONTENT_POS
        )
    ]
    return lemmas or query_terms(query)


#: Граммемы pymorphy3 для имён собственных: фамилия, имя, отчество, топоним,
#: организация, торговая марка.
_PROPER_NAME = frozenset({"Surn", "Name", "Patr", "Geox", "Orgn", "Trad"})
_LATIN_NAME_RE = re.compile(r"[0-9A-Za-z]+(?:[-_][0-9A-Za-z]+)*")


def _latin_names(query: str) -> list[tuple[int, str]]:
    """Латинские слова и имена из частей через «_» или «-» с позицией в запросе.

    `io_uring`, `IS-LM`, `Wi-Fi`, `SHA-256` — одно имя: токенизатор режет их на
    части, и «IS» с «LM» по отдельности короче порога. Через дефис части
    склеиваются, только если каждая не короче двух знаков: `A-B` — формула, а
    `B-tree` учебник пишет «B-дерево».
    """
    names: list[tuple[int, str]] = []
    for match in _LATIN_NAME_RE.finditer(query):
        pieces = match.group(0).split("-")
        if all(len(piece) >= 2 for piece in pieces):
            names.append((match.start(), match.group(0)))
            continue
        offset = match.start()
        for piece in pieces:
            names.append((offset, piece))
            offset += len(piece) + 1
    return names


def specific_terms(query: str) -> list[str]:
    """Имена, аббревиатуры и слова вне общего словаря в том виде, как их написали.

    Такие слова называют предмет вопроса: если их нет в материалах, материалы
    не о нём. Общеупотребительное слово («привилегия», «протокол») может быть
    синонимом формулировки учебника, поэтому сюда не входит. То же с английским
    словом строчными: «likelihood» или «dropout» русский конспект пишет
    по-русски. Латиница — аббревиатуры, названия и идентификаторы (`ZFC`,
    `WireGuard`, `io_uring`, `IS-LM`, `v2`): с заглавной буквой, цифрой или
    подчёркиванием; от трёх символов или с цифрой, чтобы не считать терминами
    переменные формул. Кириллица — слово, которого нет в словаре
    pymorphy3, или имя собственное.
    """
    analyzer = _get_analyzer()
    found: list[tuple[int, str]] = []
    for start, written in _latin_names(query):
        has_digit = any(char.isdigit() for char in written)
        if not written.isdigit() and (len(written) >= 3 or has_digit) and (
            has_digit or "_" in written or any(char.isupper() for char in written)
        ):
            found.append((start, written))
    for token, start, end in tokenize_with_positions(query):
        if _CYRILLIC_RE.search(token) and len(token) >= 3 and (
            not analyzer.word_is_known(token)
            or analyzer.parse(token)[0].tag.grammemes & _PROPER_NAME
        ):
            found.append((start, query[start:end]))
    terms: dict[str, str] = {}
    for _, written in sorted(found):
        terms.setdefault(fold(written), written)
    return list(terms.values())


def prefix_term(query: str) -> str | None:
    """Последний токен запроса как недопечатанное слово, если он не слишком короток."""
    tokens = normalize(query)
    if not tokens or len(tokens[-1]) < MIN_PREFIX_LENGTH:
        return None
    return tokens[-1]
