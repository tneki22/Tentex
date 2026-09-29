"""ИИ предлагает проверяемые экзаменационные карточки перед записью в Банк."""

import json

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy import select

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.cards.generate import generate_cards
from app.cards.schemas import CardCreate, CardGenerateWrite
from app.cards.service import create_card
from app.models import Card, ReferenceAnswer, ReferenceAnswerMatchMethod, ReferenceAnswerOrigin
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
