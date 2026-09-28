"""Паспорт урока (`brief`): всё, что проект знает о теме и читателе, для модели.

Правило: заполненное поле попадает в промпт явно, пустое — называется пустым
(«цель не указана»), а не выдумывается. Паспорт собирается один раз на запуск и
замораживается в `checkpoint` задачи, поэтому все вызовы одной сборки видят одно и
то же, даже если программа или материалы менялись во время сборки. Тот же текст
показывает диалог запуска в свёрнутом блоке «Что увидит модель».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lessons.schemas import LessonTemplate
from app.lessons.service import STUDY_NODE_TYPES, _load_program, _Program
from app.models import (
    Conspect,
    GoalPassport,
    Lesson,
    LessonTopic,
    Material,
    MaterialSourceKind,
    NodeType,
    ProgramNode,
    Project,
    ProjectMaterial,
    SourceRole,
    TemplateKey,
)
from app.retrieval.chunking import count_tokens

#: Больше понятий «уже известно» модель не удержит полезно; ближние темы идут первыми.
KNOWN_CONCEPTS_LIMIT = 40
#: Конспект — то, что пользователь уже записал; длиннее он вытеснял бы материал.
CONSPECT_TOKENS = 800
PLACE_WINDOW = 3

PROJECT_KIND = {
    TemplateKey.TEXTBOOK: "изучение по учебнику",
    TemplateKey.FREE: "свободное изучение по цели",
    TemplateKey.EXAM: "подготовка к экзамену",
}
STARTING_LEVEL = {
    "beginner": "начинает с нуля — тема почти незнакома",
    "familiar": "что-то знает — есть отдельные знакомые темы",
    "refreshing": "повторяет забытое — раньше изучал",
}
TARGET_OUTCOME = {
    "awareness": "ориентироваться: узнавать термины и отвечать коротко по сути",
    "understanding": "понимать: объяснять определения и связи своими словами, приводить пример",
    "application": "уверенно отвечать: полный ответ без конспекта, типовые задачи",
    "mastery": "владеть свободно: связывать темы, решать нетиповые задачи",
}
PURPOSE = {
    "exam": "экзамен",
    "work": "работа",
    "interview": "собеседование",
    "interest": "интерес",
}
STUDY_FORMAT = {
    "theory": "только теория",
    "theory_and_practice": "теория и задачи",
    "practice": "больше практики",
}
GOAL_ROLE = {
    "target": "целевая тема",
    "prerequisite": "предпосылка к целевым темам",
    "related": "связанная тема",
}
SOURCE_ROLE = {
    SourceRole.MAIN: "основной",
    SourceRole.ADDITIONAL: "дополнительный",
    SourceRole.REFERENCE: "справочный",
}
MATERIAL_KIND = {
    MaterialSourceKind.FILE: "файл (PDF, документ)",
    MaterialSourceKind.TEXT: "текст",
    MaterialSourceKind.URL: "веб-страница",
    MaterialSourceKind.YOUTUBE: "расшифровка видео",
    MaterialSourceKind.AUDIO: "расшифровка аудиозаписи",
    MaterialSourceKind.TYPST: "исходник Typst",
}
TEMPLATE_TITLE: dict[str, str] = {
    "explain": "Объяснение с нуля",
    "guide": "Путеводитель по материалу",
    "practice": "Через практику",
    "cheatsheet": "Шпаргалка",
}
LEVEL_TITLE = {"draft": "Черновик", "standard": "Обычный", "detailed": "Подробный"}
BASIS_TITLE = {
    "sources": "только материалы проекта",
    "sources_and_model": "материалы проекта и знания модели",
    "model_only": "только знания модели",
}
EMPTY = "не указано"


@dataclass(frozen=True)
class MaterialState:
    """Что известно о материале темы — одна строка и причины деградации поиска."""

    label: str
    notes: tuple[str, ...] = ()


def _value(mapping: dict[str, str], raw: Any) -> str | None:
    if raw is None:
        return None
    key = getattr(raw, "value", raw)
    return mapping.get(key, key)


def _numbering(program: _Program) -> dict[UUID, str]:
    """Номер узла по порядку в дереве: «2.3» — третий пункт второго раздела."""
    numbers: dict[UUID, str] = {}
    counters: list[int] = []
    for node, depth in program.ordered:
        del counters[depth + 1 :]
        while len(counters) <= depth:
            counters.append(0)
        counters[depth] += 1
        numbers[node.id] = ".".join(str(item) for item in counters[: depth + 1])
    return numbers


def _path(program: _Program, node: ProgramNode, numbers: dict[UUID, str]) -> list[str]:
    by_id = {item.id: item for item, _ in program.ordered}
    chain: list[str] = []
    parent_id = node.parent_id
    while parent_id is not None and parent_id in by_id:
        parent = by_id[parent_id]
        chain.append(f"{numbers[parent.id]} {parent.title}")
        parent_id = parent.parent_id
    return list(reversed(chain))


def _study_order(program: _Program) -> list[ProgramNode]:
    return [node for node, _ in program.ordered if node.node_type in STUDY_NODE_TYPES]


def _known_concepts(
    session: Session, project_id: UUID, earlier: list[ProgramNode]
) -> list[str]:
    """Понятия уроков предыдущих тем: ближние первыми, без повторов, до предела."""
    if not earlier:
        return []
    rank = {node.id: index for index, node in enumerate(reversed(earlier))}
    rows = session.execute(
        select(LessonTopic.program_node_id, Lesson.build_meta)
        .join(Lesson, Lesson.id == LessonTopic.lesson_id)
        .where(Lesson.project_id == project_id, LessonTopic.program_node_id.in_(list(rank)))
    ).all()
    rows.sort(key=lambda row: rank[row[0]])
    concepts: list[str] = []
    seen: set[str] = set()
    for _, meta in rows:
        for concept in (meta or {}).get("concepts") or []:
            key = str(concept).strip().lower()
            if key and key not in seen:
                seen.add(key)
                concepts.append(str(concept).strip())
    return concepts[:KNOWN_CONCEPTS_LIMIT]


def _other_lessons(session: Session, node_id: UUID) -> list[str]:
    result: list[str] = []
    for lesson in session.scalars(
        select(Lesson)
        .join(LessonTopic, LessonTopic.lesson_id == Lesson.id)
        .where(LessonTopic.program_node_id == node_id)
        .order_by(Lesson.created_at)
    ):
        template = (lesson.build_meta or {}).get("template")
        suffix = f" · {TEMPLATE_TITLE.get(template, template)}" if template else ""
        result.append(f"«{lesson.title}»{suffix}")
    return result


def _conspect(session: Session, project_id: UUID, node_id: UUID) -> str:
    row = session.get(Conspect, (project_id, node_id))
    text = (row.content_markdown if row else "").strip()
    if count_tokens(text) <= CONSPECT_TOKENS:
        return text
    words = text.split()
    # Грубое усечение по словам: токены русского текста ≈ слова, точность здесь не нужна.
    return " ".join(words[:CONSPECT_TOKENS]) + " …"


def conspect_words(session: Session, project_id: UUID, node_id: UUID) -> int:
    row = session.get(Conspect, (project_id, node_id))
    return len((row.content_markdown if row else "").split())


def material_entry(
    material: Material, link: ProjectMaterial, name: str, page_range: tuple[int, int] | None
) -> dict[str, Any]:
    """Строка материала в паспорте: роль, приоритет, инструкция к источнику и диапазон темы."""
    kind = MATERIAL_KIND.get(material.source_kind, material.source_kind.value)
    return {
        "name": name,
        "role": SOURCE_ROLE[link.source_role],
        "priority": link.priority,
        "instruction": link.instruction,
        "kind": kind,
        "range": f"стр. {page_range[0]}–{page_range[1]}" if page_range else None,
    }


def build_brief(
    session: Session,
    *,
    project: Project,
    node: ProgramNode,
    order: dict[str, Any],
    materials: list[dict[str, Any]],
    material_state: MaterialState,
    use_conspect: bool,
) -> dict[str, Any]:
    """Собрать паспорт урока. `order` — заказ из диалога, `materials` — `material_entry`."""
    passport = session.get(GoalPassport, project.id)
    program = _load_program(session, project.id)
    numbers = _numbering(program)
    study = _study_order(program)
    position = next((i for i, item in enumerate(study) if item.id == node.id), None)
    earlier = study[:position] if position is not None else []
    later = study[position + 1 :] if position is not None else []
    children = [
        item
        for item, _ in program.ordered
        if item.parent_id == node.id and item.node_type in STUDY_NODE_TYPES
    ]
    siblings = [
        item.title
        for item, _ in program.ordered
        if item.parent_id == node.parent_id and item.id != node.id
    ]
    reader_fields = (
        "starting_level", "current_knowledge", "target_outcome", "goal",
        "success_criterion", "purpose", "study_format", "important", "excluded",
    )
    reader = {key: getattr(passport, key, None) for key in reader_fields}
    return {
        "project": {
            "name": project.name,
            "kind": PROJECT_KIND.get(project.template_key, project.template_key.value),
            "subject": passport.subject if passport else None,
        },
        "reader": {
            "starting_level": _value(STARTING_LEVEL, reader["starting_level"]),
            "current_knowledge": reader["current_knowledge"],
            "target_outcome": _value(TARGET_OUTCOME, reader["target_outcome"]),
            "goal": reader["goal"],
            "success_criterion": reader["success_criterion"],
            "purpose": _value(PURPOSE, reader["purpose"]),
            "study_format": _value(STUDY_FORMAT, reader["study_format"]),
            "important": reader["important"],
            "excluded": reader["excluded"],
        },
        "topic": {
            "number": numbers.get(node.id),
            "title": node.title,
            "type": "подпункт" if node.node_type == NodeType.SUBPOINT else "тема",
            "path": _path(program, node, numbers),
            "section_purpose": node.section_purpose,
            "goal_role": _value(GOAL_ROLE, node.goal_role),
            "target_level": _value(TARGET_OUTCOME, node.target_level),
            "origin_note": node.origin_note,
            "search_hint": list(node.material_search_queries or []),
            "material_kind": node.material_kind,
        },
        "subpoints": [
            {"title": item.title, "target_level": _value(TARGET_OUTCOME, item.target_level)}
            for item in children
        ],
        "place": {
            "position": position + 1 if position is not None else None,
            "total": len(study),
            "previous": [item.title for item in earlier[-PLACE_WINDOW:]],
            "next": [item.title for item in later[:PLACE_WINDOW]],
            "siblings": siblings,
        },
        "known": {
            "concepts": _known_concepts(session, project.id, earlier),
            "other_lessons": _other_lessons(session, node.id),
        },
        "materials": materials,
        "material_state": {"label": material_state.label, "notes": list(material_state.notes)},
        "conspect": _conspect(session, project.id, node.id) if use_conspect else None,
        "order": order,
    }


# --- текст для модели ------------------------------------------------------------------


def _line(label: str, value: Any) -> str:
    if value is None or value == "" or value == []:
        return f"- {label}: {EMPTY}"
    if isinstance(value, list):
        return f"- {label}: " + "; ".join(str(item) for item in value)
    return f"- {label}: {value}"


def _material_line(item: dict[str, Any]) -> str:
    parts = (
        item["name"], item["role"], f"приоритет {item['priority']}", item["kind"],
        item["range"] or "диапазона по оглавлению нет",
    )
    line = "- " + " · ".join(part for part in parts if part)
    if item["instruction"]:
        line += f"\n  Инструкция к источнику: {item['instruction']}"
    return line


def _order_lines(order: dict[str, Any]) -> list[str]:
    """Заказ урока. У дополнения готового урока шаблона и уровня нет — строк тоже нет."""
    template: LessonTemplate | None = order.get("template")
    lines = []
    if template:
        lines.append(_line("Шаблон", TEMPLATE_TITLE[template]))
    if order.get("level"):
        lines.append(_line("Уровень", LEVEL_TITLE[order["level"]]))
    return [
        *lines,
        _line("Основа", BASIS_TITLE[order["basis"]]),
        _line("Длина", f"≈{order['minutes']} мин чтения" if order.get("minutes") else None),
        _line("Пожелания к уроку", order.get("wishes")),
    ]


def render_brief(brief: dict[str, Any], *, compact: bool = False) -> str:
    """Паспорт текстом. Компактный — читатель, тема, место и заказ (для шагов)."""
    reader = brief["reader"]
    topic = brief["topic"]
    place = brief["place"]
    title = f"{topic['number']} {topic['title']}" if topic["number"] else topic["title"]
    sections: list[tuple[str, list[str]]] = []
    if not compact:
        project = brief["project"]
        sections.append(("Проект", [
            _line("Название", project["name"]),
            _line("Вид", project["kind"]),
            _line("Предмет", project["subject"]),
        ]))
    reader_lines = [
        _line("Стартовый уровень", reader["starting_level"]),
        _line("Что уже знает", reader["current_knowledge"]),
        _line("Желаемый результат", reader["target_outcome"]),
        _line("Цель", reader["goal"]),
    ]
    if not compact:
        reader_lines += [
            _line("Критерий успеха", reader["success_criterion"]),
            _line("Назначение", reader["purpose"]),
            _line("Формат", reader["study_format"]),
            _line("Что важно", reader["important"]),
            _line("Что пропустить", reader["excluded"]),
        ]
    sections.append(("Читатель", reader_lines))
    topic_lines = [
        _line("Тема", title),
        _line("Тип", topic["type"]),
        _line("Раздел", " › ".join(topic["path"]) if topic["path"] else None),
    ]
    if not compact:
        topic_lines += [
            _line("Назначение раздела", topic["section_purpose"]),
            _line("Роль темы в цели", topic["goal_role"]),
            _line("Целевой уровень темы", topic["target_level"]),
            _line("Почему тема в программе", topic["origin_note"]),
            _line("Где искать", topic["search_hint"]),
            _line("Вид источника", topic["material_kind"]),
        ]
    sections.append(("Тема", topic_lines))
    subpoints = [
        f"- {item['title']}"
        + (f" (уровень: {item['target_level']})" if item["target_level"] else "")
        for item in brief["subpoints"]
    ]
    sections.append(("Подпункты — урок обязан их покрыть", subpoints or [f"- {EMPTY}"]))
    position = (
        f"тема {place['position']} из {place['total']}" if place["position"] else None
    )
    place_lines = [
        _line("Место", position),
        _line("Три предыдущие темы", place["previous"]),
        _line("Три следующие темы — их не объяснять", place["next"]),
    ]
    if not compact:
        place_lines.append(_line("Соседние темы раздела", place["siblings"]))
    sections.append(("Место в программе", place_lines))
    known = brief["known"]
    sections.append(("Уже известно", [
        _line("Понятия из уроков предыдущих тем", known["concepts"]),
        _line("Другие уроки этой темы", known["other_lessons"]),
    ]))
    if not compact:
        materials = [_material_line(item) for item in brief["materials"]]
        sections.append(("Материалы", materials or ["- материалы не выбраны"]))
        state = brief["material_state"]
        sections.append(("Состояние материала по теме", [
            f"- {state['label']}", *(f"- {note}" for note in state["notes"])
        ]))
        conspect = brief.get("conspect")
        sections.append(("Мой конспект темы", [
            conspect if conspect else f"- {EMPTY}" if conspect is not None else "- не передаётся"
        ]))
    sections.append(("Заказ", _order_lines(brief["order"])))
    return "\n\n".join(
        f"## {heading}\n" + "\n".join(lines) for heading, lines in sections
    )
