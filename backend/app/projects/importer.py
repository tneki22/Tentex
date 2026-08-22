import re
from dataclasses import dataclass

from app.models import ExamFormat, ExamKind, NodeType
from app.projects.numbered_series import select_numbered_series

ITEM_RE = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*[.)])\s*|(?:\d+(?:\.\d+)*)\s+|[-—*•]\s+)(.+?)\s*$"
)
# Разметчик PDF иногда сливает несколько нумерованных пунктов в один текстовый
# блок (конец предложения одного пункта и начало следующего попадают в одну
# строку). Режем по границе «конец предложения» + «следующий номер».
# После точки номера пробела может не быть («…значимости. 36.Изложить…»), поэтому
# опираемся не на пробел, а на то, что за «36.» идёт не цифра (иначе «5.2» — не
# номер пункта). Пробел перед номером остаётся обязательным якорем от ложных резов.
INLINE_ITEM_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=\d{1,4}[.)](?!\d))")
TICKET_RE = re.compile(
    r"^\s*Билет\s*(?:№|#)?\s*(\d+)?\s*(?:[.:—-]\s*)?(.*?)\s*$",
    re.IGNORECASE,
)
QUESTION_HEADER_RE = re.compile(r"^\s*Вопросы\s*:??\s*$", re.IGNORECASE)
TASK_HEADER_RE = re.compile(r"^\s*(?:Задачи|Задания)\s*:??\s*$", re.IGNORECASE)
TASK_PREFIX_RE = re.compile(r"^\s*(?:Задача|Задание)\s*:\s*(.+)$", re.IGNORECASE)


class ExamImportError(ValueError):
    pass


@dataclass(slots=True)
class ParsedNode:
    parent_index: int | None
    node_type: NodeType
    exam_kind: ExamKind
    title: str
    position: int


@dataclass(slots=True)
class ParsedExamProgram:
    nodes: list[ParsedNode]
    tickets: int
    questions: int
    tasks: int
    warnings: list[str]


def _lines(raw_text: str) -> list[str]:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def _split_inline_items(lines: list[str]) -> list[str]:
    """Разрезает строки, в которых слиплось несколько нумерованных пунктов."""
    result: list[str] = []
    for line in lines:
        result.extend(part for part in INLINE_ITEM_SPLIT_RE.split(line) if part)
    return result


def _kind_and_title(text: str, default_kind: ExamKind) -> tuple[ExamKind, str]:
    task_match = TASK_PREFIX_RE.match(text)
    if task_match:
        return ExamKind.TASK, task_match.group(1).strip()
    return default_kind, text.strip()


def _duplicate_warnings(nodes: list[ParsedNode]) -> list[str]:
    positions: dict[str, list[int]] = {}
    study_index = 0
    for node in nodes:
        if node.node_type not in {NodeType.TOPIC, NodeType.SUBPOINT}:
            continue
        study_index += 1
        positions.setdefault(node.title.casefold(), []).append(study_index)
    warnings: list[str] = []
    for key, indexes in positions.items():
        if len(indexes) <= 1:
            continue
        title = next(node.title for node in nodes if node.title.casefold() == key)
        number_list = ", ".join(map(str, indexes))
        warnings.append(
            f"Формулировка «{title}» повторяется в пунктах {number_list}"
        )
    return warnings


def _parse_flat(
    lines: list[str], exam_format: ExamFormat, expected_item_count: int | None
) -> tuple[list[ParsedNode], list[str]]:
    lines = _split_inline_items(lines)
    if exam_format == ExamFormat.QUESTIONS:
        selection = select_numbered_series(lines, expected_item_count)
        if selection.ambiguous:
            raise ExamImportError("Не удалось однозначно выбрать основной нумерованный список")
        if selection.items:
            nodes = []
            for item in selection.items:
                kind, title = _kind_and_title(item.text, ExamKind.QUESTION)
                nodes.append(
                    ParsedNode(
                        parent_index=None,
                        node_type=NodeType.TOPIC,
                        exam_kind=kind,
                        title=title,
                        position=len(nodes),
                    )
                )
            return nodes, list(selection.warnings)

    marker_present = any(ITEM_RE.match(line) for line in lines)
    nodes: list[ParsedNode] = []
    current_kind = ExamKind.QUESTION

    for line in lines:
        if QUESTION_HEADER_RE.match(line):
            current_kind = ExamKind.QUESTION
            continue
        if exam_format == ExamFormat.QUESTIONS_TASKS and TASK_HEADER_RE.match(line):
            current_kind = ExamKind.TASK
            continue

        marker = ITEM_RE.match(line)
        if marker:
            text = marker.group(1)
        elif marker_present and nodes:
            nodes[-1].title = f"{nodes[-1].title} {line}".strip()
            continue
        else:
            text = line

        kind, title = _kind_and_title(text, current_kind)
        if title:
            nodes.append(
                ParsedNode(
                    parent_index=None,
                    node_type=NodeType.TOPIC,
                    exam_kind=kind,
                    title=title,
                    position=len(nodes),
                )
            )
    return nodes, []


