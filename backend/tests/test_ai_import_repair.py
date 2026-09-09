import json
from decimal import Decimal
from uuid import uuid4

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


def _ticket_with_questions(
    session: Session, project_id, ticket_title: str, question_titles: list[str]
) -> tuple[ProgramNode, list[ProgramNode]]:
    ticket = ProgramNode(
        id=uuid4(),
        project_id=project_id,
        parent_id=None,
        node_type=NodeType.SECTION,
        exam_kind=ExamKind.TICKET,
        sort_order=0,
        title=ticket_title,
        is_in_current_program=True,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(ticket)
    session.flush()
    children = []
    for index, title in enumerate(question_titles):
        node = ProgramNode(
            id=uuid4(),
            project_id=project_id,
            parent_id=ticket.id,
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
        children.append(node)
    session.commit()
    return ticket, children


def _question_payload(
    text: str,
    *,
    source_indices: list[int],
    subpoints: list[str] | None = None,
    kind: str = "question",
    ticket_index: int | None = None,
) -> dict:
    return {
        "kind": kind,
        "title": text,
        "subpoints": subpoints or [],
        "source_indices": source_indices,
        "ticket_index": ticket_index,
    }


def _completion(
    items: list[dict],
    *,
    dropped: list[dict] | None = None,
    changes: list[str] | None = None,
    warnings: list[str] | None = None,
) -> ProviderCompletion:
    payload = {
        "items": items,
        "dropped": dropped or [],
        "changes": (
            changes if changes is not None else ["Расставлены пробелы между слипшимися словами"]
        ),
        "warnings": warnings or [],
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
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    _question_payload(fixed[0], source_indices=[1]),
                    _question_payload(fixed[1], source_indices=[2]),
                ]
            )
        ]
    )
    gateway = ModelGateway(session, fake)

    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    assert preview.has_tickets is False
    run = await import_repair.run_program_repair(
        session,
        gateway,
        project.id,
        import_repair.ProgramRepairRunWrite(
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
        ),
    )
    assert [item.title for item in run.items] == fixed

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
    completion = _completion([_question_payload(fixed[0], source_indices=[1])])
    fake = FakeTransport(completions=[completion])
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
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    _question_payload("Первый.", source_indices=[1]),
                    _question_payload("Второй.", source_indices=[2]),
                    _question_payload("Третий.", source_indices=[3]),
                ]
            )
        ]
    )
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
    assert session.get(ProgramNode, a1.id).parent_id == section_a.id
    assert session.get(ProgramNode, a2.id).parent_id == section_a.id
    assert session.get(ProgramNode, b1.id).parent_id == section_b.id


@pytest.mark.asyncio
async def test_program_repair_rejects_position_missing_from_response(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    _nodes(session, project.id, ["Первый.", "Второй.", "Третий."])
    # Позиция 3 не упомянута ни в items, ни в dropped — модель потеряла пункт молча.
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    _question_payload("Первый.", source_indices=[1]),
                    _question_payload("Второй.", source_indices=[2]),
                ]
            )
        ]
    )
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


@pytest.mark.asyncio
async def test_program_repair_splits_one_position_into_two(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    nodes = _nodes(session, project.id, ["Вопрос один.Вопрос два слипшиеся.", "Отдельный вопрос."])
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    _question_payload("Вопрос один.", source_indices=[1]),
                    _question_payload("Вопрос два слипшиеся.", source_indices=[1]),
                    _question_payload("Отдельный вопрос.", source_indices=[2]),
                ]
            )
        ]
    )
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
    active_titles = {
        node.title
        for node in result.program.nodes
        if node.is_in_current_program and not node.is_archived
    }
    assert active_titles == {"Вопрос один.", "Вопрос два слипшиеся.", "Отдельный вопрос."}
    # Позиция 1 разбита на два новых узла — исходный архивирован, а не удалён.
    split_source = session.get(ProgramNode, nodes[0].id)
    assert split_source is not None and split_source.is_archived is True
    # Позиция 2 переиспользована как есть — тот же узел, привязки не потеряны.
    reused = session.get(ProgramNode, nodes[1].id)
    assert reused is not None and reused.title == "Отдельный вопрос." and not reused.is_archived


