"""Расшифровка аудиоматериала: два способа, нарезка, чекпоинт и отказы без модели.

Провайдер подменён заглушкой, декодер файла — синтетическим звуком: проверяется
решение конвейера (что и когда уходит наружу, что сохраняется, что говорим
человеку), а не Whisper и не FFmpeg.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.ai.provider import (
    FakeTransport,
    ProviderError,
    ProviderTranscription,
    ProviderUsage,
    TimedSegment,
)
from app.background import registry
from app.materials import audio_job, library
from app.materials.parsers import cloud_asr
from app.materials.parsers.audio import TranscriptionCancelled, page_from_segments
from app.materials.parsers.cloud_asr import (
    CHUNK_SECONDS,
    CUT_WINDOW_SECONDS,
    SAMPLE_RATE,
    CloudTranscriber,
    TranscriptionFailed,
    approximate_segments,
    plan_chunks,
    transcribe_cloud,
)
from app.materials.schemas import ProcessingStart
from app.models import (
    AiRoleSetting,
    AiSettings,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    MaterialSourceKind,
    ParserMode,
    ProcessingStage,
    utc_now,
)
from app.ocr import speech
from app.projects.errors import ProjectConflictError
from tests.test_ai_speech import WHISPER, speech_config  # noqa: F401  (фикстура)

MODEL = WHISPER


def _tone(seconds: float, level: int = 3000) -> np.ndarray:
    """Звук, который не считается тишиной."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (np.sin(2 * np.pi * 220 * t) * level).astype("<i2")


def _pcm(*parts: np.ndarray) -> np.ndarray:
    return np.concatenate(parts)


def _decoder(pcm: np.ndarray):
    """Подмена `decode_pcm`: пишет готовый звук туда, куда его ждёт транскрибер."""

    def decode(path: Path, dest: Path) -> int:
        del path
        dest.write_bytes(np.asarray(pcm, dtype="<i2").tobytes())
        return len(pcm)

    return decode


def _reply(text: str, *, timed: bool = True, length: float = 60.0) -> ProviderTranscription:
    segments = (TimedSegment(0.0, length, text),) if timed else ()
    return ProviderTranscription(
        text=text, actual_model_id=MODEL, usage=ProviderUsage(cost_usd=Decimal("0.001")),
        segments=segments,
    )


# ── Нарезка ──────────────────────────────────────────────────────────────────


def test_short_recording_is_one_chunk() -> None:
    pcm = _tone(90)
    assert plan_chunks(pcm) == [(0, len(pcm))]


def test_long_recording_is_cut_in_the_quietest_place_before_the_boundary() -> None:
    # 12 минут речи с паузой на 4:40 — в окне поиска перед плановой границей 5:00.
    pause_at = CHUNK_SECONDS - 20
    pcm = _pcm(_tone(pause_at), np.zeros(SAMPLE_RATE, dtype="<i2"), _tone(12 * 60 - pause_at - 1))

    chunks = plan_chunks(pcm)

    assert len(chunks) == 3
    first_cut = chunks[0][1] / SAMPLE_RATE
    assert pause_at <= first_cut <= pause_at + 1.0, "граница должна лечь в паузу, а не в слово"


def test_chunks_cover_the_recording_without_gaps_and_stay_under_the_provider_limit() -> None:
    pcm = _tone(23 * 60 + 17)
    chunks = plan_chunks(pcm)

    assert chunks[0][0] == 0 and chunks[-1][1] == len(pcm)
    assert all(a[1] == b[0] for a, b in zip(chunks, chunks[1:], strict=False))
    longest = max(end - start for start, end in chunks) / SAMPLE_RATE
    assert longest <= CHUNK_SECONDS + CUT_WINDOW_SECONDS
    # 2 байта на отсчёт: кусок обязан влезать в потолок шлюза с запасом.
    assert longest * SAMPLE_RATE * 2 < 20 * 1024 * 1024