def _parse_tickets(lines: list[str]) -> list[ParsedNode]:
    nodes: list[ParsedNode] = []
    ticket_index: int | None = None
    ticket_child_count = 0

    for line in lines:
        ticket_match = TICKET_RE.match(line)
        if ticket_match:
            if ticket_index is not None and ticket_child_count == 0:
                raise ExamImportError("В каждом билете должен быть хотя бы один пункт")
            number, suffix = ticket_match.groups()
            title = f"Билет {number}" if number else "Билет"
            if suffix:
                title = f"{title}: {suffix.strip()}"
            root_position = sum(node.parent_index is None for node in nodes)
            nodes.append(
                ParsedNode(
                    parent_index=None,
                    node_type=NodeType.SECTION,
                    exam_kind=ExamKind.TICKET,
                    title=title,
                    position=root_position,
                )
            )
            ticket_index = len(nodes) - 1
            ticket_child_count = 0
            continue

        if ticket_index is None:
            raise ExamImportError("Для формата билетов нужны заголовки «Билет 1», «Билет № 2»")

        marker = ITEM_RE.match(line)
        if marker:
            kind, title = _kind_and_title(marker.group(1), ExamKind.QUESTION)
            if title:
                nodes.append(
                    ParsedNode(
                        parent_index=ticket_index,
                        node_type=NodeType.TOPIC,
                        exam_kind=kind,
                        title=title,
                        position=ticket_child_count,
                    )
                )
                ticket_child_count += 1
        elif ticket_child_count:
            nodes[-1].title = f"{nodes[-1].title} {line}".strip()
        else:
            raise ExamImportError("У билета должен быть нумерованный пункт")

    if ticket_index is None:
        raise ExamImportError("В тексте не найдено ни одного билета")
    if ticket_child_count == 0:
        raise ExamImportError("В каждом билете должен быть хотя бы один пункт")
    return nodes


def parse_exam_program(
    raw_text: str,
    exam_format: ExamFormat,
    *,
    expected_item_count: int | None = None,
) -> ParsedExamProgram:
    if len(raw_text) > 1_000_000:
        raise ExamImportError("Текст списка не может быть длиннее 1 000 000 символов")
    lines = _lines(raw_text)
    if not lines:
        raise ExamImportError("Вставьте хотя бы один вопрос, задачу или билет")
    if exam_format == ExamFormat.TICKETS:
        nodes = _parse_tickets(lines)
        parse_warnings: list[str] = []
    elif exam_format in {ExamFormat.QUESTIONS, ExamFormat.QUESTIONS_TASKS}:
        nodes, parse_warnings = _parse_flat(lines, exam_format, expected_item_count)
    else:
        raise ExamImportError("Этот формат нельзя импортировать без материалов")

    study_nodes = [node for node in nodes if node.node_type != NodeType.SECTION]
    if not study_nodes:
        raise ExamImportError("В списке не найдено ни одного изучаемого пункта")
    return ParsedExamProgram(
        nodes=nodes,
        tickets=sum(node.exam_kind == ExamKind.TICKET for node in nodes),
        questions=sum(node.exam_kind == ExamKind.QUESTION for node in study_nodes),
        tasks=sum(node.exam_kind == ExamKind.TASK for node in study_nodes),
        warnings=[*parse_warnings, *_duplicate_warnings(nodes)],
    )
