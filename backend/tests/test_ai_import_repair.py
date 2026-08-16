import json
from decimal import Decimal

import pytest
from conftest import make_exam_project
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.models import ExamKind, NodeType, ProgramNode, ProjectStatus, WizardDraft, utc_now
from app.projects import import_repair, program
from app.projects.errors import ProjectDomainError


def _nodes(session: Session, project_id, titles: list[str]) -> list[ProgramNode]:
    nodes = []
    for index, title in enumerate(titles):
        node = ProgramNode(
            project_id=project_id,
            parent_id=None,
            node_type=NodeType.TOPIC,
            exam_kind=ExamKind.QUESTION,
            sort_order=index,
            title=title,
            is_in_current_program=True,
            is_archived=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(node)
        nodes.append(node)
    session.commit()
    return nodes


def _completion(items: list[str]) -> ProviderCompletion:
    payload = {
        "items": [{"text": text} for text in items],
        "changes": ["Расставлены пробелы между слипшимися словами"],
        "warnings": [],
    }
    return ProviderCompletion(
        content=json.dumps(payload),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=100, output_tokens=50, cost_usd=Decimal("0.003")),
    )


@pytest.mark.asyncio
async def test_program_repair_run_apply_and_undo(session: Session, ai_config: str) -> None:
    del ai_config
    project = make_exam_project(session)
    mangled = ["Датьопределениенезависимости.", "Второйвопрос."]
    fixed = ["Дать определение независимости.", "Второй вопрос."]
    nodes = _nodes(session, project.id, mangled)
    fake = FakeTransport(completions=[_completion(fixed)])
    gateway = ModelGateway(session, fake)

    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    run = await import_repair.run_program_repair(
        session,
        gateway,
        project.id,
        import_repair.ProgramRepairRunWrite(
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
        ),
    )
    assert run.items == fixed

    result = import_repair.apply_program_repair(
        session,
        project.id,
        import_repair.ProgramRepairApplyWrite(
            run_id=run.run_id,
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
            items=run.items,
        ),
    )
    titles_by_id = {node.id: node.title for node in result.program.nodes}
    assert titles_by_id[nodes[0].id] == fixed[0]
    assert titles_by_id[nodes[1].id] == fixed[1]

    action = result.latest_undoable_action
    assert action is not None and action.action_type == "ai_import_repair"
    undone = program.undo_last_project_action(session, project.id, action.sequence)
    undone_titles = {node.id: node.title for node in undone.program.nodes}
    assert undone_titles[nodes[0].id] == mangled[0]
    assert undone_titles[nodes[1].id] == mangled[1]


@pytest.mark.asyncio
async def test_program_repair_works_on_draft_project_during_wizard_review(
    session: Session, ai_config: str
) -> None:
    # Шаг 5 мастера уже создал реальные ProgramNode на черновом проекте —
    # переименование должно работать до активации, не только после.
    del ai_config
    project = make_exam_project(session, status=ProjectStatus.DRAFT)
    session.add(WizardDraft(project_id=project.id, revision=1, state={}))
    session.commit()
    mangled = ["Датьопределение."]
    fixed = ["Дать определение."]
    nodes = _nodes(session, project.id, mangled)
    fake = FakeTransport(completions=[_completion(fixed)])
    gateway = ModelGateway(session, fake)

    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    run = await import_repair.run_program_repair(
        session,
        gateway,
        project.id,
        import_repair.ProgramRepairRunWrite(
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
        ),
    )
    result = import_repair.apply_program_repair(
        session,
        project.id,
        import_repair.ProgramRepairApplyWrite(
            run_id=run.run_id,
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
            items=run.items,
        ),
    )
    titles_by_id = {node.id: node.title for node in result.program.nodes}
    assert titles_by_id[nodes[0].id] == "Дать определение."


@pytest.mark.asyncio
async def test_program_repair_apply_rejects_item_count_mismatch(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    nodes = _nodes(session, project.id, ["Первый.", "Второй."])
    fake = FakeTransport(completions=[_completion(["Первый.", "Второй."])])
    gateway = ModelGateway(session, fake)

    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    run = await import_repair.run_program_repair(
        session,
        gateway,
        project.id,
        import_repair.ProgramRepairRunWrite(
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
        ),
    )

    with pytest.raises(ProjectDomainError):
        import_repair.apply_program_repair(
            session,
            project.id,
            import_repair.ProgramRepairApplyWrite(
                run_id=run.run_id,
                expected_program_revision=preview.program_revision,
                expected_source_hash=preview.source_hash,
                items=["Только один пункт вместо двух"],
            ),
        )
    assert nodes[0].title == "Первый."


@pytest.mark.asyncio
async def test_program_repair_orders_nodes_by_tree_not_flat_sort_order(
    session: Session, ai_config: str
) -> None:
    # После «Разложить по разделам» sort_order уникален только внутри своего
    # раздела — секция Б с локальным sort_order=0 не должна обогнать вопрос
    # из секции А с локальным sort_order=1.
    del ai_config
    project = make_exam_project(session)
    section_a = ProgramNode(
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.SECTION,
        exam_kind=None,
        sort_order=0,
        title="Раздел А",
        is_in_current_program=True,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    section_b = ProgramNode(
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.SECTION,
        exam_kind=None,
        sort_order=1,
        title="Раздел Б",
        is_in_current_program=True,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add_all([section_a, section_b])
    session.flush()
    a1 = ProgramNode(
        project_id=project.id,
        parent_id=section_a.id,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.QUESTION,
        sort_order=0,
        title="Вопрос А1",
        is_in_current_program=True,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    a2 = ProgramNode(
        project_id=project.id,
        parent_id=section_a.id,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.QUESTION,
        sort_order=1,
        title="Вопрос А2",
        is_in_current_program=True,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    b1 = ProgramNode(
        project_id=project.id,
        parent_id=section_b.id,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.QUESTION,
        sort_order=0,
        title="Вопрос Б1",
        is_in_current_program=True,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add_all([a1, a2, b1])
    session.commit()
    # Фейковая модель просто возвращает три позиционные метки — реальная
    # проверка тут в том, какому узлу какая позиция достанется при apply.
    fake = FakeTransport(completions=[_completion(["Первый.", "Второй.", "Третий."])])
    gateway = ModelGateway(session, fake)

    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    run = await import_repair.run_program_repair(
        session,
        gateway,
        project.id,
        import_repair.ProgramRepairRunWrite(
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
        ),
    )

    result = import_repair.apply_program_repair(
        session,
        project.id,
        import_repair.ProgramRepairApplyWrite(
            run_id=run.run_id,
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
            items=run.items,
        ),
    )
    titles_by_id = {node.id: node.title for node in result.program.nodes}
    assert titles_by_id[a1.id] == "Первый."
    assert titles_by_id[a2.id] == "Второй."
    assert titles_by_id[b1.id] == "Третий."


@pytest.mark.asyncio
async def test_program_repair_model_reply_with_wrong_count_is_rejected(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    _nodes(session, project.id, ["Первый.", "Второй.", "Третий."])
    fake = FakeTransport(completions=[_completion(["Только один"])])
    gateway = ModelGateway(session, fake)

    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    with pytest.raises(ProjectDomainError):
        await import_repair.run_program_repair(
            session,
            gateway,
            project.id,
            import_repair.ProgramRepairRunWrite(
                expected_program_revision=preview.program_revision,
                expected_source_hash=preview.source_hash,
            ),
        )
