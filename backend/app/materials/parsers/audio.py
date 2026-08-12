import os
from pathlib import Path

from app.materials.parsers.base import ParsedElement, ParsedPage


def parse_audio(path: Path) -> ParsedPage:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "Локальная транскрипция недоступна: запустите worker из Docker-образа этапа 5"
        ) from error

    model_name = os.getenv("TENTEX_WHISPER_MODEL", "small")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(path), language="ru", beam_size=5)
    rows = [
        (segment.text.strip(), float(segment.start), float(segment.end))
        for segment in segments
    ]
    rows = [row for row in rows if row[0]]
    if not rows:
        raise RuntimeError("В аудио не удалось распознать речь")
    duration = max(float(getattr(info, "duration", 0) or 0), rows[-1][2], 1)
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
    return ParsedPage(1, 1, duration, markdown, plain, "native", elements)
