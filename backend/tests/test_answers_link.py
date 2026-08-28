from uuid import uuid4

import pytest
from conftest import make_exam_project, make_material
from pydantic import ValidationError
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
from app.projects.answers import put_reference_answer
from app.projects.schemas import ReferenceAnswerWrite


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
    *,
    exam_slot: str | None = None,
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
            exam_slot=exam_slot,
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


def _question_and_task_node(session: Session) -> tuple[object, ProgramNode, ProgramNode]:
    """Вопрос и задача с одинаковой формулировкой — без учёта слота файл ответов

    привязался бы к обоим узлам сразу; со слотом видит только свой вид.
    """
    project = make_exam_project(session)
    question = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.QUESTION,
        sort_order=0,
        title="Общая формулировка 1",
        is_in_current_program=True,
        needs_material=False,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    task = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.TASK,
        sort_order=1,
        title="Общая формулировка 1",
        is_in_current_program=True,
        needs_material=False,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add_all([question, task])
    session.commit()
    return project, question, task


def test_answer_slots_link_only_to_their_own_exam_kind(session: Session) -> None:
    project, question, task = _question_and_task_node(session)
    question_answers = _answers_material(
        session,
        project,
        [("Общая формулировка 1", [("Ответ на вопрос", "paragraph", None)])],
        exam_slot="question_answers",
    )
    task_answers = _answers_material(
        session,
        project,
        [("Общая формулировка 1", [("Решение задачи", "paragraph", None)])],
        exam_slot="task_answers",
    )

    link_answers_material(session, project.id, question_answers.id)
    link_answers_material(session, project.id, task_answers.id)

    question_answer = session.get(ReferenceAnswer, (project.id, question.id))
    task_answer = session.get(ReferenceAnswer, (project.id, task.id))
    assert question_answer is not None and "Ответ на вопрос" in question_answer.text
    assert task_answer is not None and "Решение задачи" in task_answer.text
    assert question_answer.source_material_id == question_answers.id
    assert task_answer.source_material_id == task_answers.id


def test_legacy_unslotted_answers_file_still_sees_the_whole_tree(session: Session) -> None:
    project = make_exam_project(session)
    question = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.QUESTION,
        sort_order=0,
        title="Нормальные формы базы данных",
        is_in_current_program=True,
        needs_material=False,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    task = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.TOPIC,
        exam_kind=ExamKind.TASK,
        sort_order=1,
        title="Построить график функции",
        is_in_current_program=True,
        needs_material=False,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add_all([question, task])
    session.commit()
    # Общий старый файл без слота (`exam_slot=None`) должен связать вопрос и
    # задачу из одного дерева, а не только свой вид, как со слотом.
    material = _answers_material(
        session,
        project,
        [
            (question.title, [("Ответ про нормальные формы", "paragraph", None)]),
            (task.title, [("Решение с графиком", "paragraph", None)]),
        ],
    )

    result = link_answers_material(session, project.id, material.id)

    assert result.expected_questions == 2
    linked_ids = set(result.linked_node_ids)
    assert linked_ids == {question.id, task.id}
    question_answer = session.get(ReferenceAnswer, (project.id, question.id))
    task_answer = session.get(ReferenceAnswer, (project.id, task.id))
    assert question_answer is not None and "нормальные формы" in question_answer.text
    assert task_answer is not None and "графиком" in task_answer.text


def _numbered_sections() -> list[tuple[str, list[tuple[str, str, int | None]]]]:
    return [
        (
            "1. Program question 1",
            [
                ("Answer one", "paragraph", None),
                ("1.1 Nested detail", "heading", 2),
                ("Nested body", "paragraph", None),
            ],
        ),
        ("2. Program question 2", [("Answer two", "paragraph", None)]),
        ("3. Program question 3", [("Answer three", "paragraph", None)]),
        ("4. Surplus answer", [("Outside program", "paragraph", None)]),
    ]


def test_links_numbered_answers_by_current_program_order(session: Session) -> None:
    project, nodes = _program(session, 3)
    material = _answers_material(session, project, _numbered_sections())

    result = link_answers_material(session, project.id, material.id)

    assert result.numbered_sections == 0
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
        answer.match_method == ReferenceAnswerMatchMethod.EXACT_TITLE
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