def test_approximate_times_fill_the_chunk_and_follow_text_length() -> None:
    text = "Первая фраза. " * 30 + "Вторая длиннее и продолжается ещё немного."
    rows = approximate_segments(text, 100.0, 160.0)

    assert rows[0][1] == 100.0
    assert rows[-1][2] == pytest.approx(160.0)
    assert all(a[2] == pytest.approx(b[1]) for a, b in zip(rows, rows[1:], strict=False))


def test_page_needs_speech() -> None:
    with pytest.raises(RuntimeError, match="не удалось распознать речь"):
        page_from_segments([], 30.0)


# ── Облачная расшифровка ─────────────────────────────────────────────────────


def _run_cloud(
    session: Session,
    fake: FakeTransport,
    pcm: np.ndarray,
    tmp_path: Path,
    *,
    done: dict | None = None,
    progress=lambda done_s, total_s: True,
):
    saved: dict[int, dict] = {}
    transcriber = CloudTranscriber(session, fake, retry_backoff=(0.01, 0.01), sleep=lambda _: None)
    # Своя папка на запуск, как у воркера: на Windows memmap держит файл открытым.
    workdir = tmp_path / uuid4().hex
    workdir.mkdir()
    try:
        page = transcribe_cloud(
            tmp_path / "in.ogg",
            transcriber,
            workdir,
            done=done or {},
            save_chunk=saved.__setitem__,
            progress=progress,
            decode=_decoder(pcm),
        )
    finally:
        transcriber.close()
    return page, saved


