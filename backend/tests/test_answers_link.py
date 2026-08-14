from uuid import uuid4

from conftest import make_exam_project, make_material
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bindings.answers_link import link_answers_material
from app.models import (
    Binding,
    BlockClass,
    ExamKind,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    NodeType,
    PageQuality,
    ProgramNode,
    ProjectMaterial,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    SourceRole,
    utc_now,
)


def _program(session: Session, count: int) -> tuple[object, list[ProgramNode]]:
    project = make_exam_project(session)
    nodes = [
        ProgramNode(
            id=uuid4(),
            project_id=project.id,
            parent_id=None,
            node_type=NodeType.TOPIC,
            exam_kind=ExamKind.QUESTION,
            sort_order=index,
            title=f"Program question {index + 1}",
            is_in_current_program=True,
            needs_material=False,
            is_archived=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        for index in range(count)
    ]
    session.add_all(nodes)
    session.commit()
    return project, nodes


def _answers_material(
    session: Session,
    project,
    sections: list[tuple[str, list[tuple[str, str, int | None]]]],
):
    material = make_material(session, uuid4().hex)
    session.add(
        ProjectMaterial(
            project_id=project.id,
            material_id=material.id,
            source_role=SourceRole.REFERENCE,
            priority=0,
            affects_program=False,
            purposes=["reference_answers"],
            created_at=utc_now(),
        )
    )
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=1,
        page_number=1,
        width=595,
        height=842,
        text="",
        markdown="",
        quality=PageQuality.NATIVE,
        elements=[],
        diagnostics=[],
        created_at=utc_now(),
    )
    session.add(page)
    session.flush()
    fragment_order = 0
    for block_order, (title, body) in enumerate(sections):
        block = MaterialBlock(
            id=uuid4(),
            material_id=material.id,
            revision=1,
            sort_order=block_order,
            title=title,
            block_class=BlockClass.CONTENT,
            page_from=1,
            page_to=1,
        )
        session.add(block)
        session.flush()
        rows = [(title, "heading", 1), *body]
        for text, kind, level in rows:
            session.add(
                MaterialFragment(
                    id=uuid4(),
                    material_id=material.id,
                    page_id=page.id,
                    block_id=block.id,
                    sort_order=fragment_order,
                    text=text,
                    bbox=[0, fragment_order / 100, 1, (fragment_order + 1) / 100],
                    element_kind=kind,
                    structure_level=level,
                    degraded_structure=False,
                    quality=PageQuality.NATIVE,
                )
            )
            fragment_order += 1
    session.commit()
    return material


def _numbered_sections() -> list[tuple[str, list[tuple[str, str, int | None]]]]:
    return [
        (
            "1. Completely unrelated alpha",
            [
                ("Answer one", "paragraph", None),
                ("1.1 Nested detail", "heading", 2),
                ("Nested body", "paragraph", None),
            ],
        ),
        ("2. Completely unrelated beta", [("Answer two", "paragraph", None)]),
        ("3. Completely unrelated gamma", [("Answer three", "paragraph", None)]),
        ("4. Surplus answer", [("Outside program", "paragraph", None)]),
    ]


def test_links_numbered_answers_by_current_program_order(session: Session) -> None:
    project, nodes = _program(session, 3)
    material = _answers_material(session, project, _numbered_sections())

    result = link_answers_material(session, project.id, material.id)

    assert result.numbered_sections == 3
    assert result.extra_sections == 1
    assert result.ordinal_rejected_reason is None
    assert result.unmatched_headings == []
    answers = list(
        session.scalars(
            select(ReferenceAnswer)
            .where(ReferenceAnswer.project_id == project.id)
            .order_by(ReferenceAnswer.program_node_id)
        )
    )
    assert {answer.program_node_id for answer in answers} == {node.id for node in nodes}
    assert all(
        answer.match_method == ReferenceAnswerMatchMethod.NUMBERED_ORDER
        and answer.is_confirmed is False
        for answer in answers
    )
    first = session.get(ReferenceAnswer, (project.id, nodes[0].id))
    assert first is not None
    assert "Nested detail" in first.text
    assert "Answer two" not in first.text


def test_numbered_relink_is_idempotent_and_preserves_manual_answer(session: Session) -> None:
    project, nodes = _program(session, 3)
    material = _answers_material(session, project, _numbered_sections())
    session.add(
        ReferenceAnswer(
            project_id=project.id,
            program_node_id=nodes[1].id,
            text="Manual verified text",
            origin_kind=ReferenceAnswerOrigin.MANUAL,
            match_method=ReferenceAnswerMatchMethod.MANUAL,
            is_confirmed=True,
            is_active=True,
            revision=4,
        )
    )
    session.commit()

    link_answers_material(session, project.id, material.id)
    binding_count = session.scalar(select(func.count(Binding.id)))
    repeated = link_answers_material(session, project.id, material.id)

    assert session.scalar(select(func.count(Binding.id))) == binding_count
    manual = session.get(ReferenceAnswer, (project.id, nodes[1].id))
    assert manual is not None
    assert manual.text == "Manual verified text"
    assert manual.match_method == ReferenceAnswerMatchMethod.MANUAL
    assert repeated.created_answers == 0


def test_ordinal_linking_fails_closed_on_gap(session: Session) -> None:
    project, _nodes = _program(session, 2)
    material = _answers_material(
        session,
        project,
        [
            ("1. Unrelated first", [("Body", "paragraph", None)]),
            ("3. Unrelated third", [("Body", "paragraph", None)]),
            ("4. Unrelated fourth", [("Body", "paragraph", None)]),
        ],
    )

    result = link_answers_material(session, project.id, material.id)

    assert result.numbered_sections == 0
    assert result.ordinal_rejected_reason == "Основная нумерация ответов начинается не с 1"
    assert session.scalar(select(func.count(ReferenceAnswer.program_node_id))) == 0


def test_exact_title_match_keeps_priority_over_number(session: Session) -> None:
    project, nodes = _program(session, 1)
    nodes[0].title = "Exact title"
    session.commit()
    material = _answers_material(
        session,
        project,
        [("1. Exact title", [("Exact body", "paragraph", None)])],
    )

    result = link_answers_material(session, project.id, material.id)

    answer = session.get(ReferenceAnswer, (project.id, nodes[0].id))
    assert answer is not None
    assert answer.match_method == ReferenceAnswerMatchMethod.EXACT_TITLE
    assert result.numbered_sections == 0
