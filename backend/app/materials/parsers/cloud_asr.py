"""Режим «Облако» для аудио: запись читает внешняя модель речи.

Соседка `cloud_vlm` для страниц. Запись декодируется в моно 16 кГц, режется на
куски по несколько минут (провайдеры принимают файл до 25 МБ, а долгий запрос
рвётся по таймауту) и уходит через тот же шлюз, что и диктовка: выбор модели,
ключи, лимиты и учёт расхода остаются там.

Резать по времени вслепую нельзя — граница попадёт в середину слова, и оно
пропадёт из обоих кусков. Поэтому граница ищется в самой тихой доле секунды
перед плановым концом куска.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.ai.gateway import RETRY_BACKOFF_SECONDS, RETRYABLE_PROVIDER_CODES, ModelGateway
from app.ai.provider import OpenAICompatibleTransport
from app.ai.settings import AiGatewayError
from app.materials.parsers.audio import (
    ProgressCallback,
    TimedText,
    TranscriptionCancelled,
    page_from_segments,
)
from app.materials.parsers.base import ParsedPage
from app.ocr.speech import SPEECH_ROLE

log = logging.getLogger("tentex.worker")

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2

# Плановая длина куска. WAV моно 16 кГц весит ≈1,9 МБ на минуту, так что даже
# кусок с запасом на поиск границы (5,5 мин ≈ 10,5 МБ) далеко от потолка 20 МБ.
# Короче — больше вызовов и чаще граница; длиннее — дороже повтор при сбое.
CHUNK_SECONDS = 300
# Где искать тихое место: последние секунды перед плановой границей.
CUT_WINDOW_SECONDS = 30
FRAME_SECONDS = 0.1
# Кусок тише этого среднего уровня (шкала int16) — тишина, слать его платно
# незачем: модель на пустоте не молчит, а выдумывает фразы.
SILENCE_LEVEL = 25

# Фразы из ответа без времени группируются в абзацы примерно такой длины.
APPROX_PARAGRAPH_CHARS = 220
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class TranscriptionFailed(RuntimeError):
    """Расшифровка остановилась на куске: готовые части сохранены, повтор их не тронет."""


def decode_pcm(path: Path, dest: Path) -> int:
    """Декодировать любой аудиофайл в сырой PCM s16 моно 16 кГц; вернуть число отсчётов.

    Пишет на диск, а не в память: двухчасовая лекция в float32 занимает полгига.
    """
    try:
        import av
    except ImportError as error:
        raise RuntimeError(
            "Расшифровка недоступна: запустите worker из Docker-образа этапа 5"
        ) from error

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    samples = 0
    try:
        with av.open(str(path)) as container, dest.open("wb") as out:
            if not container.streams.audio:
                raise RuntimeError("В файле нет звуковой дорожки")
            for frame in container.decode(audio=0):
                for piece in resampler.resample(frame):
                    block = piece.to_ndarray().astype("<i2", copy=False)
                    out.write(block.tobytes())
                    samples += block.size
            for piece in resampler.resample(None):
                block = piece.to_ndarray().astype("<i2", copy=False)
                out.write(block.tobytes())
                samples += block.size
    except av.error.FFmpegError as error:
        raise RuntimeError(
            "Не удалось прочитать аудиофайл: формат не поддерживается или файл повреждён"
        ) from error
    return samples


def plan_chunks(pcm: np.ndarray, chunk_seconds: int = CHUNK_SECONDS) -> list[tuple[int, int]]:
    """Границы кусков в отсчётах: режем по самой тихой доле секунды у планового конца."""
    total = len(pcm)
    size = chunk_seconds * SAMPLE_RATE
    window = CUT_WINDOW_SECONDS * SAMPLE_RATE
    frame = int(FRAME_SECONDS * SAMPLE_RATE)
    chunks: list[tuple[int, int]] = []
    start = 0
    # Пока остаток длиннее куска и окна поиска — режем. Иначе хвост забирает
    # последний кусок целиком: обрезок в пару секунд не стоит отдельного вызова.
    while total - start > size + window:
        low, high = start + size - window, start + size
        chunk = np.abs(np.asarray(pcm[low:high], dtype=np.int32))
        frames = len(chunk) // frame
        levels = chunk[: frames * frame].reshape(frames, frame).mean(axis=1)
        cut = low + int(np.argmin(levels)) * frame + frame // 2
        chunks.append((start, cut))
        start = cut
    chunks.append((start, total))
    return chunks


def is_silent(samples: np.ndarray) -> bool:
    return len(samples) == 0 or float(np.abs(samples.astype(np.int32)).mean()) < SILENCE_LEVEL


def wav_bytes(samples: np.ndarray) -> bytes:
    """WAV 16 кГц моно: его понимают все три пути шлюза (multipart, JSON, чат)."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(BYTES_PER_SAMPLE)
        file.setframerate(SAMPLE_RATE)
        file.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return buffer.getvalue()


