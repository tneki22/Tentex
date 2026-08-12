from pathlib import Path

import pytest

from app.materials.external import _ReadableHtml, _validate_public_url, _youtube_id
from app.materials.parsers.native import inspect
from app.models import ExamFormat
from app.projects.errors import ProjectDomainError
from app.projects.importer import parse_exam_program


def test_web_snapshot_ignores_script_and_keeps_readable_blocks() -> None:
    parser = _ReadableHtml()
    parser.feed(
        "<html><head><title>Тест</title><script>bad()</script></head>"
        "<body><h1>Заголовок</h1><p>Первый абзац</p></body></html>"
    )
    assert parser.title == "Тест"
    assert parser.text() == "Заголовок\n\nПервый абзац"


def test_private_url_is_rejected_before_fetch() -> None:
    with pytest.raises(ProjectDomainError) as error:
        _validate_public_url("http://127.0.0.1/private")
    assert error.value.code == "material_url_private"


def test_youtube_url_extracts_video_id() -> None:
    assert _youtube_id("https://www.youtube.com/watch?v=abcdefghijk") == "abcdefghijk"
    assert _youtube_id("https://youtu.be/abcdefghijk") == "abcdefghijk"


def test_audio_is_accepted_for_deferred_local_transcription(tmp_path: Path) -> None:
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"not decoded during inspection")
    assert inspect(audio) == (1, 0, 60, ["audio_transcription_required"])


def test_exam_import_accepts_ocr_number_without_space() -> None:
    parsed = parse_exam_program("40) Первый вопрос\n41)Второй вопрос", ExamFormat.QUESTIONS)
    assert parsed.questions == 2
    assert [node.title for node in parsed.nodes] == ["Первый вопрос", "Второй вопрос"]