@pytest.mark.asyncio
async def test_program_repair_drops_spurious_heading(session: Session, ai_config: str) -> None:
    del ai_config
    project = make_exam_project(session)
    nodes = _nodes(session, project.id, ["Заголовок раздела", "Настоящий вопрос."])
    fake = FakeTransport(
        completions=[
            _completion(
                [_question_payload("Настоящий вопрос.", source_indices=[2])],
                dropped=[{"source_indices": [1], "reason": "Это заголовок раздела, не вопрос"}],
            )
        ]
    )
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
    assert len(run.dropped) == 1
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
    active_titles = {
        node.title
        for node in result.program.nodes
        if node.is_in_current_program and not node.is_archived
    }
    assert active_titles == {"Настоящий вопрос."}
    archived = session.get(ProgramNode, nodes[0].id)
    assert archived is not None and archived.is_archived is True


@pytest.mark.asyncio
async def test_program_repair_adds_subpoints_and_shrinks_them_on_second_run(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    _nodes(session, project.id, ["Платформы МК и IoT STM32 ESP32 сравнение"])
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    _question_payload(
                        "Платформы МК и IoT",
                        subpoints=["STM32: Cortex-M", "ESP32: Wi-Fi/BLE", "Сравнение платформ"],
                        source_indices=[1],
                    )
                ]
            )
        ]
    )
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
    applied = import_repair.apply_program_repair(
        session,
        project.id,
        import_repair.ProgramRepairApplyWrite(
            run_id=run.run_id,
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
            items=run.items,
        ),
    )
    subpoints = [
        node
        for node in applied.program.nodes
        if node.node_type == "subpoint" and node.is_in_current_program and not node.is_archived
    ]
    expected_subpoints = {"STM32: Cortex-M", "ESP32: Wi-Fi/BLE", "Сравнение платформ"}
    assert {node.title for node in subpoints} == expected_subpoints
    kept_subpoint_id = next(node.id for node in subpoints if node.title == "STM32: Cortex-M")

    # Второй запуск: у вопроса остаётся один подпункт — лишние должны уйти в архив,
    # а не потеряться (их можно будет восстановить вручную).
    second = _completion(
        [_question_payload("Платформы МК и IoT", subpoints=["STM32: Cortex-M"], source_indices=[1])]
    )
    fake.completions.append(second)
    preview2 = await import_repair.preflight_program_repair(session, gateway, project.id)
    run2 = await import_repair.run_program_repair(
        session,
        gateway,
        project.id,
        import_repair.ProgramRepairRunWrite(
            expected_program_revision=preview2.program_revision,
            expected_source_hash=preview2.source_hash,
        ),
    )
    applied2 = import_repair.apply_program_repair(
        session,
        project.id,
        import_repair.ProgramRepairApplyWrite(
            run_id=run2.run_id,
            expected_program_revision=preview2.program_revision,
            expected_source_hash=preview2.source_hash,
            items=run2.items,
        ),
    )
    active_subpoints = [
        node
        for node in applied2.program.nodes
        if node.node_type == "subpoint" and node.is_in_current_program and not node.is_archived
    ]
    assert [node.id for node in active_subpoints] == [kept_subpoint_id]


@pytest.mark.asyncio
async def test_program_repair_supports_ticket_format(session: Session, ai_config: str) -> None:
    del ai_config
    project = make_exam_project(session)
    ticket, children = _ticket_with_questions(
        session, project.id, "Билет", ["Вопрос а.", "Вопрос б."]
    )
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    _question_payload("Билет 1", source_indices=[1], kind="ticket"),
                    _question_payload(
                        "Вопрос А (исправлено).",
                        source_indices=[2],
                        ticket_index=1,
                    ),
                    _question_payload(
                        "Вопрос Б (исправлено).",
                        source_indices=[3],
                        ticket_index=1,
                    ),
                ]
            )
        ]
    )
    gateway = ModelGateway(session, fake)

    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    assert preview.has_tickets is True
    assert preview.node_count == 3
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
    assert titles_by_id[ticket.id] == "Билет 1"
    assert titles_by_id[children[0].id] == "Вопрос А (исправлено)."
    assert titles_by_id[children[1].id] == "Вопрос Б (исправлено)."


