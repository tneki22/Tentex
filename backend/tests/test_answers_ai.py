import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_answers_link import _answers_material, _program

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.bindings import answers_ai
from app.models import ProjectActionLog, ReferenceAnswer, ReferenceAnswerMatchMethod
from app.projects.errors import ProjectDomainError
from app.projects.program import undo_last_project_action


def _completion(boundaries: list[dict], skipped: list[int] | None = None) -> ProviderCompletion:
    payload = {"boundaries": boundaries, "skipped_questions": skipped or []}
    return ProviderCompletion(
        content=json.dumps(payload),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=200, output_tokens=80, cost_usd=Decimal("0.001")),
    )


def _boundary(candidate: int, question: int, confidence: str = "high", note: str = "") -> dict:
    return {"candidate": candidate, "question": question, "confidence": confidence, "note": note}


@pytest.mark.asyncio
async def test_preflight_estimates_a_single_batch(session: Session, ai_config: str) -> None:
    del ai_config
    project, nodes = _program(session, 2)
    material = _answers_material(
        session,
        project,
        [
            (nodes[0].title, [("Текст первого ответа без общих слов.", "paragraph", None)]),
            (nodes[1].title, [("Текст второго ответа тоже иной совсем.", "paragraph", None)]),
        ],
    )
    gateway = ModelGateway(session, FakeTransport())

    preview = await answers_ai.preflight_answers_ai(session, gateway, project.id, material.id)

    assert preview.candidate_count == 2
    assert preview.batch_count == 1
    assert preview.question_count == 2
    assert len(preview.calls) == 1


