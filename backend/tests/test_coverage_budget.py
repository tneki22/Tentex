"""Шлюз с FakeTransport: протокол обзора и retries используют устойчивый бюджет."""

import json
from decimal import Decimal

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderError, ProviderUsage
from app.ai.schemas import AiMessage
from app.ai.settings import resolve_model
from app.coverage.budget import ResearchBudget, budget_usage
from app.coverage.lifecycle import ExecutionToken
from app.coverage.protocol import CoverageOverviewExecutor, expand_compact_response
from app.coverage.queries import overview, run_read
from app.coverage.research import prepare_task, process_coverage_job, publish_packet
from app.models import AiProviderConnection, AiRun
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


def test_overview_protocol_runs_through_gateway_with_explicit_model(session, ai_config):
    project, _, material = setup_source(session)
    provider_id = session.scalar(select(AiProviderConnection.id))
    roles = {
        key: {"provider_id": provider_id, "model_id": ai_config}
        for key in ("overview", "research")
    }
    run_id, job, token, _ = launch(session, project, material, roles=roles)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    aliases = list(task_input.target_aliases.values())
    fake = FakeTransport(
        completions=[
            ProviderCompletion(
                content=json.dumps(
                    {
                        "decisions": [{
                            "from_target": aliases[0],
                            "to_target": aliases[-1],
                            "outcome": "service",
                            "reason": "fixture",
                            "parts": [],
                        }],
                        "section_descriptions": [{
                            "section": "Без заголовка",
                            "summary": "Тестовое описание раздела",
                        }],
                    },
                    ensure_ascii=False,
                ),
                actual_model_id=ai_config,
                usage=ProviderUsage(input_tokens=40, output_tokens=20),
            )
        ]
    )
    executor = CoverageOverviewExecutor(
        session,
        job.id,
        token,
        gateway=ModelGateway(session, fake, retry_backoff=()),
    )
    try:
        executed = executor(task_input)
    finally:
        executor.close()
    assert executed.call_receipt["requested_model"] == ai_config
    assert executed.call_receipt["actual_model"] == ai_config
    assert fake.complete_requests[0]["model"] == ai_config

    publish_packet(
        session,
        token,
        task_input,
        expand_compact_response(task_input, executed.decisions),
    )
    assert overview(session, project.id)["distribution"]["service"] == 3


def test_worker_path_runs_overview_without_explicit_executor(session, ai_config, monkeypatch):
    """Собственный исполнитель job — единственный боевой путь; тест проходит его целиком."""
    from app.coverage import protocol
    from app.models import BackgroundJob, BackgroundJobState

    project, topic, material = setup_source(session)
    provider_id = session.scalar(select(AiProviderConnection.id))
    roles = {
        key: {"provider_id": provider_id, "model_id": ai_config}
        for key in ("overview", "research")
    }
    run_id, job, _, _ = launch(session, project, material, roles=roles)
    task_input = prepare_task(
        session,
        ExecutionToken(run_id, job.checkpoint["coverage_generation"], job.lease_owner),
        first_task(session, run_id).id,
    )
    aliases = list(task_input.target_aliases.values())
    fake = FakeTransport(
        completions=[
            ProviderCompletion(
                content=json.dumps(
                    {
                        "decisions": [{
                            "from_target": aliases[0],
                            "to_target": aliases[-1],
                            "outcome": "outside_program",
                            "reason": "не относится к программе",
                            "parts": [],
                        }],
                        "section_descriptions": [],
                    },
                    ensure_ascii=False,
                ),
                actual_model_id=ai_config,
                usage=ProviderUsage(input_tokens=40, output_tokens=20),
            )
        ]
    )
    monkeypatch.setattr(
        protocol, "ModelGateway", lambda _session: ModelGateway(session, fake, retry_backoff=())
    )
    process_coverage_job(session, job)

    assert fake.complete_calls == 1
    assert session.get(BackgroundJob, job.id).state == BackgroundJobState.COMPLETED
    status = run_read(session, project.id, run_id)
    assert status["primary"]["inspected"] == 3 and status["outcomes"]["outside_program"] == 3
    assert status["costs"]["calls"] == 1
    assert overview(session, project.id)["material_ratio"]["value"] == 0.0