def approximate_segments(text: str, start: float, end: float) -> list[TimedText]:
    """Время фраз, когда провайдер его не дал: пропорционально длине текста.

    Граница куска известна точно, а внутри неё положение фразы прикидывается по
    числу букв. Ошибка в пределах нескольких секунд — для перехода к месту
    записи хватает, но это оценка, и материал получает отметку об этом.
    """
    sentences = [part.strip() for part in SENTENCE_END.split(text.strip()) if part.strip()]
    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        current = f"{current} {sentence}".strip()
        if len(current) >= APPROX_PARAGRAPH_CHARS:
            paragraphs.append(current)
            current = ""
    if current:
        paragraphs.append(current)
    total_chars = sum(len(item) for item in paragraphs)
    if not total_chars:
        return []
    rows: list[TimedText] = []
    cursor = start
    for item in paragraphs:
        span = (end - start) * len(item) / total_chars
        rows.append((item, cursor, cursor + span))
        cursor += span
    return rows


@dataclass
class CloudTranscriber:
    """Вызовы шлюза для кусков одной записи. Живёт, пока идёт разбор материала.

    Один event loop на всё время, как у `CloudRecognizer`: `asyncio.run` на
    каждый кусок оставляет клиенту провайдера закрытый loop и сыплет
    `Event loop is closed` в лог воркера.
    """

    session: Session
    transport: OpenAICompatibleTransport | None = None
    retry_backoff: Sequence[float] = RETRY_BACKOFF_SECONDS
    sleep: Callable[[float], None] = time.sleep
    _loop: asyncio.AbstractEventLoop | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def close(self) -> None:
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    def transcribe(self, wav: bytes, chunk_start: float, chunk_end: float) -> dict[str, Any]:
        """Один кусок → словарь для чекпоинта: реплики со временем от начала записи."""
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        result = None
        for attempt, pause in enumerate((0.0, *self.retry_backoff)):
            if pause:
                self.sleep(pause)
            try:
                result = self._loop.run_until_complete(
                    ModelGateway(self.session, self.transport).transcribe(
                        wav, "wav", role=SPEECH_ROLE, timestamps=True
                    )
                )
                break
            except AiGatewayError as error:
                # Ключ, лимиты стоимости и «модель не умеет аудио» временем не
                # лечатся — повторять только то, что похоже на сбой сети провайдера.
                if error.code not in RETRYABLE_PROVIDER_CODES or attempt >= len(self.retry_backoff):
                    raise
                log.warning("кусок записи не расшифрован (%s), повтор: %s", error.code, error)
        assert result is not None
        length = chunk_end - chunk_start
        timed = [
            (item.text, chunk_start + item.start, chunk_start + min(item.end, length))
            for item in result.segments
            if item.text.strip()
        ]
        approximate = False
        if not timed and result.text.strip():
            timed = approximate_segments(result.text, chunk_start, chunk_end)
            approximate = True
        return {
            "start": chunk_start,
            "end": chunk_end,
            "model": result.actual_model_id,
            "approximate": approximate,
            "segments": [list(item) for item in timed],
        }


def transcribe_cloud(
    path: Path,
    transcriber: CloudTranscriber,
    workdir: Path,
    *,
    done: dict[int, dict[str, Any]],
    save_chunk: Callable[[int, dict[str, Any]], None],
    progress: ProgressCallback,
    decode: Callable[[Path, Path], int] = decode_pcm,
) -> ParsedPage:
    """Расшифровать запись по кускам, сохраняя каждый готовый.

    :param done: уже готовые куски из чекпоинта; повтор после сбоя начинается
        с первого недостающего и не платит за прочитанное второй раз.
    :param save_chunk: записать готовый кусок в чекпоинт задачи.
    :param progress: «секунд готово, секунд всего» → продолжать ли.
    """
    pcm_path = workdir / "audio.pcm"
    samples = decode(path, pcm_path)
    if samples < SAMPLE_RATE // 2:
        raise RuntimeError("В аудио нет звука: запись короче полсекунды")
    pcm = np.memmap(pcm_path, dtype="<i2", mode="r", shape=(samples,))
    duration = samples / SAMPLE_RATE
    plan = plan_chunks(pcm)
    results: dict[int, dict[str, Any]] = dict(done)
    if not progress(sum(item["end"] - item["start"] for item in results.values()), duration):
        raise TranscriptionCancelled
    for index, (first, last) in enumerate(plan):
        if index in results:
            continue
        start, end = first / SAMPLE_RATE, last / SAMPLE_RATE
        chunk = pcm[first:last]
        if is_silent(chunk):
            results[index] = {"start": start, "end": end, "model": "", "approximate": False,
                              "segments": []}
        else:
            try:
                results[index] = transcriber.transcribe(wav_bytes(chunk), start, end)
            except AiGatewayError as error:
                raise TranscriptionFailed(
                    f"Расшифровка остановилась на {int(start // 60):02d}:{int(start % 60):02d}: "
                    f"{error}. Готовые части сохранены — «Повторить» продолжит с этого места."
                ) from error
        save_chunk(index, results[index])
        finished = sum(item["end"] - item["start"] for item in results.values())
        if not progress(finished, duration):
            raise TranscriptionCancelled
    rows: list[TimedText] = [
        (str(text), float(begin), float(finish))
        for index in sorted(results)
        for text, begin, finish in results[index]["segments"]
    ]
    models = {item["model"] for item in results.values() if item["model"]}
    diagnostics = [f"asr_cloud:{model}" for model in sorted(models)]
    if any(item["approximate"] for item in results.values()):
        diagnostics.append("approximate_timestamps")
    return page_from_segments(rows, duration, diagnostics)
