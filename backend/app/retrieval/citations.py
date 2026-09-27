"""Ссылки [S*] в ответах по источникам: разбор и проверка.

Общая для учебного чата и полного обзора: обе проверяют ответ модели одним
правилом, и форма `[S1, S2]` понимается одинаково.
"""

from __future__ import annotations

import re

CITATION_GROUP = re.compile(r"\[(S\d+(?:[ \t]*[,;][ \t]*S\d+)*)\]")


def cited_ids(text: str) -> set[str]:
    """Все S-ID из ссылок текста: `[S1]`, `[S1, S2]`, `[S1; S2]`, `[S1][S2]`."""
    return {
        item.strip()
        for group in CITATION_GROUP.findall(text)
        for item in re.split(r"[,;]", group)
    }


def citation_error(text: str, allowed: set[str]) -> str | None:
    """Ссылки ответа: только переданные S-ID; при наличии источников — хотя бы одна.

    Неизвестный ID отклоняется и без источников: [S1] в ответе без выдачи —
    выдуманная ссылка, а не отсутствие цитат.
    """
    used = cited_ids(text)
    unknown = used - allowed
    if unknown:
        return "Ответ сослался на неизвестные источники: " + ", ".join(sorted(unknown))
    if allowed and not used:
        return "Ответ по найденным источникам не содержит проверяемых цитат"
    return None
