import json
from datetime import date, time
from decimal import Decimal

import pytest
from conftest import make_exam_project
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.db import get_session
from app.main import create_app
from app.models import ExamFormat, StartingLevel, StudyFormat, TargetOutcome
from app.projects import preparation_ai
from app.projects.errors import ProjectDomainError


def _command(**overrides) -> preparation_ai.PreparationEstimateWrite:
    values = {
        "exam_date": date(2026, 9, 2),
        "exam_time": time(9, 0),
        "item_count": 42,
        "exam_format": ExamFormat.QUESTIONS,
        "starting_level": StartingLevel.FAMILIAR,
        "target_outcome": TargetOutcome.APPLICATION,
        "study_format": StudyFormat.THEORY_AND_PRACTICE,
        "has_answers": True,
        "has_theory": False,
    }
    return preparation_ai.PreparationEstimateWrite(**(values | overrides))


def _completion(*, minutes: int = 240) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(
            {
                "minutes_per_day": minutes,
                "rationale": "Четыре часа дают время на шесть вопросов и повторение.",
            }
        ),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(
            input_tokens=80,
            output_tokens=30,
            cost_usd=Decimal("0.001"),
        ),
    )


def test_schedule_reserves_last_day_and_distributes_items() -> None:
    schedule = preparation_ai.build_schedule(_command(), today=date(2026, 8, 25))

    assert schedule.study_days == 7
    assert schedule.items_per_day == 6
    assert schedule.review_day_reserved is True


def test_short_schedule_does_not_invent_review_day() -> None:
    schedule = preparation_ai.build_schedule(
        _command(exam_date=date(2026, 8, 26)),
        today=date(2026, 8, 25),
    )

    assert schedule.study_days == 1
    assert schedule.items_per_day == 42
    assert schedule.review_day_reserved is False


def test_past_exam_date_is_rejected() -> None:
    with pytest.raises(ProjectDomainError) as caught:
        preparation_ai.build_schedule(
            _command(exam_date=date(2026, 8, 24)),
            today=date(2026, 8, 25),
        )

    assert caught.value.code == "preparation_exam_date_past"


def test_zero_items_are_rejected_before_gateway_call() -> None:
    with pytest.raises(ValidationError):
        _command(item_count=0)


@pytest.mark.asyncio
async def test_preflight_reports_disabled_external_models(session: Session) -> None:
    project = make_exam_project(session)
    gateway = ModelGateway(session, FakeTransport())

    with pytest.raises(ProjectDomainError) as caught:
        await preparation_ai.preflight(session, gateway, project.id, _command())

    assert caught.value.code == "ai_disabled"


def test_http_preflight_validates_input_and_reports_disabled_models(
    session: Session,
) -> None:
    project = make_exam_project(session)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_model_gateway] = lambda: ModelGateway(
        session, FakeTransport()
    )
    client = TestClient(app, raise_server_exceptions=False)
    payload = _command().model_dump(mode="json")

    invalid = client.post(
        f"/api/projects/{project.id}/preparation-estimate/preflight",
        json={**payload, "item_count": 0},
    )
    disabled = client.post(
        f"/api/projects/{project.id}/preparation-estimate/preflight",
        json=payload,
    )

    assert invalid.status_code == 422
    assert disabled.status_code == 422
    assert disabled.json()["code"] == "ai_disabled"


@pytest.mark.asyncio
async def test_preflight_and_run_use_only_minimal_passport_fields(
    session: Session,
    ai_config: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del ai_config
    project = make_exam_project(session)
    fake = FakeTransport(completions=[_completion()])
    gateway = ModelGateway(session, fake)
    command = _command()
    monkeypatch.setattr(preparation_ai, "date", _FixedDate)

    preview = await preparation_ai.preflight(session, gateway, project.id, command)
    result = await preparation_ai.run(
        session,
        gateway,
        project.id,
        preparation_ai.PreparationEstimateRunWrite(
            **command.model_dump(),
            expected_input_hash=preview.input_hash,
        ),
    )

    assert result.minutes_per_day == 240
    assert result.study_days == 7
    assert result.items_per_day == 6
    assert result.review_day_reserved is True
    user_message = fake.complete_requests[0]["messages"][1]["content"]
    assert '"item_count": 42' in user_message
    assert "current_knowledge" not in user_message
    assert "instructor_requirements" not in user_message
    assert "exam_procedure" not in user_message

    cached_preview = await preparation_ai.preflight(session, gateway, project.id, command)
    cached_result = await preparation_ai.run(
        session,
        gateway,
        project.id,
        preparation_ai.PreparationEstimateRunWrite(
            **command.model_dump(),
            expected_input_hash=cached_preview.input_hash,
        ),
    )
    assert cached_preview.preflight.cached is True
    assert cached_result.cached is True
    assert len(fake.complete_requests) == 1


@pytest.mark.asyncio
async def test_invalid_minutes_leave_gateway_with_structured_output_error(
    session: Session,
    ai_config: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del ai_config
    project = make_exam_project(session)
    fake = FakeTransport(completions=[_completion(minutes=15)])
    gateway = ModelGateway(session, fake)
    command = _command()
    monkeypatch.setattr(preparation_ai, "date", _FixedDate)
    preview = await preparation_ai.preflight(session, gateway, project.id, command)

    with pytest.raises(ProjectDomainError) as caught:
        await preparation_ai.run(
            session,
            gateway,
            project.id,
            preparation_ai.PreparationEstimateRunWrite(
                **command.model_dump(),
                expected_input_hash=preview.input_hash,
            ),
        )

    assert caught.value.code == "ai_invalid_structured_output"


class _FixedDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(2026, 8, 25)
