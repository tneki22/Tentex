"""Именованные уровни оглавления, общие для извлечения и импорта."""

import re

_ORDER_WORD = (
    r"(?:первая|вторая|третья|четвертая|четвёртая|пятая|шестая|седьмая|"
    r"восьмая|девятая|десятая|первый|второй|третий|четвертый|четвёртый|"
    r"пятый|шестой|седьмой|восьмой|девятый|десятый|first|second|third|"
    r"fourth|fifth|sixth|seventh|eighth|ninth|tenth|one|two|three|four|"
    r"five|six|seven|eight|nine|ten)"
)
_ORDER_MARKER = rf"(?:\d+|[ivxlcdm]+|{_ORDER_WORD})"

GENERAL_TITLE_RE = re.compile(
    rf"^(?:часть|раздел|part|section)(?:\s+{_ORDER_MARKER}\b|[.:—-]?$)",
    re.IGNORECASE,
)
TOPIC_TITLE_RE = re.compile(
    rf"^(?:тема|лекция|глава|topic|lecture|chapter)(?:\s+{_ORDER_MARKER}\b|[.:—-]?$)",
    re.IGNORECASE,
)