def test_duplicate_program_titles_receive_the_same_answer(session: Session) -> None:
    """Импорт с сохранением дублей не должен оставлять второй вопрос без эталона."""
    project = make_exam_project(session)
    titles = ["Repeated question", "Other question", "Repeated question"]
    nodes = [
        ProgramNode(
            id=uuid4(),
            project_id=project.id,
            parent_id=None,
            node_type=NodeType.TOPIC,
            exam_kind=ExamKind.QUESTION,
            sort_order=index,
            title=title,
            is_in_current_program=True,
            needs_material=False,
            is_archived=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        for index, title in enumerate(titles)
    ]
    session.add_all(nodes)
    session.commit()
    material = _answers_material(
        session,
        project,
        [
            ("Repeated question", [("Shared answer text", "paragraph", None)]),
            ("Other question", [("Other answer text", "paragraph", None)]),
        ],
    )

    result = link_answers_material(session, project.id, material.id)

    assert set(result.linked_node_ids) == {node.id for node in nodes}
    assert result.missing_node_ids == []
    first_dup, other, second_dup = nodes
    first_answer = session.get(ReferenceAnswer, (project.id, first_dup.id))
    second_answer = session.get(ReferenceAnswer, (project.id, second_dup.id))
    other_answer = session.get(ReferenceAnswer, (project.id, other.id))
    assert first_answer is not None
    assert second_answer is not None
    assert other_answer is not None
    assert first_answer.text == second_answer.text
    assert "Shared answer text" in first_answer.text
    assert other_answer.text != first_answer.text


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
    assert len(result.missing_node_ids) == 2
    assert result.expected_questions == 2
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


def test_image_fragment_uses_its_asset_filename_as_answer_marker(session: Session) -> None:
    project, nodes = _program(session, 1)
    material = _answers_material(
        session,
        project,
        [(nodes[0].title, [("Answer body", "paragraph", None), ("", "paragraph", None)])],
    )
    page = session.scalar(select(MaterialPage).where(MaterialPage.material_id == material.id))
    block = session.scalar(select(MaterialBlock).where(MaterialBlock.material_id == material.id))
    assert page is not None and block is not None
    session.add(
        MaterialFragment(
            id=uuid4(),
            material_id=material.id,
            page_id=page.id,
            block_id=block.id,
            sort_order=3,
            text="[Изображение]",
            bbox=[0, 0.02, 1, 0.03],
            element_kind="image",
            asset_path="assets/source/diagram-1.png",
            structure_level=None,
            degraded_structure=False,
            quality=PageQuality.NATIVE,
        )
    )
    session.commit()

    link_answers_material(session, project.id, material.id)

    answer = session.get(ReferenceAnswer, (project.id, nodes[0].id))
    assert answer is not None
    assert str(material.id) in answer.text
    assert "diagram-1.png" in answer.text


def test_textbook_table_and_formula_survive_answer_linking(session: Session) -> None:
    project, nodes = _program(session, 1)
    material = _answers_material(
        session,
        project,
        [(nodes[0].title, [("Answer body", "paragraph", None)])],
    )
    page = session.scalar(select(MaterialPage).where(MaterialPage.material_id == material.id))
    block = session.scalar(select(MaterialBlock).where(MaterialBlock.material_id == material.id))
    assert page is not None and block is not None
    session.add_all(
        [
            MaterialFragment(
                id=uuid4(),
                material_id=material.id,
                page_id=page.id,
                block_id=block.id,
                sort_order=2,
                text="",
                bbox=[0, 0.02, 1, 0.03],
                element_kind="table",
                asset_path="assets/source/table-1.png",
                structure_level=None,
                degraded_structure=False,
                quality=PageQuality.OCR,
            ),
            MaterialFragment(
                id=uuid4(),
                material_id=material.id,
                page_id=page.id,
                block_id=block.id,
                sort_order=3,
                text=r"\mathbf{P}\{\xi=k\}=p^k",
                bbox=[0, 0.04, 1, 0.05],
                element_kind="formula",
                asset_path="assets/source/formula-1.png",
                structure_level=None,
                degraded_structure=False,
                quality=PageQuality.OCR,
            ),
        ]
    )
    session.commit()

    link_answers_material(session, project.id, material.id)

    answer = session.get(ReferenceAnswer, (project.id, nodes[0].id))
    assert answer is not None
    assert "table-1.png" in answer.text
    assert r"$$\mathbf{P}\{\xi=k\}=p^k$$" in answer.text


def test_linked_answer_preserves_outer_blanks_and_indented_list(session: Session) -> None:
    project, nodes = _program(session, 1)
    material = _answers_material(
        session,
        project,
        [
            (
                nodes[0].title,
                [
                    ("", "paragraph", None),
                    ("  - Первый пункт", "paragraph", None),
                    ("", "paragraph", None),
                ],
            )
        ],
    )

    link_answers_material(session, project.id, material.id)

    answer = session.get(ReferenceAnswer, (project.id, nodes[0].id))
    assert answer is not None
    assert answer.text == "\n  - Первый пункт\n"


def test_manual_answer_validation_preserves_formatting_and_rejects_blank_text(
    session: Session,
) -> None:
    text = "\n  - Первый пункт\n\n"
    command = ReferenceAnswerWrite(text=text)
    assert command.text == text
    with pytest.raises(ValidationError):
        ReferenceAnswerWrite(text=" \n\t ")

    project, nodes = _program(session, 1)
    slot = put_reference_answer(session, project.id, nodes[0].id, command)

    assert slot.answer is not None
    assert slot.answer.text == text


def test_manual_edit_clears_import_provenance_for_legacy_media_fallback(session: Session) -> None:
    project, nodes = _program(session, 1)
    material = make_material(session, "a5")
    session.add(
        ReferenceAnswer(
            project_id=project.id,
            program_node_id=nodes[0].id,
            text="Imported",
            origin_kind=ReferenceAnswerOrigin.IMPORT,
            match_method=ReferenceAnswerMatchMethod.EXACT_TITLE,
            is_confirmed=False,
            is_active=True,
            revision=0,
            source_material_id=material.id,
            source_page_from=1,
            source_page_to=2,
        )
    )
    session.commit()

    slot = put_reference_answer(
        session,
        project.id,
        nodes[0].id,
        ReferenceAnswerWrite(expected_revision=0, text="Manual"),
    )

    assert slot.answer is not None
    assert slot.answer.origin_kind == ReferenceAnswerOrigin.MANUAL
    assert slot.answer.source_material_id is None
    assert slot.answer.source_page_from is None
    assert slot.answer.source_page_to is None
