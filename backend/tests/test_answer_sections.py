from uuid import uuid4

from app.bindings.answer_sections import detect_sections
from app.models import (
    MaterialFragment,
    NodeType,
    PageQuality,
    ProgramNode,
    RecognitionSource,
)


def _nodes(count: int) -> list[ProgramNode]:
    titles = [f"Вопрос программы {number}" for number in range(1, count + 1)]
    titles[9] = (
        "Дать определение плотности распределения вероятности случайной величины. "
        "Сформулировать и доказать её свойства."
    )
    titles[10] = "Функция распределения случайной величины и её свойства"
    return [
        ProgramNode(
            id=uuid4(),
            project_id=uuid4(),
            parent_id=None,
            node_type=NodeType.TOPIC,
            sort_order=index,
            title=title,
            is_in_current_program=True,
            needs_material=False,
            is_archived=False,
        )
        for index, title in enumerate(titles)
    ]


def _fragment(text: str, order: int, kind: str = "paragraph") -> MaterialFragment:
    return MaterialFragment(
        id=uuid4(),
        material_id=uuid4(),
        page_id=uuid4(),
        block_id=uuid4(),
        sort_order=order,
        text=text,
        bbox=[0, order / 100, 1, (order + 1) / 100],
        element_kind=kind,
        structure_level=None,
        degraded_structure=True,
        quality=PageQuality.OCR,
        recognition_source=RecognitionSource.OCR,
    )


def test_question_header_joins_across_pages_and_ignores_element_kind() -> None:
    nodes = _nodes(11)
    first = _fragment("10. Дать определение плотности распределения вероятности случайной", 0)
    continuation = _fragment(
        "величины. Сформулировать и доказать её свойства.", 1, "paragraph"
    )
    answer = _fragment("Плотностью называется производная функции распределения.", 2)
    next_header = _fragment(
        "11. Функция распределения случайной величины и её свойства", 3, "paragraph"
    )
    rows = [(first, 13), (continuation, 14), (answer, 14), (next_header, 15)]

    result = detect_sections(nodes, rows)

    tenth = next(section for section in result.sections if nodes[9].id in section.node_ids)
    assert tenth.header_fragment_ids == frozenset({first.id, continuation.id})
    body_ids = [
        fragment.id
        for fragment in tenth.fragments
        if fragment.id not in tenth.header_fragment_ids
    ]
    assert body_ids == [answer.id]
    assert nodes[10].id in result.linked_node_ids


def test_internal_numbered_list_cannot_move_alignment_backwards() -> None:
    nodes = _nodes(11)
    header = _fragment(
        "10. Дать определение плотности распределения вероятности случайной "
        "величины. Сформулировать и доказать её свойства.",
        0,
    )
    internal = _fragment("1. Вспомогательная аксиома в доказательстве", 1, "list")
    body = _fragment("Она используется только внутри ответа.", 2)
    next_header = _fragment(
        "11. Функция распределения случайной величины и её свойства", 3
    )

    result = detect_sections(nodes, [(header, 1), (internal, 1), (body, 1), (next_header, 2)])

    assert nodes[0].id not in result.linked_node_ids
    tenth = next(section for section in result.sections if nodes[9].id in section.node_ids)
    assert internal.id in {fragment.id for fragment in tenth.fragments}


def test_image_only_answer_creates_empty_text_reference(session) -> None:
    from sqlalchemy import func, select
    from test_answers_link import _answers_material, _program

    from app.bindings.answers_link import link_answers_material
    from app.models import Binding, ReferenceAnswer
    from app.projects.answers import get_reference_answer

    project, nodes = _program(session, 1)
    material = _answers_material(
        session,
        project,
        [("1. Program question 1", [("[Изображение]", "image", None)])],
    )
    image = session.scalar(
        select(MaterialFragment).where(MaterialFragment.element_kind == "image")
    )
    assert image is not None
    image.asset_path = "materials/source-only.png"
    session.commit()

    result = link_answers_material(session, project.id, material.id)
    answer = session.get(ReferenceAnswer, (project.id, nodes[0].id))

    assert result.created_answers == 1
    assert result.available_node_ids == [nodes[0].id]
    assert result.unavailable_node_ids == []
    assert result.complete is True
    assert answer is not None and answer.text == ""
    assert session.scalar(select(func.count(Binding.id))) == 1
    slot = get_reference_answer(session, project.id, nodes[0].id)
    assert slot.answer is not None and slot.answer.source_only is True
