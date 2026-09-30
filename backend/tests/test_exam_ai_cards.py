"""ИИ предлагает проверяемые экзаменационные карточки перед записью в Банк."""

import json

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy import select

from app.ai.gateway import ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.background.registry import get_job, list_jobs
from app.cards.generate import (
    generate_cards,
    queue_card_generation,
    review_card_generation,
    update_card_proposal,
)
from app.cards.schemas import (
    CardCreate,
    CardGenerateBatchWrite,
    CardGenerateWrite,
    CardProposalUpdate,
)
from app.cards.service import create_card
from app.models import (
    BackgroundJob,
    Card,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
)
from app.projects.errors import ProjectDomainError


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["connections", "understanding"])
@pytest.mark.parametrize("question,source,front,back,quote", [
    (
        "Почему меняется скорость реакции?",
        "Повышение температуры ускоряет реакцию, если остальные условия одинаковы.",
        "При каком условии сравнивают скорость реакции?",
        "Когда остальные условия одинаковы.",
        "если остальные условия одинаковы",
    ),
    (
        "Почему росло недовольство властью?",
        "Рост налогов уменьшал доход крестьян и усиливал недовольство властью.",
        "Почему рост налогов усиливал недовольство властью?",
        "Он уменьшал доход крестьян.",
        "уменьшал доход крестьян",
    ),
])
async def test_generate_review_and_accept_supported_card(
    session, ai_config, mode, question, source, front, back, quote
):
    del ai_config
    project = make_exam_project(session)
    node = make_topic_node(session, project, title=question)
    other = make_topic_node(session, project, title="Другой вопрос")
    session.add(ReferenceAnswer(
        project_id=project.id, program_node_id=node.id, text=source,
        origin_kind=ReferenceAnswerOrigin.MANUAL,
        match_method=ReferenceAnswerMatchMethod.MANUAL,
        is_confirmed=True, is_active=True, revision=1,
    ))
    session.add(ReferenceAnswer(
        project_id=project.id, program_node_id=other.id, text=source,
        origin_kind=ReferenceAnswerOrigin.MANUAL,
        match_method=ReferenceAnswerMatchMethod.MANUAL,
        is_confirmed=True, is_active=True, revision=1,
    ))
    session.commit()
    existing_front = "Какой фактор нужно учитывать при сравнении?"
    create_card(session, project.id, CardCreate(
        program_node_id=node.id, front=existing_front, back="При прочих равных."
    ))
    fake = FakeTransport(completions=[ProviderCompletion(
        content=json.dumps({"candidates": [
            {
                "front": front,
                "back": back, "hint": None,
                "source_kind": "reference", "fragment_id": None,
                "evidence_quote": quote,
            },
            {
                "front": existing_front + "!", "back": "При прочих равных.",
                "hint": None, "source_kind": "reference", "fragment_id": None,
                "evidence_quote": quote,
            },
            {
                "front": "Какая формула энергии активации?", "back": "Неизвестна",
                "hint": None, "source_kind": "reference", "fragment_id": None,
                "evidence_quote": "Формула энергии активации",
            },
        ]}, ensure_ascii=False),
        actual_model_id="test/structured-model", usage=ProviderUsage(),
    )])

    proposal = await generate_cards(
        session, ModelGateway(session, fake), project.id,
        CardGenerateWrite(program_node_id=node.id, mode=mode),
    )
    assert len(proposal.candidates) == 1
    assert session.scalar(select(Card).where(Card.generation_run_id == proposal.run_id)) is None
    candidate = proposal.candidates[0]
    assert candidate.source.kind == "reference"
    assert f'"mode": "{mode}"' in fake.complete_requests[0]["messages"][1]["content"]

    command = CardCreate(
        program_node_id=node.id, front="Исправленная лицевая сторона?",
        back="Исправленный короткий ответ.", source=candidate.source,
        generation_run_id=proposal.run_id, generation_candidate_index=candidate.index,
    )
    with pytest.raises(ProjectDomainError) as wrong_unit:
        create_card(session, project.id, command.model_copy(update={"program_node_id": other.id}))
    assert wrong_unit.value.code == "card_generation_unavailable"

    accepted = create_card(session, project.id, command)
    row = session.get(Card, accepted.id)
    assert row is not None and row.generation_run_id == proposal.run_id
    assert row.source_snapshot["generation"]["evidence_quote"] in source
    assert accepted.front == "Исправленная лицевая сторона?"


