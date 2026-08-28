from pathlib import Path

import pytest
from conftest import link_material, make_exam_project, make_material
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.materials import service
from app.materials.external import _ReadableHtml, _validate_public_url, _youtube_id
from app.materials.parsers.native import inspect
from app.materials.schemas import ExamMaterialSlot, MaterialPurpose, MaterialUpdate
from app.models import ExamFormat, ProjectMaterial, SourceRole
from app.projects.errors import ProjectConflictError, ProjectDomainError
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


def test_material_settings_update_all_project_fields(session: Session) -> None:
    project = make_exam_project(session)
    material = make_material(session, "f1")
    link = link_material(session, project, material)

    result = service.update_material(
        session,
        project.id,
        material.id,
        MaterialUpdate(
            display_name="Ответы по предмету",
            source_role=SourceRole.MAIN,
            priority=3,
            instruction="Использовать таблицы как приложения",
            purposes=[MaterialPurpose.STUDY_SOURCE],
        ),
    )

    assert result.display_name == "Ответы по предмету"
    assert result.source_role == SourceRole.MAIN
    assert result.priority == 3
    assert result.instruction == "Использовать таблицы как приложения"
    assert result.attached_at == link.created_at
    assert session.get(ProjectMaterial, (project.id, material.id)).affects_program is True


def test_second_answers_file_requires_explicit_replacement(session: Session) -> None:
    project = make_exam_project(session)
    current = make_material(session, "f2")
    candidate = make_material(session, "f3")
    current_link = link_material(session, project, current)
    current_link.purposes = [MaterialPurpose.REFERENCE_ANSWERS.value]
    link_material(session, project, candidate)
    session.commit()

    with pytest.raises(ProjectConflictError) as caught:
        service.update_material(
            session,
            project.id,
            candidate.id,
            MaterialUpdate(purposes=[MaterialPurpose.REFERENCE_ANSWERS]),
        )

    assert caught.value.code == "reference_answers_already_set"


def test_separate_question_and_task_answer_slots_are_allowed(session: Session) -> None:
    project = make_exam_project(session)
    question_answers = make_material(session, "f6")
    task_answers = make_material(session, "f7")
    link_material(session, project, question_answers)
    link_material(session, project, task_answers)
    session.commit()

    question_result = service.update_material(
        session,
        project.id,
        question_answers.id,
        MaterialUpdate(
            purposes=[MaterialPurpose.REFERENCE_ANSWERS],
            exam_slot=ExamMaterialSlot.QUESTION_ANSWERS,
        ),
    )
    task_result = service.update_material(
        session,
        project.id,
        task_answers.id,
        MaterialUpdate(
            purposes=[MaterialPurpose.REFERENCE_ANSWERS],
            exam_slot=ExamMaterialSlot.TASK_ANSWERS,
        ),
    )

    assert question_result.exam_slot == ExamMaterialSlot.QUESTION_ANSWERS
    assert task_result.exam_slot == ExamMaterialSlot.TASK_ANSWERS


def test_duplicate_exam_slot_is_rejected(session: Session) -> None:
    project = make_exam_project(session)
    current = make_material(session, "f8")
    duplicate = make_material(session, "f9")
    current_link = link_material(session, project, current)
    current_link.purposes = [MaterialPurpose.EXAM_STRUCTURE.value]
    current_link.exam_slot = ExamMaterialSlot.QUESTION_LIST.value
    link_material(session, project, duplicate)
    session.commit()

    with pytest.raises(ProjectConflictError) as caught:
        service.update_material(
            session,
            project.id,
            duplicate.id,
            MaterialUpdate(
                purposes=[MaterialPurpose.EXAM_STRUCTURE],
                exam_slot=ExamMaterialSlot.QUESTION_LIST,
            ),
        )

    assert caught.value.code == "exam_slot_already_set"


def test_exam_slot_requires_matching_purpose(session: Session) -> None:
    project = make_exam_project(session)
    material = make_material(session, "fa")
    link_material(session, project, material)
    session.commit()

    with pytest.raises(ProjectConflictError) as caught:
        service.update_material(
            session,
            project.id,
            material.id,
            MaterialUpdate(
                purposes=[MaterialPurpose.STUDY_SOURCE],
                exam_slot=ExamMaterialSlot.TASK_ANSWERS,
            ),
        )

    assert caught.value.code == "exam_slot_purpose_mismatch"


def test_confirmed_answers_replacement_is_atomic(session: Session) -> None:
    project = make_exam_project(session)
    current = make_material(session, "f4")
    candidate = make_material(session, "f5")
    current_link = link_material(session, project, current)
    current_link.purposes = [MaterialPurpose.REFERENCE_ANSWERS.value]
    link_material(session, project, candidate)
    session.commit()

    result = service.update_material(
        session,
        project.id,
        candidate.id,
        MaterialUpdate(
            display_name="Новый эталон",
            source_role=SourceRole.REFERENCE,
            purposes=[MaterialPurpose.REFERENCE_ANSWERS],
            replace_reference_answers=True,
        ),
    )

    previous = session.get(ProjectMaterial, (project.id, current.id))
    assert previous.purposes == [MaterialPurpose.STUDY_SOURCE.value]
    assert result.purposes == [MaterialPurpose.REFERENCE_ANSWERS]
    assert result.display_name == "Новый эталон"
    assert result.source_role == SourceRole.REFERENCE
    assert session.get(ProjectMaterial, (project.id, candidate.id)).affects_program is False


def test_replacement_flag_requires_answers_purpose() -> None:
    with pytest.raises(ValidationError):
        MaterialUpdate(
            purposes=[MaterialPurpose.STUDY_SOURCE],
            replace_reference_answers=True,
        )