@pytest.mark.asyncio
async def test_program_repair_rejects_flat_response_when_project_has_tickets(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    _ticket_with_questions(session, project.id, "Билет", ["Вопрос а.", "Вопрос б."])
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    _question_payload("Билет 1", source_indices=[1]),
                    _question_payload("Вопрос а.", source_indices=[2]),
                    _question_payload("Вопрос б.", source_indices=[3]),
                ]
            )
        ]
    )
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


@pytest.mark.asyncio
async def test_mixed_nested_repair_preserves_tree_and_undo(session: Session, ai_config: str):
    del ai_config
    from app.projects.program_context import build_program_context

    project = make_exam_project(session)
    ticket, questions = _ticket_with_questions(session, project.id, "Билет 1", ["Вопрос"])
    standalone = _nodes(session, project.id, ["Задача"])[0]
    section = _nodes(session, project.id, ["Раздел"])[0]
    section.node_type = NodeType.SECTION
    section.exam_kind = None
    subsection = _nodes(session, project.id, ["Подраздел"])[0]
    subsection.node_type = NodeType.SECTION
    subsection.exam_kind = None
    subsection.parent_id = section.id
    ticket.parent_id = subsection.id
    standalone.parent_id = subsection.id
    standalone.sort_order = 1
    session.commit()
    context = build_program_context(session, project.id)
    assert [node["id"] for node in context] == [
        str(node.id) for node in [section, subsection, ticket, questions[0], standalone]
    ]
    assert context[3]["path"] == ["Раздел", "Подраздел", "Билет 1"]
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    {"kind": "ticket", "title": "Билет 1", "source_indices": [1]},
                    _question_payload("Вопрос исправлен", source_indices=[2], ticket_index=1),
                    _question_payload("Задача исправлена", source_indices=[3], kind="task"),
                ]
            )
        ]
    )
    gateway = ModelGateway(session, fake)
    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    assert preview.source_context == context
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
    assert session.get(ProgramNode, standalone.id).parent_id == subsection.id
    assert session.get(ProgramNode, ticket.id).parent_id == subsection.id
    assert session.get(ProgramNode, questions[0].id).parent_id == ticket.id
    action = result.latest_undoable_action
    program.undo_last_project_action(session, project.id, action.sequence)
    assert session.get(ProgramNode, questions[0].id).title == "Вопрос"
    assert session.get(ProgramNode, standalone.id).title == "Задача"


def test_context_hash_detects_parent_changes(session: Session):
    project = make_exam_project(session)
    first, second = _nodes(session, project.id, ["А", "Б"])
    before = import_repair._program_repair_snapshot(session, project.id)
    second.parent_id = first.id
    session.commit()
    after = import_repair._program_repair_snapshot(session, project.id)
    with pytest.raises(ProjectDomainError):
        import_repair._check_program_snapshot(after, project.program_revision, before.source_hash)


def test_context_includes_subpoints_and_only_answer_metrics(session: Session):
    from app.models import ReferenceAnswer, ReferenceAnswerMatchMethod, ReferenceAnswerOrigin
    from app.projects.program_context import build_program_context

    project = make_exam_project(session)
    topic, subpoint = _nodes(session, project.id, ["Вопрос", "Подпункт"])
    subpoint.node_type = NodeType.SUBPOINT
    subpoint.parent_id = topic.id
    session.add(
        ReferenceAnswer(
            project_id=project.id,
            program_node_id=topic.id,
            text="Личный эталон",
            origin_kind=next(iter(ReferenceAnswerOrigin)),
            match_method=next(iter(ReferenceAnswerMatchMethod)),
        )
    )
    session.commit()
    context = build_program_context(session, project.id)
    assert context[0]["has_answer"] is True
    assert context[0]["answer_chars"] == len("Личный эталон")
    assert context[0]["subpoints"] == ["Подпункт"]
    assert context[1]["id"] == str(subpoint.id)
    assert "Личный эталон" not in json.dumps(context, ensure_ascii=False)


def test_repair_rejects_moving_question_out_of_ticket(session: Session):
    project = make_exam_project(session)
    _ticket_with_questions(session, project.id, "Билет", ["Вопрос"])
    snapshot = import_repair._program_repair_snapshot(session, project.id)
    entry = import_repair._FlatNewNode("question", "Вопрос", [], [2], None)
    with pytest.raises(ProjectDomainError, match="внутри своего билета"):
        import_repair._validate_parentage([entry], snapshot.positions)


