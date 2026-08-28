import pytest

from app.models import ExamKind, NodeType
from app.projects.importer import ExamImportError, parse_exam_list


def _titles_by_type(parsed, node_type: NodeType) -> list[str]:
    return [node.title for node in parsed.nodes if node.node_type == node_type]


def test_parses_dotted_and_bracketed_subpoints_under_matching_parent() -> None:
    parsed = parse_exam_list(
        "1. Нормальные формы\n"
        "1.1. Первая нормальная форма\n"
        "1.2) Вторая нормальная форма\n"
        "2. Транзакции",
        ExamKind.QUESTION,
    )

    assert _titles_by_type(parsed, NodeType.TOPIC) == ["Нормальные формы", "Транзакции"]
    assert _titles_by_type(parsed, NodeType.SUBPOINT) == [
        "Первая нормальная форма",
        "Вторая нормальная форма",
    ]
    subpoints = [node for node in parsed.nodes if node.node_type == NodeType.SUBPOINT]
    parent = parsed.nodes[0]
    assert all(node.parent_index == parsed.nodes.index(parent) for node in subpoints)
    assert [node.position for node in subpoints] == [0, 1]
    assert parsed.questions == 2
    assert parsed.subpoints == 2


def test_subpoint_kind_matches_parent_kind() -> None:
    parsed = parse_exam_list(
        "1. Найти производную\n1.1. Частный случай",
        ExamKind.TASK,
    )

    subpoint = next(node for node in parsed.nodes if node.node_type == NodeType.SUBPOINT)
    assert subpoint.exam_kind == ExamKind.TASK


def test_subpoint_with_mismatched_parent_number_becomes_continuation_text() -> None:
    parsed = parse_exam_list(
        "1. Первый вопрос\n2.1 Похоже на подпункт другого пункта\n2. Второй вопрос",
        ExamKind.QUESTION,
    )

    assert _titles_by_type(parsed, NodeType.SUBPOINT) == []
    assert _titles_by_type(parsed, NodeType.TOPIC) == [
        "Первый вопрос Похоже на подпункт другого пункта",
        "Второй вопрос",
    ]
    assert parsed.subpoints == 0
    assert any("не продолжает пункт" in warning for warning in parsed.warnings)


def test_only_one_level_of_subpoints_is_recognized() -> None:
    parsed = parse_exam_list(
        "1. Вопрос\n1.1. Подпункт\n1.1.1 Второй уровень не поддерживается",
        ExamKind.QUESTION,
    )

    # Строка «1.1.1 …» не совпадает со строгим маркером «N.M» (два числа,
    # разделённых одной точкой) — второй уровень не выделяется отдельным узлом.
    assert parsed.subpoints == 1
    assert _titles_by_type(parsed, NodeType.SUBPOINT) == ["Подпункт"]
    combined_text = " ".join(node.title for node in parsed.nodes)
    assert "Второй уровень не поддерживается" in combined_text


def test_top_level_counts_exclude_subpoints() -> None:
    parsed = parse_exam_list(
        "1. Первый\n1.1 Деталь\n1.2 Другая деталь\n2. Второй\n3. Третий",
        ExamKind.QUESTION,
        expected_item_count=3,
    )

    assert (parsed.questions, parsed.tasks, parsed.subpoints) == (3, 0, 2)


def test_task_kind_list_is_independent_of_question_numbering() -> None:
    parsed = parse_exam_list("1. Решить уравнение\n2. Построить график", ExamKind.TASK)

    assert parsed.tasks == 2
    assert parsed.questions == 0
    assert all(node.exam_kind == ExamKind.TASK for node in parsed.nodes)


def test_empty_list_raises() -> None:
    with pytest.raises(ExamImportError):
        parse_exam_list("   \n  ", ExamKind.QUESTION)