def test_cloud_transcription_sends_chunks_and_offsets_times(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    fake = FakeTransport(
        transcriptions=[_reply("первый кусок", length=290), _reply("второй кусок")]
    )
    pcm = _pcm(_tone(CHUNK_SECONDS + 20), _tone(240))

    page, saved = _run_cloud(session, fake, pcm, tmp_path)

    assert [item["timestamps"] for item in fake.transcribe_requests] == [True, True]
    assert all(item["format"] == "wav" for item in fake.transcribe_requests)
    assert sorted(saved) == [0, 1]
    texts = [element.text for element in page.elements]
    assert texts == ["первый кусок", "второй кусок"]
    # Время второго куска отсчитывается от начала записи, а не от начала куска.
    assert page.elements[1].time_from >= CHUNK_SECONDS - CUT_WINDOW_SECONDS
    assert "asr_cloud:" + MODEL in page.diagnostics
    assert "approximate_timestamps" not in page.diagnostics


def test_text_only_answer_gets_approximate_times_and_says_so(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    fake = FakeTransport(transcriptions=[_reply("Одна фраза. Вторая фраза.", timed=False)])

    page, _ = _run_cloud(session, fake, _tone(60), tmp_path)

    assert "approximate_timestamps" in page.diagnostics
    assert page.elements[0].time_from == 0.0


def test_silent_chunk_is_not_sent_to_the_paid_model(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    fake = FakeTransport(transcriptions=[_reply("после тишины")])
    silence = np.zeros(CHUNK_SECONDS * SAMPLE_RATE + 40 * SAMPLE_RATE, dtype="<i2")
    pcm = _pcm(silence, _tone(60))

    page, saved = _run_cloud(session, fake, pcm, tmp_path)

    assert len(fake.transcribe_requests) == 1
    assert saved[0]["segments"] == []
    assert [element.text for element in page.elements] == ["после тишины"]


def test_retry_after_a_failure_does_not_pay_for_finished_chunks_again(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    pcm = _pcm(_tone(CHUNK_SECONDS + 20), _tone(240))
    # Первый кусок проходит, второй три раза подряд не отвечает: попытки кончились.
    unavailable = ProviderError("ai_provider_unavailable", "нет связи")
    fake = FakeTransport(
        transcriptions=[_reply("готово"), unavailable, unavailable, unavailable, unavailable]
    )
    saved: dict[int, dict] = {}
    transcriber = CloudTranscriber(
        session, fake, retry_backoff=(0.0, 0.0, 0.0), sleep=lambda _: None
    )
    first_dir = tmp_path / "first"
    first_dir.mkdir()
    with pytest.raises(TranscriptionFailed, match="«Повторить» продолжит"):
        transcribe_cloud(
            tmp_path / "in.ogg", transcriber, first_dir, done={},
            save_chunk=saved.__setitem__, progress=lambda *_: True, decode=_decoder(pcm),
        )
    transcriber.close()
    assert list(saved) == [0], "готовый кусок должен пережить сбой"

    retry = FakeTransport(transcriptions=[_reply("второй")])
    page, _ = _run_cloud(session, retry, pcm, tmp_path, done=saved)

    assert len(retry.transcribe_requests) == 1, "уже прочитанное второй раз не покупается"
    assert [element.text for element in page.elements] == ["готово", "второй"]


def test_temporary_provider_failure_is_retried(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    fake = FakeTransport(
        transcriptions=[ProviderError("ai_rate_limited", "429"), _reply("прошло со второго раза")]
    )

    page, _ = _run_cloud(session, fake, _tone(30), tmp_path)

    assert len(fake.transcribe_requests) == 2
    assert page.elements[0].text == "прошло со второго раза"


def test_bad_credentials_are_not_retried(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    fake = FakeTransport(
        transcriptions=[ProviderError("ai_invalid_credentials", "401"), _reply("x")]
    )

    with pytest.raises(TranscriptionFailed):
        _run_cloud(session, fake, _tone(30), tmp_path)

    assert len(fake.transcribe_requests) == 1


def test_cancelled_task_stops_before_the_next_paid_call(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    fake = FakeTransport(transcriptions=[_reply("a"), _reply("b")])
    calls = {"n": 0}

    def progress(done_s: float, total_s: float) -> bool:
        calls["n"] += 1
        return calls["n"] < 2  # первое обращение — до работы, второе — после первого куска

    with pytest.raises(TranscriptionCancelled):
        _run_cloud(session, fake, _pcm(_tone(CHUNK_SECONDS + 20), _tone(240)), tmp_path,
                   progress=progress)

    assert len(fake.transcribe_requests) == 1


def test_recording_without_sound_is_an_error_not_an_empty_material(
    session: Session, speech_config, tmp_path: Path  # noqa: F811
) -> None:
    del speech_config
    with pytest.raises(RuntimeError, match="нет звука"):
        _run_cloud(session, FakeTransport(), np.zeros(100, dtype="<i2"), tmp_path)


# ── Ход и чекпоинт задачи ────────────────────────────────────────────────────


def _audio_material(session: Session, seed: str = "a1") -> Material:
    material = Material(
        id=uuid4(),
        sha256=seed.rjust(64, "0"),
        original_name="audio.ogg",
        storage_path=f"materials/{seed}.ogg",
        media_type="audio/ogg",
        source_kind=MaterialSourceKind.AUDIO,
        size_bytes=10,
        page_count=1,
        active_parse_revision=0,
        outline=[],
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(material)
    session.commit()
    return material


def _job(session: Session, material: Material, mode: ParserMode) -> BackgroundJob:
    job = BackgroundJob(
        material_id=material.id,
        kind=BackgroundJobKind.PARSE,
        state=BackgroundJobState.RUNNING,
        stage=ProcessingStage.EXTRACT,
        parser_mode=mode,
        done=0,
        total=1,
        checkpoint={"revision": 1, "selected_pages": [1], "next_index": 0},
        diagnostics=[],
        pause_requested=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(job)
    session.commit()
    return job


def test_progress_counts_minutes_and_detects_cancellation(session: Session) -> None:
    job = _job(session, _audio_material(session), ParserMode.CLOUD)
    progress = audio_job._Progress(session, job.id)

    assert progress(150.0, 600.0) is True
    session.refresh(job)
    assert (job.done, job.total) == (2, 10), "минуты записи, а не «страниц 0 из 1»"

    session.delete(job)
    session.commit()
    progress._last = 0.0  # прошёл интервал: следующая запись ходит в БД
    assert progress(300.0, 600.0) is False, "задачи нет — расшифровку надо бросить"


def test_cloud_pages_keep_finished_chunks_in_the_task_checkpoint(
    session: Session, speech_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    del speech_config
    job = _job(session, _audio_material(session), ParserMode.CLOUD)
    fake = FakeTransport(transcriptions=[_reply("готово")])
    monkeypatch.setattr(cloud_asr, "decode_pcm", _decoder(_tone(45)))
    monkeypatch.setattr(
        audio_job, "CloudTranscriber", lambda db: CloudTranscriber(db, fake, retry_backoff=())
    )
    monkeypatch.setattr(audio_job, "transcribe_cloud", _with_decoder(_decoder(_tone(45))))

    pages = list(audio_job.transcribe_pages(session, job.id, tmp_path / "in.ogg", ParserMode.CLOUD))

    assert [element.text for element in pages[0].elements] == ["готово"]
    session.refresh(job)
    assert "0" in job.checkpoint["audio"]["chunks"]


def _with_decoder(decode):
    def call(*args, **kwargs):
        return transcribe_cloud(*args, decode=decode, **kwargs)

    return call


# ── Готовность способов и подписи ────────────────────────────────────────────


def _cloud(session: Session):
    return next(item for item in speech.speech_engines(session) if item.mode == ParserMode.CLOUD)


def test_local_is_always_offered_and_cloud_explains_what_is_missing(session: Session) -> None:
    modes = speech.speech_engines(session)
    assert [item.mode for item in modes] == [ParserMode.FAST, ParserMode.CLOUD]
    assert modes[0].available is True

    # Ничего не настроено — внешние модели выключены.
    assert _cloud(session).available is False
    assert "выключены" in _cloud(session).status_detail

    row = session.get(AiSettings, 1) or AiSettings(id=1)
    row.external_models_enabled = True
    session.add(row)
    session.commit()
    assert "Не выбрана модель" in _cloud(session).status_detail


def test_cloud_needs_a_key(session: Session, speech_config) -> None:  # noqa: F811
    provider = session.get(type(session.query(AiSettings).one()), 1)
    del provider
    from app.models import AiProviderConnection

    connection = session.query(AiProviderConnection).one()
    connection.api_key_ciphertext = None
    session.commit()

    cloud = _cloud(session)
    assert cloud.available is False
    assert "нет ключа" in cloud.status_detail
    assert cloud.model_label == speech_config.model_id


def test_cloud_is_ready_when_model_and_key_exist(session: Session, speech_config) -> None:  # noqa: F811
    cloud = _cloud(session)
    assert cloud.available is True
    assert cloud.model_label == speech_config.model_id


def test_disabled_role_switches_cloud_off(session: Session, speech_config) -> None:  # noqa: F811
    del speech_config
    session.add(AiRoleSetting(role=speech.SPEECH_ROLE, enabled=False, parameters={}))
    session.commit()

    assert "выключена" in _cloud(session).status_detail


def test_starting_cloud_transcription_without_a_model_is_refused(session: Session) -> None:
    material = _audio_material(session, "b1")

    with pytest.raises(ProjectConflictError) as error:
        library.start_processing_core(
            session, material.id, ProcessingStart(parser_mode=ParserMode.CLOUD)
        )

    assert error.value.code == "parser_mode_unavailable"


def test_starting_local_transcription_needs_no_external_model(session: Session) -> None:
    material = _audio_material(session, "b2")

    task = library.start_processing_core(
        session, material.id, ProcessingStart(parser_mode=ParserMode.FAST)
    )

    assert task.parser_mode == ParserMode.FAST


def test_background_row_names_the_speech_engine_not_ocr(session: Session, speech_config) -> None:  # noqa: F811
    material = _audio_material(session, "c1")
    local = _job(session, material, ParserMode.FAST)

    read = registry.get_job(session, local.id)
    assert read.model_label == "Whisper small"
    assert read.progress_unit == "минут"

    local.parser_mode = ParserMode.CLOUD
    session.commit()
    read = registry.get_job(session, local.id)
    assert read.model_label == speech_config.model_id
    assert read.progress_unit == "минут"


# ── Воркер целиком и локальный Whisper ───────────────────────────────────────


def test_worker_turns_a_cloud_audio_job_into_a_ready_material(
    session: Session, speech_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    from app.materials import worker
    from app.materials.storage import material_path
    from app.models import MaterialPage, MaterialState

    del speech_config
    material = _audio_material(session, "d1")
    source = material_path(material.storage_path)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"not decoded: decoder is stubbed")
    job = _job(session, material, ParserMode.CLOUD)
    fake = FakeTransport(transcriptions=[_reply("расшифровано облаком", length=40)])
    monkeypatch.setattr(
        audio_job, "CloudTranscriber", lambda db: CloudTranscriber(db, fake, retry_backoff=())
    )
    monkeypatch.setattr(audio_job, "transcribe_cloud", _with_decoder(_decoder(_tone(45))))

    worker.process_parse_job(session, job)

    session.expire_all()
    stored = session.get(Material, material.id)
    assert stored is not None and stored.status == MaterialState.READY, stored.error
    page = session.query(MaterialPage).filter_by(material_id=material.id).one()
    assert page.text == "расшифровано облаком"
    assert "asr_cloud:" + MODEL in page.diagnostics
    finished = session.get(BackgroundJob, job.id)
    assert finished is not None and finished.state == BackgroundJobState.COMPLETED
    # Модель страниц к записи не подключается: облачный OCR тут ни при чём.
    assert len(fake.transcribe_requests) == 1


def test_worker_reports_a_failed_cloud_chunk_and_keeps_finished_ones(
    session: Session, speech_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    from app.materials import worker
    from app.materials.storage import material_path
    from app.models import MaterialState

    del speech_config
    material = _audio_material(session, "d2")
    source = material_path(material.storage_path)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"x")
    job = _job(session, material, ParserMode.CLOUD)
    pcm = _pcm(_tone(CHUNK_SECONDS + 20), _tone(240))
    unavailable = ProviderError("ai_provider_unavailable", "нет связи")
    fake = FakeTransport(transcriptions=[_reply("первый"), unavailable, unavailable])
    monkeypatch.setattr(
        audio_job, "CloudTranscriber", lambda db: CloudTranscriber(db, fake, retry_backoff=(0.0,))
    )
    monkeypatch.setattr(audio_job, "transcribe_cloud", _with_decoder(_decoder(pcm)))

    worker.process_parse_job(session, job)

    session.expire_all()
    failed = session.get(BackgroundJob, job.id)
    assert failed is not None and failed.state == BackgroundJobState.FAILED
    assert "«Повторить» продолжит" in (failed.error or "")
    assert list(failed.checkpoint["audio"]["chunks"]) == ["0"]
    stored = session.get(Material, material.id)
    assert stored is not None and stored.status == MaterialState.FAILED


class _FakeWhisperSegment:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text, self.start, self.end = text, start, end


def _install_fake_whisper(monkeypatch: pytest.MonkeyPatch, segments: list) -> None:
    import sys
    import types

    class WhisperModel:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def transcribe(self, *args, **kwargs):
            del args, kwargs
            return iter(segments), types.SimpleNamespace(duration=100.0)

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = WhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


def test_local_whisper_reports_progress_and_labels_the_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.materials.parsers.audio import parse_audio

    _install_fake_whisper(
        monkeypatch,
        [_FakeWhisperSegment(" привет ", 0, 40), _FakeWhisperSegment("", 40, 50),
         _FakeWhisperSegment("мир", 50, 100)],
    )
    seen: list[tuple[float, float]] = []

    def progress(done_s: float, total_s: float) -> bool:
        seen.append((done_s, total_s))
        return True

    page = parse_audio(tmp_path / "a.ogg", progress)

    assert seen == [(40.0, 100.0), (50.0, 100.0), (100.0, 100.0)]
    assert [element.text for element in page.elements] == ["привет", "мир"]
    assert page.diagnostics == ("asr_local:Whisper small",)


def test_local_whisper_stops_when_the_task_is_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.materials.parsers.audio import parse_audio

    _install_fake_whisper(
        monkeypatch, [_FakeWhisperSegment("a", 0, 10), _FakeWhisperSegment("b", 10, 20)]
    )

    with pytest.raises(TranscriptionCancelled):
        parse_audio(tmp_path / "a.ogg", lambda *_: False)
