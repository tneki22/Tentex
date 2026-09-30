"""Контракт входных данных и версии кэша ИИ-оценки подготовки."""

import json
from datetime import date, time

from conftest import make_exam_project

from app.ai.roles import ROLE_SPECS
from app.models import ExamFormat, StartingLevel, StudyFormat, TargetOutcome
from app.projects import preparation_ai


def test_estimate_request_includes_every_workload_factor(session):
    project = make_exam_project(session)
    command = preparation_ai.PreparationEstimateWrite(
        exam_date=date.today(),
        exam_time=time(9, 30),
        item_count=20,
        exam_format=ExamFormat.QUESTIONS_TASKS,
        starting_level=StartingLevel.BEGINNER,
        target_outcome=TargetOutcome.MASTERY,
        study_format=StudyFormat.THEORY_AND_PRACTICE,
        has_answers=False,
        has_theory=True,
    )

    snapshot = preparation_ai._snapshot(session, project.id, command)
    request = preparation_ai._request(snapshot, False)
    content = request.messages[1].content
    payload = json.loads(
        content.removeprefix("<preparation_data>\n").removesuffix("\n</preparation_data>")
    )

    assert payload == {
        "exam_date": str(command.exam_date),
        "exam_time": "09:30:00",
        "item_count": 20,
        "exam_format": "questions_tasks",
        "starting_level": "beginner",
        "target_outcome": "mastery",
        "study_format": "theory_and_practice",
        "has_answers": False,
        "has_theory": True,
        "study_days": 1,
        "items_per_day": 20,
        "review_day_reserved": False,
    }


def test_estimate_role_version_invalidates_old_cached_advice():
    assert ROLE_SPECS["exam_preparation_estimate"].prompt_version == "preparation-estimate-v2"
