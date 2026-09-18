"""Шлюз с FakeTransport: retries платят из одного устойчивого бюджета."""

from decimal import Decimal

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderError, ProviderUsage
from app.ai.schemas import AiMessage
from app.ai.settings import resolve_model
from app.coverage.budget import ResearchBudget, budget_usage
from app.models import AiRun
from app.projects.errors import ProjectConflictError, ProjectDomainError
from tests.test_coverage import first_task, launch, setup_source


class Answer(BaseModel):
    answer: str


def completion(text):
    return ProviderCompletion(
        content=text,
        actual_model_id="test/structured-model",
        request_id="test",
        usage=ProviderUsage(input_tokens=20, output_tokens=10, cost_usd=Decimal("0.001")),
    )


@pytest.mark.asyncio
async def test_schema_repair_and_provider_retry_share_persistent_budget(session, ai_config):
    project, _, material = setup_source(session)
    run_id, job, token, _ = launch(session, project, material, limits={"max_calls": 3})
    task = first_task(session, run_id)
    fake = FakeTransport(
        completions=[
            ProviderError("ai_timeout", "timeout"),
            completion('{"bad":true}'),
            completion('{"answer":"ok"}'),
        ]
    )
    request = AiTextRequest(
        role="material_text_cleanup",
        response_model=Answer,
        messages=[AiMessage(role="user", content="fixture")],
        project_id=project.id,
        job_id=job.id,
        context_manifest=[{"coverage_task_id": str(task.id)}],
        budget_context=ResearchBudget(session, token, task.id),
    )
    result = await ModelGateway(session, fake, retry_backoff=(0, 0)).complete(request)
    assert result.value.answer == "ok" and fake.complete_calls == 3
    usage = budget_usage(session, run_id)
    assert usage["calls"] == 3 and usage["uncertain_calls"] == 1
    assert usage["cost_usd"] >= Decimal("0.002")
    assert session.scalar(select(AiRun)).job_id == job.id


@pytest.mark.asyncio
async def test_budget_stops_before_retry_and_closes_ai_run(session, ai_config):
    project, _, material = setup_source(session)
    run_id, job, token, _ = launch(session, project, material, limits={"max_calls": 1})
    fake = FakeTransport(completions=[ProviderError("ai_timeout", "timeout"), completion("{}")])
    request = AiTextRequest(
        role="material_text_cleanup",
        response_model=Answer,
        messages=[AiMessage(role="user", content="fixture")],
        job_id=job.id,
        budget_context=ResearchBudget(session, token, first_task(session, run_id).id),
    )
    with pytest.raises(ProjectConflictError) as error:
        await ModelGateway(session, fake, retry_backoff=(0,)).complete(request)
    assert error.value.code == "coverage_budget_exhausted"
    assert fake.complete_calls == 1
    assert session.scalar(select(AiRun)).status == "cancelled"


def test_coverage_role_never_uses_default_model_silently(session, ai_config):
    with pytest.raises(ProjectDomainError) as error:
        resolve_model(session, "coverage_overview")
    assert error.value.code == "ai_model_not_configured"
