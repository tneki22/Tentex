"""Диспетчер фоновых задач-ролей ИИ (`app.ai.jobs.process_ai_job`, Ш2 плана).

Сценарий уборки страницы (`BackgroundJobKind.AI_CLEANUP`) выбран как самый
дешёвый в подготовке снимок: не нужен ни проект, ни программа — только
материал с одной страницей. Остальные роли ИИ используют тот же `run()` и
тот же диспетчер, поэтому отдельно не дублируются.
"""

import asyncio
import hashlib
from decimal import Decimal

from conftest import add_page_with_fragments, make_material
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import jobs as ai_jobs
from app.ai.gateway import ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.materials import ai_cleanup
from app.models import AiRun, BackgroundJob, BackgroundJobKind, BackgroundJobState


def _completion() -> ProviderCompletion:
    return ProviderCompletion(
        content='{"markdown":"# Чисто","changes":["Убраны опечатки"],"warnings":[]}',
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=50, output_tokens=10, cost_usd=Decimal("0.001")),
    )


class _SlowTransport(FakeTransport):
    """`FakeTransport` с задержкой перед ответом — нужна только затем, чтобы
    предельное время задачи (`DEADLINE_SECONDS`) успело истечь: у настоящего
    `FakeTransport.complete` нет ни одной точки приостановки, и в паре с
    `asyncio.timeout` таймер там никогда не успевает сработать."""

    def __init__(self, delay: float, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.delay = delay

    async def complete(self, **kwargs: object) -> ProviderCompletion:
        await asyncio.sleep(self.delay)
        return await super().complete(**kwargs)


def _material_with_page(session: Session, seed: str, text: str = "Исходный текст"):
    material = make_material(session, seed)
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=[text])
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    return material, source_hash


def _cleanup_job(session: Session, material, source_hash: str) -> BackgroundJob:
    command = ai_cleanup.CleanupRunWrite(expected_revision=1, expected_source_hash=source_hash)
    job = BackgroundJob(
        kind=BackgroundJobKind.AI_CLEANUP,
        project_id=None,
        material_id=material.id,
        state=BackgroundJobState.RUNNING,
        checkpoint={"command": command.model_dump(mode="json"), "page_number": 1},
    )
    session.add(job)
    session.commit()
    return job


def test_process_ai_job_completes_and_links_ai_run(session: Session, ai_config: str) -> None:
    del ai_config
    material, source_hash = _material_with_page(session, "a101")
    job = _cleanup_job(session, material, source_hash)
    gateway = ModelGateway(session, FakeTransport(completions=[_completion()]))

    process_ai_job(session, job, gateway)

    session.expire_all()
    finished = session.get(BackgroundJob, job.id)
    assert finished is not None
    assert finished.state == BackgroundJobState.COMPLETED
    assert finished.done == finished.total == 1
    assert finished.lease_owner is None
    run = session.scalar(select(AiRun).where(AiRun.job_id == job.id))
    assert run is not None
    assert run.status == "succeeded"
    assert run.response_payload is not None
    assert run.response_payload["markdown"] == "# Чисто"


def test_process_ai_job_deadline_exceeded_fails_with_russian_message(
    session: Session, ai_config: str, monkeypatch
) -> None:
    del ai_config
    material, source_hash = _material_with_page(session, "a102")
    job = _cleanup_job(session, material, source_hash)
    gateway = ModelGateway(session, _SlowTransport(delay=0.3, completions=[_completion()]))
    monkeypatch.setitem(ai_jobs.DEADLINE_SECONDS, BackgroundJobKind.AI_CLEANUP, 0.05)

    process_ai_job(session, job, gateway)

    session.expire_all()
    finished = session.get(BackgroundJob, job.id)
    assert finished is not None
    assert finished.state == BackgroundJobState.FAILED
    assert finished.error is not None and "0.05" in finished.error
    assert finished.lease_owner is None


def test_process_ai_job_cancelled_while_running_finishes_as_cancelled(
    session: Session, ai_config: str
) -> None:
    """Отменить уже идущий вызов модели нечем (Ш3: `registry.cancel_job`
    только выставляет `pause_requested` у running-задачи) — но результат не
    должен выглядеть завершённым, если пользователь его уже не ждёт."""
    del ai_config
    material, source_hash = _material_with_page(session, "a103")
    job = _cleanup_job(session, material, source_hash)
    job.pause_requested = True
    session.commit()
    gateway = ModelGateway(session, FakeTransport(completions=[_completion()]))

    process_ai_job(session, job, gateway)

    session.expire_all()
    finished = session.get(BackgroundJob, job.id)
    assert finished is not None
    assert finished.state == BackgroundJobState.CANCELLED
    # Деньги не теряются: вызов провайдера всё равно случился и записан.
    run = session.scalar(select(AiRun).where(AiRun.job_id == job.id))
    assert run is not None and run.status == "succeeded"


def test_process_ai_job_stale_snapshot_fails_with_domain_error_detail(
    session: Session, ai_config: str
) -> None:
    del ai_config
    material, source_hash = _material_with_page(session, "a104")
    job = _cleanup_job(session, material, source_hash)
    # Материал переразобран уже после того, как задача встала в очередь —
    # активной становится ревизия без такой страницы, и снимок должен
    # честно провалить задачу (ProjectDomainError), а не уронить воркер.
    material.active_parse_revision = 2
    session.commit()
    gateway = ModelGateway(session, FakeTransport(completions=[_completion()]))

    process_ai_job(session, job, gateway)

    session.expire_all()
    finished = session.get(BackgroundJob, job.id)
    assert finished is not None
    assert finished.state == BackgroundJobState.FAILED
    assert finished.error == "Страница не найдена"