@pytest.mark.asyncio
async def test_generate_without_source_never_calls_model(session, ai_config):
    del ai_config
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Без материала")
    fake = FakeTransport()
    with pytest.raises(ProjectDomainError) as missing:
        await generate_cards(session, ModelGateway(session, fake), project.id,
                             CardGenerateWrite(program_node_id=node.id))
    assert missing.value.code == "card_generation_no_source"
    assert fake.complete_calls == 0


def test_background_generation_survives_review_and_tracks_decisions(session, ai_config):
    del ai_config
    project = make_exam_project(session)
    nodes = [
        make_topic_node(session, project, title="Причины изменений"),
        make_topic_node(session, project, title="Следствия изменений"),
    ]
    for node in nodes:
        session.add(ReferenceAnswer(
            project_id=project.id, program_node_id=node.id,
            text="Повышение температуры ускоряет реакцию при одинаковых условиях.",
            origin_kind=ReferenceAnswerOrigin.MANUAL,
            match_method=ReferenceAnswerMatchMethod.MANUAL,
            is_confirmed=True, is_active=True, revision=1,
        ))
    session.commit()
    job_id = queue_card_generation(session, project.id, CardGenerateBatchWrite(
        program_node_ids=[node.id for node in nodes], mode="connections",
    ))
    assert get_job(session, job_id).state == "queued"
    replies = [ProviderCompletion(
        content=json.dumps({"candidates": [{
            "front": f"Как влияет температура на реакцию в случае {index}?",
            "back": "Ускоряет реакцию.",
            "hint": "Подумайте о скорости.",
            "source_kind": "reference", "fragment_id": None,
            "evidence_quote": "Повышение температуры ускоряет реакцию",
        }]}),
        actual_model_id="test/structured-model", usage=ProviderUsage(),
    ) for index in (1, 2)]
    process_ai_job(session, session.get(BackgroundJob, job_id),
                   ModelGateway(session, FakeTransport(completions=replies)))
    assert get_job(session, job_id).state == "completed"
    assert get_job(session, job_id).needs_review
    review = review_card_generation(session, project.id, job_id)
    assert len(review.groups) == 2
    first = review.groups[0]
    updated = update_card_proposal(
        session, project.id, job_id, first.program_node_id, first.candidates[0].index,
        CardProposalUpdate(front="Исправленный вопрос?", back="Ускоряет.", hint=None),
    )
    assert updated.groups[0].candidates[0].front == "Исправленный вопрос?"
    assert review_card_generation(session, project.id, job_id).groups[0].candidates[0].hint is None
    create_card(session, project.id, CardCreate(
        program_node_id=first.program_node_id, front="Исправленный вопрос?",
        back="Ускоряет.", source=first.candidates[0].source,
        generation_run_id=first.run_id,
        generation_candidate_index=first.candidates[0].index,
    ))
    refreshed = review_card_generation(session, project.id, job_id)
    assert refreshed.groups[0].candidates[0].status == "accepted"
    second = review.groups[1]
    update_card_proposal(
        session, project.id, job_id, second.program_node_id, second.candidates[0].index,
        CardProposalUpdate(front=second.candidates[0].front,
                           back=second.candidates[0].back, rejected=True),
    )
    refreshed = review_card_generation(session, project.id, job_id)
    assert refreshed.groups[1].candidates[0].status == "rejected"
    assert len(list_jobs(session, project_id=project.id, pending_review=True)) == 1
