import re
from dataclasses import dataclass

from app.models import ExamFormat, ExamKind, NodeType
from app.projects.numbered_series import select_numbered_series

ITEM_RE = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*[.)])\s*|(?:\d+(?:\.\d+)*)\s+|[-—*•]\s+)(.+?)\s*$"
)
# Один уровень подпунктов: «N.M», «N.M.» или «N.M)» отдельной строкой. N должен
# совпадать с номером последнего родительского пункта — проверяется на месте
# использования, не в самом регулярном выражении.
SUBPOINT_RE = re.compile(
    r"^\s*(?P<parent>\d{1,4})\.(?P<child>\d{1,3})(?:[.)])?\s+(?P<text>\S.*?)\s*$"
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
    subpoints: int
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


def _parse_marker_list(
    lines: list[str], default_kind: ExamKind, *, honor_headers: bool
) -> list[ParsedNode]:
    """Построчный разбор без опоры на сквозную нумерацию: маркер `N.`, `N)`, тире

    или голая строка — каждый непустой пункт становится темой. Используется как
    запасной вариант, когда сквозного номерного списка нет, и как единственный
    путь для устаревшего формата «Вопросы и задачи» с заголовками разделов.
    """
    marker_present = any(ITEM_RE.match(line) for line in lines)
    nodes: list[ParsedNode] = []
    current_kind = default_kind

    for line in lines:
        if QUESTION_HEADER_RE.match(line):
            current_kind = ExamKind.QUESTION
            continue
        if honor_headers and TASK_HEADER_RE.match(line):
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
    return nodes


def count_exam_nodes(nodes: list[ParsedNode]) -> tuple[int, int, int]:
    study_nodes = [node for node in nodes if node.node_type != NodeType.SECTION]
    top_level = [node for node in study_nodes if node.node_type == NodeType.TOPIC]
    questions = sum(node.exam_kind == ExamKind.QUESTION for node in top_level)
    tasks = sum(node.exam_kind == ExamKind.TASK for node in top_level)
    subpoints = sum(node.node_type == NodeType.SUBPOINT for node in study_nodes)
    return questions, tasks, subpoints


def parse_exam_list(
    raw_text: str,
    default_kind: ExamKind,
    *,
    expected_item_count: int | None = None,
) -> ParsedExamProgram:
    """Разбирает один список вопросов или задач с поддержкой подпунктов `N.M`.

    Строки-подпункты снимаются с общего потока до поиска основной нумерованной
    серии — иначе `select_numbered_series` принял бы их текст за продолжение
    родительского пункта. После выбора серии подпункты вставляются обратно по
    позиции в исходном тексте и проверяются на совпадение родительского номера.
    """
    if len(raw_text) > 1_000_000:
        raise ExamImportError("Текст списка не может быть длиннее 1 000 000 символов")
    lines = _lines(raw_text)
    if not lines:
        raise ExamImportError("Вставьте хотя бы один вопрос или задачу")
    lines = _split_inline_items(lines)

    subpoint_lines: list[tuple[int, int, int, str]] = []
    filtered_lines: list[str] = []
    index_map: list[int] = []
    for original_index, line in enumerate(lines):
        match = SUBPOINT_RE.match(line)
        if match:
            subpoint_lines.append(
                (
                    original_index,
                    int(match.group("parent")),
                    int(match.group("child")),
                    match.group("text").strip(),
                )
            )
            continue
        filtered_lines.append(line)
        index_map.append(original_index)

    selection = select_numbered_series(filtered_lines, expected_item_count)
    if selection.ambiguous:
        raise ExamImportError("Не удалось однозначно выбрать основной нумерованный список")

    if not selection.items:
        nodes = _parse_marker_list(lines, default_kind, honor_headers=False)
        if not nodes:
            raise ExamImportError("В списке не найдено ни одного изучаемого пункта")
        questions, tasks, subpoints = count_exam_nodes(nodes)
        return ParsedExamProgram(
            nodes=nodes,
            tickets=0,
            questions=questions,
            tasks=tasks,
            subpoints=subpoints,
            warnings=_duplicate_warnings(nodes),
        )

    nodes: list[ParsedNode] = []
    top_positions: list[tuple[int, int, int]] = []  # (исходная строка, индекс узла, номер)
    for item in selection.items:
        original_index = index_map[item.source_index]
        kind, title = _kind_and_title(item.text, default_kind)
        nodes.append(
            ParsedNode(
                parent_index=None,
                node_type=NodeType.TOPIC,
                exam_kind=kind,
                title=title,
                position=len(nodes),
            )
        )
        top_positions.append((original_index, len(nodes) - 1, item.number))

    warnings = list(selection.warnings)
    top_ptr = 0
    parent_node_index: int | None = None
    parent_number: int | None = None
    last_node_index: int | None = None
    sibling_count = 0
    last_child_number = 0

    for original_index, parent, child, text in subpoint_lines:
        while top_ptr < len(top_positions) and top_positions[top_ptr][0] < original_index:
            _, parent_node_index, parent_number = top_positions[top_ptr]
            last_node_index = parent_node_index
            sibling_count = 0
            last_child_number = 0
            top_ptr += 1

        if parent_node_index is not None and parent == parent_number and child > last_child_number:
            nodes.append(
                ParsedNode(
                    parent_index=parent_node_index,
                    node_type=NodeType.SUBPOINT,
                    exam_kind=nodes[parent_node_index].exam_kind,
                    title=text,
                    position=sibling_count,
                )
            )
            sibling_count += 1
            last_child_number = child
            last_node_index = len(nodes) - 1
        elif last_node_index is not None:
            nodes[last_node_index].title = f"{nodes[last_node_index].title} {text}".strip()
            shown_parent = parent_number if parent_number is not None else "—"
            warnings.append(
                f"Подпункт «{parent}.{child}» не продолжает пункт {shown_parent} "
                "и сохранён как часть текста"
            )
        else:
            warnings.append(f"Подпункт «{parent}.{child}» встретился до первого пункта и пропущен")

    questions, tasks, subpoints = count_exam_nodes(nodes)
    return ParsedExamProgram(
        nodes=nodes,
        tickets=0,
        questions=questions,
        tasks=tasks,
        subpoints=subpoints,
        warnings=[*warnings, *_duplicate_warnings(nodes)],
    )


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
    if exam_format == ExamFormat.QUESTIONS:
        return parse_exam_list(
            raw_text, ExamKind.QUESTION, expected_item_count=expected_item_count
        )

    if len(raw_text) > 1_000_000:
        raise ExamImportError("Текст списка не может быть длиннее 1 000 000 символов")
    lines = _lines(raw_text)
    if not lines:
        raise ExamImportError("Вставьте хотя бы один вопрос, задачу или билет")
    if exam_format == ExamFormat.TICKETS:
        nodes = _parse_tickets(lines)
    elif exam_format == ExamFormat.QUESTIONS_TASKS:
        # Устаревший объединённый формат: заголовки «Вопросы»/«Задачи» переключают
        # вид пункта, сквозная нумерация не проверяется, подпункты не выделяются —
        # новый составной импорт (`parse_exam_list`) заменяет этот путь для новых
        # черновиков, а этот остаётся только ради старых.
        nodes = _parse_marker_list(
            _split_inline_items(lines), ExamKind.QUESTION, honor_headers=True
        )
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
        subpoints=0,
        warnings=_duplicate_warnings(nodes),
    )
