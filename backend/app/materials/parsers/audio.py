"""Расшифровка аудиоматериала: локальный Whisper и сборка страницы транскрипта.

Запись — это одна логическая страница, а реплики на ней — абзацы с настоящим
временем начала и конца. Сборка страницы общая для двух путей: локальный
Whisper из этого файла и облачная модель речи из `cloud_asr`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from app.config import settings
from app.materials.parsers.base import ParsedElement, ParsedPage

# (текст, начало, конец) в секундах от начала записи.
TimedText = tuple[str, float, float]

# «Сделано секунд, всего секунд» → продолжать ли. Ложь означает, что задачу
# отменили, и расшифровку надо бросить, а не дожёвывать до конца.
ProgressCallback = Callable[[float, float], bool]


class TranscriptionCancelled(Exception):
    """Задачу отменили, пока шла расшифровка: страницы не будет и это не ошибка."""


def page_from_segments(
    rows: Sequence[TimedText],
    duration: float,
    diagnostics: Sequence[str] = (),
) -> ParsedPage:
    """Страница транскрипта из реплик со временем.

    `height` страницы — длительность записи в секундах, а bbox абзаца — его
    положение по времени; так просмотрщик и поиск получают тот же вид «место на
    странице», что и у PDF.
    """
    rows = [row for row in rows if row[0].strip()]
    if not rows:
        raise RuntimeError("В аудио не удалось распознать речь")
    duration = max(duration, rows[-1][2], 1)
    elements = tuple(
        ParsedElement(
            "paragraph",
            text,
            (0, start / duration, 1, min(1, end / duration)),
            None,
            None,
            start,
            end,
        )
        for text, start, end in rows
    )
    plain = "\n".join(text for text, _, _ in rows)
    markdown = "\n\n".join(
        f"[{int(start // 60):02d}:{int(start % 60):02d}] {text}" for text, start, _ in rows
    )
    return ParsedPage(1, 1, duration, markdown, plain, "native", elements, tuple(diagnostics))


def parse_audio(path: Path, progress: ProgressCallback | None = None) -> ParsedPage:
    """Расшифровать запись локально: faster-whisper на процессоре.

    :param progress: зовётся после каждой готовой реплики; ложь — отмена.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "Локальная транскрипция недоступна: запустите worker из Docker-образа этапа 5"
        ) from error

    model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(path), language="ru", beam_size=5)
    total = float(getattr(info, "duration", 0) or 0)
    rows: list[TimedText] = []
    # Генератор: сама расшифровка идёт по мере обхода, поэтому здесь же
    # отчитываемся о ходе и здесь же можно остановиться.
    for segment in segments:
        text = segment.text.strip()
        if text:
            rows.append((text, float(segment.start), float(segment.end)))
        if progress is not None and not progress(float(segment.end), total):
            raise TranscriptionCancelled
    return page_from_segments(
        rows, total, (f"asr_local:Whisper {settings.whisper_model}",)
    )