@pytest.mark.asyncio
async def test_repair_rejects_dropped_child_of_retained_ticket(session: Session, ai_config: str):
    del ai_config
    project = make_exam_project(session)
    _ticket_with_questions(session, project.id, "Билет", ["Первый", "Второй"])
    fake = FakeTransport(
        completions=[
            _completion(
                [
                    {"kind": "ticket", "title": "Билет", "source_indices": [1]},
                    _question_payload("Первый", source_indices=[2], ticket_index=1),
                ],
                dropped=[{"source_indices": [3], "reason": "Лишний"}],
            )
        ]
    )
    gateway = ModelGateway(session, fake)
    preview = await import_repair.preflight_program_repair(session, gateway, project.id)
    assert len(preview.source_context) == 3
    with pytest.raises(ProjectDomainError, match="сохранённого билета"):
        await import_repair.run_program_repair(
            session,
            gateway,
            project.id,
            import_repair.ProgramRepairRunWrite(
                expected_program_revision=preview.program_revision,
                expected_source_hash=preview.source_hash,
            ),
        )


@pytest.mark.asyncio
async def test_apply_rejects_manual_removal_from_retained_ticket(session: Session, ai_config: str):
    del ai_config
    project = make_exam_project(session)
    _ticket_with_questions(session, project.id, "Билет", ["Первый", "Второй"])
    gateway = ModelGateway(
        session,
        FakeTransport(
            completions=[
                _completion(
                    [
                        {"kind": "ticket", "title": "Билет", "source_indices": [1]},
                        _question_payload("Первый", source_indices=[2], ticket_index=1),
                        _question_payload("Второй", source_indices=[3], ticket_index=1),
                    ]
                )
            ]
        ),
    )
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
    run.items[0].items.pop()
    with pytest.raises(ProjectDomainError, match="сохранённого билета"):
        import_repair.apply_program_repair(
            session,
            project.id,
            import_repair.ProgramRepairApplyWrite(
                run_id=run.run_id,
                expected_program_revision=preview.program_revision,
                expected_source_hash=preview.source_hash,
                items=run.items,
            ),
        )


@pytest.mark.asyncio
async def test_repair_rejects_merging_ticket_headers_with_their_questions(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    _ticket_with_questions(session, project.id, "Билет 1", ["Первый вопрос"])
    _ticket_with_questions(session, project.id, "Билет 2", ["Второй вопрос"])
    gateway = ModelGateway(
        session,
        FakeTransport(
            completions=[
                _completion(
                    [
                        {"kind": "ticket", "title": "Общий билет", "source_indices": [1, 3]},
                        _question_payload("Первый вопрос", source_indices=[2], ticket_index=1),
                        _question_payload("Второй вопрос", source_indices=[4], ticket_index=1),
                    ]
                )
            ]
        ),
    )
    preview = await import_repair.preflight_program_repair(session, gateway, project.id)

    with pytest.raises(ProjectDomainError, match="объединять билеты"):
        await import_repair.run_program_repair(
            session,
            gateway,
            project.id,
            import_repair.ProgramRepairRunWrite(
                expected_program_revision=preview.program_revision,
                expected_source_hash=preview.source_hash,
            ),
        )


@pytest.mark.asyncio
async def test_repair_rejects_splitting_ticket_header_with_its_questions(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    _ticket_with_questions(session, project.id, "Билет", ["Первый вопрос", "Второй вопрос"])
    gateway = ModelGateway(
        session,
        FakeTransport(
            completions=[
                _completion(
                    [
                        {"kind": "ticket", "title": "Часть 1", "source_indices": [1]},
                        _question_payload("Первый вопрос", source_indices=[2], ticket_index=1),
                        {"kind": "ticket", "title": "Часть 2", "source_indices": [1]},
                        _question_payload("Второй вопрос", source_indices=[3], ticket_index=2),
                    ]
                )
            ]
        ),
    )
    preview = await import_repair.preflight_program_repair(session, gateway, project.id)

    with pytest.raises(ProjectDomainError, match="разделять билет"):
        await import_repair.run_program_repair(
            session,
            gateway,
            project.id,
            import_repair.ProgramRepairRunWrite(
                expected_program_revision=preview.program_revision,
                expected_source_hash=preview.source_hash,
            ),
        )