@pytest.mark.asyncio
async def test_run_and_apply_creates_answers_and_undo_restores(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project, nodes = _program(session, 2)
    bodies = [
        "Текст первого ответа без общих слов с заголовками.",
        "Текст второго ответа тоже совсем другой набор слов.",
    ]
    material = _answers_material(
        session,
        project,
        [
            (nodes[0].title, [(bodies[0], "paragraph", None)]),
            (nodes[1].title, [(bodies[1], "paragraph", None)]),
        ],
    )
    fake = FakeTransport(
        completions=[_completion([_boundary(0, 1), _boundary(1, 2)])]
    )
    gateway = ModelGateway(session, fake)

    preview = await answers_ai.preflight_answers_ai(session, gateway, project.id, material.id)
    plan = await answers_ai.run_answers_ai(
        session,
        gateway,
        project.id,
        material.id,
        answers_ai.AnswersAiRunWrite(expected_source_hash=preview.source_hash),
    )

    assert [row.node_id for row in plan.rows] == [nodes[0].id, nodes[1].id]
    assert plan.rows[0].char_count == len(bodies[0])
    assert plan.rows[1].char_count == len(bodies[1])
    assert plan.structural_boundaries == 0
    assert plan.warnings == []

    result = answers_ai.apply_answers_ai(
        session,
        project.id,
        material.id,
        answers_ai.AnswersAiApplyWrite(
            run_id=plan.run_id, expected_source_hash=plan.source_hash, accepted=[0, 1]
        ),
    )
    assert result.created_answers == 2

    first_answer = session.get(ReferenceAnswer, (project.id, nodes[0].id))
    second_answer = session.get(ReferenceAnswer, (project.id, nodes[1].id))
    assert first_answer is not None and first_answer.text == bodies[0]
    assert first_answer.match_method == ReferenceAnswerMatchMethod.AI_SECTION
    assert second_answer is not None and second_answer.text == bodies[1]

    action = session.scalar(
        select(ProjectActionLog)
        .where(ProjectActionLog.project_id == project.id)
        .order_by(ProjectActionLog.sequence.desc())
    )
    assert action is not None and action.action_type == "answers_link"
    action_sequence = action.sequence
    session.commit()

    undo_last_project_action(session, project.id, action_sequence)
    assert session.get(ReferenceAnswer, (project.id, nodes[0].id)) is None
    assert session.get(ReferenceAnswer, (project.id, nodes[1].id)) is None


@pytest.mark.asyncio
async def test_structural_boundary_without_question_stops_the_previous_section(
    session: Session, ai_config: str
) -> None:
    """Раздел без ответов (например, оглавление) обязан оборвать предыдущий раздел,

    а не быть проглоченным вместе с его текстом — та же проблема, что чинит
    `_stop_anchors` в детерминированном пути.
    """
    del ai_config
    project, nodes = _program(session, 2)
    body0 = "Ответ на первый вопрос без общих слов с заголовками совсем."
    body1 = "Ответ на второй вопрос из совершенно другого набора слов."
    material = _answers_material(
        session,
        project,
        [
            (nodes[0].title, [(body0, "paragraph", None)]),
            ("Раздел 2 (без ответов, только оглавление)", []),
            (nodes[1].title, [(body1, "paragraph", None)]),
        ],
    )
    fake = FakeTransport(
        completions=[_completion([_boundary(0, 1), _boundary(1, 0), _boundary(2, 2)])]
    )
    gateway = ModelGateway(session, fake)

    preview = await answers_ai.preflight_answers_ai(session, gateway, project.id, material.id)
    assert preview.candidate_count == 3
    plan = await answers_ai.run_answers_ai(
        session,
        gateway,
        project.id,
        material.id,
        answers_ai.AnswersAiRunWrite(expected_source_hash=preview.source_hash),
    )

    assert plan.structural_boundaries == 1
    assert [row.node_id for row in plan.rows] == [nodes[0].id, nodes[1].id]
    assert plan.rows[0].char_count == len(body0)
    assert plan.rows[1].char_count == len(body1)


@pytest.mark.asyncio
async def test_short_section_is_reported_as_a_warning_not_applied(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project, nodes = _program(session, 1)
    material = _answers_material(session, project, [(nodes[0].title, [("Ок.", "paragraph", None)])])
    fake = FakeTransport(completions=[_completion([_boundary(0, 1)])])
    gateway = ModelGateway(session, fake)

    preview = await answers_ai.preflight_answers_ai(session, gateway, project.id, material.id)
    plan = await answers_ai.run_answers_ai(
        session,
        gateway,
        project.id,
        material.id,
        answers_ai.AnswersAiRunWrite(expected_source_hash=preview.source_hash),
    )

    assert plan.rows == []
    assert any("Заголовок без текста" in warning for warning in plan.warnings)


@pytest.mark.asyncio
async def test_duplicate_candidate_question_pairs_collapse_to_one_boundary(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project, nodes = _program(session, 1)
    body = "Достаточно длинный ответ, чтобы пройти порог минимальной длины эталона."
    material = _answers_material(session, project, [(nodes[0].title, [(body, "paragraph", None)])])
    fake = FakeTransport(
        completions=[_completion([_boundary(0, 1), _boundary(0, 1, confidence="low")])]
    )
    gateway = ModelGateway(session, fake)

    preview = await answers_ai.preflight_answers_ai(session, gateway, project.id, material.id)
    plan = await answers_ai.run_answers_ai(
        session,
        gateway,
        project.id,
        material.id,
        answers_ai.AnswersAiRunWrite(expected_source_hash=preview.source_hash),
    )

    assert len(plan.rows) == 1
    assert plan.rows[0].node_id == nodes[0].id


@pytest.mark.asyncio
async def test_invalid_candidate_index_raises_domain_error(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project, nodes = _program(session, 1)
    material = _answers_material(
        session,
        project,
        [(nodes[0].title, [("Достаточно длинный текст ответа.", "paragraph", None)])],
    )
    fake = FakeTransport(completions=[_completion([_boundary(5, 1)])])
    gateway = ModelGateway(session, fake)

    preview = await answers_ai.preflight_answers_ai(session, gateway, project.id, material.id)
    with pytest.raises(ProjectDomainError) as excinfo:
        await answers_ai.run_answers_ai(
            session,
            gateway,
            project.id,
            material.id,
            answers_ai.AnswersAiRunWrite(expected_source_hash=preview.source_hash),
        )
    assert excinfo.value.code == "answers_ai_invalid_response"


@pytest.mark.asyncio
async def test_apply_with_stale_source_hash_conflicts(session: Session, ai_config: str) -> None:
    del ai_config
    project, nodes = _program(session, 1)
    material = _answers_material(
        session,
        project,
        [(nodes[0].title, [("Достаточно длинный текст ответа.", "paragraph", None)])],
    )
    fake = FakeTransport(completions=[_completion([_boundary(0, 1)])])
    gateway = ModelGateway(session, fake)

    preview = await answers_ai.preflight_answers_ai(session, gateway, project.id, material.id)
    plan = await answers_ai.run_answers_ai(
        session,
        gateway,
        project.id,
        material.id,
        answers_ai.AnswersAiRunWrite(expected_source_hash=preview.source_hash),
    )

    with pytest.raises(ProjectDomainError) as excinfo:
        answers_ai.apply_answers_ai(
            session,
            project.id,
            material.id,
            answers_ai.AnswersAiApplyWrite(
                run_id=plan.run_id, expected_source_hash="0" * 64, accepted=[0]
            ),
        )
    assert excinfo.value.status == 409
    assert excinfo.value.code == "answers_ai_stale_source"
