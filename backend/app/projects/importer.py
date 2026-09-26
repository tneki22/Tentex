import re
from collections import defaultdict
from dataclasses import dataclass, replace

from app.models import ExamFormat, ExamKind, NodeType
from app.projects.numbered_series import numbered_item, select_numbered_series

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
    r"^\s*Билет\s*(?:№|#)?\s*(\d+)\s*(?:[.:—-]\s*)?(.*?)\s*$",
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
    has_duplicates: bool = False


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


def _duplicate_positions(nodes: list[ParsedNode]) -> dict[str, list[int]]:
    positions: dict[str, list[int]] = {}
    study_index = 0
    for node in nodes:
        if node.node_type not in {NodeType.TOPIC, NodeType.SUBPOINT}:
            continue
        study_index += 1
        positions.setdefault(node.title.casefold(), []).append(study_index)
    return {key: indexes for key, indexes in positions.items() if len(indexes) > 1}


def _duplicate_warnings(nodes: list[ParsedNode], duplicates: dict[str, list[int]]) -> list[str]:
    warnings: list[str] = []
    for key, indexes in duplicates.items():
        title = next(node.title for node in nodes if node.title.casefold() == key)
        number_list = ", ".join(map(str, indexes))
        warnings.append(
            f"Формулировка «{title}» повторяется в пунктах {number_list}"
        )
    return warnings


def dedupe_first_occurrence(parsed: ParsedExamProgram) -> ParsedExamProgram:
    """Оставляет только первое вхождение повторяющейся формулировки вопроса или подпункта.

    Родителей (билеты, разделы) дубли не задевают — среди изучаемых пунктов
    дубль всегда лист, поэтому удаление не оставляет висячих ссылок `parent_index`.
    """
    seen: set[str] = set()
    old_to_new: dict[int, int] = {}
    kept: list[ParsedNode] = []
    for old_index, node in enumerate(parsed.nodes):
        if node.node_type in {NodeType.TOPIC, NodeType.SUBPOINT}:
            key = node.title.casefold()
            if key in seen:
                continue
            seen.add(key)
        old_to_new[old_index] = len(kept)
        kept.append(node)

    sibling_counts: dict[int | None, int] = defaultdict(int)
    result_nodes: list[ParsedNode] = []
    for node in kept:
        parent_index = old_to_new[node.parent_index] if node.parent_index is not None else None
        position = sibling_counts[parent_index]
        sibling_counts[parent_index] += 1
        result_nodes.append(replace(node, parent_index=parent_index, position=position))

    study_nodes = [node for node in result_nodes if node.node_type != NodeType.SECTION]
    top_level = [node for node in study_nodes if node.node_type == NodeType.TOPIC]
    subpoints = sum(node.node_type == NodeType.SUBPOINT for node in study_nodes)
    return ParsedExamProgram(
        nodes=result_nodes,
        tickets=sum(node.exam_kind == ExamKind.TICKET for node in result_nodes),
        questions=sum(node.exam_kind == ExamKind.QUESTION for node in top_level),
        tasks=sum(node.exam_kind == ExamKind.TASK for node in top_level),
        subpoints=subpoints,
        warnings=[],
        has_duplicates=False,
    )


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

    filtered_lines: list[str] = []
    index_map: list[int] = []
    for original_index, line in enumerate(lines):
        match = SUBPOINT_RE.match(line)
        if match:
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
        duplicates = _duplicate_positions(nodes)
        return ParsedExamProgram(
            nodes=nodes,
            tickets=0,
            questions=questions,
            tasks=tasks,
            subpoints=subpoints,
            warnings=_duplicate_warnings(nodes, duplicates),
            has_duplicates=bool(duplicates),
        )

    # Строим дерево по исходному порядку: перенос строки после «3.1» должен
    # продолжать подпункт, а не соседний основной вопрос.
    nodes: list[ParsedNode] = []
    warnings = list(selection.warnings)
    starts = [index_map[item.source_index] for item in selection.items]
    for position, item in enumerate(selection.items):
        start = starts[position]
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        marker = numbered_item(lines[start], start)
        assert marker is not None
        kind, title = _kind_and_title(marker.text, default_kind)
        parent_index = len(nodes)
        nodes.append(ParsedNode(None, NodeType.TOPIC, kind, title, position))
        last_index = parent_index
        last_child_number = 0
        for line in lines[start + 1 : end]:
            if re.fullmatch(r"\d{1,4}", line):
                continue  # печатный номер страницы PDF
            subpoint = SUBPOINT_RE.match(line)
            if subpoint:
                child = int(subpoint.group("child"))
                parent = int(subpoint.group("parent"))
                text = subpoint.group("text").strip()
                if parent == item.number and child > last_child_number:
                    nodes.append(ParsedNode(parent_index, NodeType.SUBPOINT, kind, text, child - 1))
                    last_index = len(nodes) - 1
                    last_child_number = child
                else:
                    nodes[last_index].title = f"{nodes[last_index].title} {text}".strip()
                    warnings.append(
                        f"Подпункт «{parent}.{child}» не продолжает пункт {item.number} "
                        "и сохранён как часть текста"
                    )
            elif numbered_item(line, 0) is None:
                nodes[last_index].title = f"{nodes[last_index].title} {line}".strip()

    questions, tasks, subpoints = count_exam_nodes(nodes)
    duplicates = _duplicate_positions(nodes)
    return ParsedExamProgram(
        nodes=nodes,
        tickets=0,
        questions=questions,
        tasks=tasks,
        subpoints=subpoints,
        warnings=[*warnings, *_duplicate_warnings(nodes, duplicates)],
        has_duplicates=bool(duplicates),
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
            continue  # титульный лист и вводный текст перед первым билетом
        if re.fullmatch(r"\d{1,4}", line):
            continue

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
    duplicates = _duplicate_positions(nodes)
    return ParsedExamProgram(
        nodes=nodes,
        tickets=sum(node.exam_kind == ExamKind.TICKET for node in nodes),
        questions=sum(node.exam_kind == ExamKind.QUESTION for node in study_nodes),
        tasks=sum(node.exam_kind == ExamKind.TASK for node in study_nodes),
        subpoints=0,
        warnings=_duplicate_warnings(nodes, duplicates),
        has_duplicates=bool(duplicates),
    )
