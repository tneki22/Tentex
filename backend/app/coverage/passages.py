"""Куски чтения: подряд идущие опоры темы вместо отдельных фрагментов.

Проход 2 публикует привязку на каждый фрагмент — строку, пункт списка, формулу, — а
читать и вставлять в урок нужно связный текст. Кусок — непрерывный отрезок одного
материала в порядке чтения, где опоры темы идут подряд. Номера страниц, заголовки и
рисунки между ними кусок не рвут и входят в него (рисунок остаётся рядом с подписью),
пара несвязанных строк — тоже, а содержание другой темы рвёт. Это приём
auto-merging retrieval: найдено достаточно соседних мелких единиц — отдаётся их общий
отрезок. На «Мат логике» 2163 карточки-фрагмента сворачиваются в 171 кусок.

Модуль ничего не пишет: привязки и решения остаются пофрагментными, кусок — только
способ их показать и выбрать все разом.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Binding,
    BindingStatus,
    BlockClass,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
)

ACTIVE_STATUSES = (BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE)
PAGE_NUMBER = re.compile(r"\s*\d{1,4}\s*")
TRANSPARENT_KINDS = {"heading", "title", "image"}
#: Столько несвязанных строк подряд кусок перешагивает: «Решение.» между шагами примера.
MAX_SOFT_GAP = 2
#: Длинная глава делится на куски по границам блоков: карточку нужно уметь прочитать.
MAX_PAGES = 6
#: Упоминание темы не длиннее этого — заголовок, даже если разбор счёл его абзацем.
HEADING_CHARS = 160
ROLE_ORDER = ("definition", "explanation", "example", "exercise", "reference")
QUALITY_ORDER = ("native", "ocr", "ocr_low")
PREVIEW_CHARS = 420
#: Параметров в одном IN: с запасом ниже старого предела SQLite в 999.
SQL_BATCH = 900


def role_group(roles: list[str]) -> str:
    """Группа чтения по ролям: определение сильнее примера.

    Раньше группу давала первая роль из `example/exercise/reference`, и раздел с ролями
    «definition, explanation, example» уезжал в «Примеры и практику» — на «Мат логике»
    так ушли 204 определения.
    """
    present = set(roles)
    if "definition" in present:
        return "explanations"
    if present & {"example", "exercise"}:
        return "practice"
    if "explanation" in present:
        return "explanations"
    if "reference" in present:
        return "depth"
    return "explanations"


def category(item: dict) -> str:
    """Скрытое, прежнее и упоминания читаются отдельно от содержательных опор."""
    if item["hidden"]:
        return "hidden"
    if item["legacy"] or item["stale"]:
        return "legacy"
    if item["semantic_kind"] == "mention":
        return "mentions"
    return "content"


@dataclass(frozen=True, slots=True)
class _Unit:
    """Фрагмент последовательности чтения с тем, что нужно для решения о разрыве."""

    id: UUID
    order: int
    page: int
    block_id: UUID
    block_title: str | None
    kind: str
    text: str
    is_content: bool

    @property
    def transparent(self) -> bool:
        return (
            not self.is_content
            or self.kind in TRANSPARENT_KINDS
            or bool(PAGE_NUMBER.fullmatch(self.text))
        )

    @property
    def page_number(self) -> bool:
        return bool(PAGE_NUMBER.fullmatch(self.text))


@dataclass
class _Draft:
    units: list[_Unit] = field(default_factory=list)
    members: list[tuple[_Unit, dict]] = field(default_factory=list)
    #: Заголовок перед первой опорой: название куска и его первая строка.
    heading: _Unit | None = None

    @property
    def last_member(self) -> tuple[_Unit, dict]:
        return self.members[-1]


def _sequence(
    session: Session, material_id: UUID, revision: int, page_from: int, page_to: int
) -> list[_Unit]:
    """Фрагменты диапазона страниц одной ревизии в порядке чтения."""
    rows = session.execute(
        select(
            MaterialFragment.id,
            MaterialPage.page_number,
            MaterialFragment.block_id,
            MaterialBlock.title,
            MaterialFragment.element_kind,
            MaterialFragment.text,
            MaterialBlock.block_class,
        )
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(
            MaterialPage.material_id == material_id,
            MaterialPage.revision == revision,
            MaterialPage.page_number.between(page_from, page_to),
        )
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
    )
    return [
        _Unit(
            fragment_id, order, page, block_id, title, kind, text or "",
            block_class == BlockClass.CONTENT,
        )
        for order, (fragment_id, page, block_id, title, kind, text, block_class) in enumerate(rows)
    ]


def _foreign_content(
    session: Session, project_id: UUID, node_id: UUID, fragment_ids: list[UUID]
) -> set[UUID]:
    """Фрагменты отрезка, которые раскрывают другую тему: на них кусок рвётся.

    Ищется по индексу «проект, фрагмент» пачками: соединение со страницами по всему
    материалу стоило полсекунды на тему.
    """
    found: set[UUID] = set()
    for start in range(0, len(fragment_ids), SQL_BATCH):
        found.update(
            session.scalars(
                select(Binding.fragment_id).where(
                    Binding.project_id == project_id,
                    Binding.fragment_id.in_(fragment_ids[start : start + SQL_BATCH]),
                    Binding.program_node_id != node_id,
                    Binding.status.in_(ACTIVE_STATUSES),
                    Binding.semantic_kind == "content",
                )
            )
        )
    return found


def _leading(pending: list[_Unit], markers: set[UUID]) -> list[_Unit]:
    """Заголовок прямо перед первой опорой становится началом и названием куска.

    Заголовок раздела проход 2 почти всегда размечает упоминанием, а разбор PDF не
    всегда узнаёт в нём заголовок: «1.13. Совершенные…» у Афанасьева — абзац. Поэтому
    заголовком считается и короткое упоминание этой же темы.
    """
    for index in range(len(pending) - 1, -1, -1):
        unit = pending[index]
        marker = unit.id in markers
        if not (unit.transparent or marker):
            return []
        if unit.kind in {"heading", "title"} or (marker and len(unit.text) <= HEADING_CHARS):
            return [item for item in pending[index:] if not item.page_number]
    return []


def _split_here(draft: _Draft, unit: _Unit, item: dict, grouped: bool) -> bool:
    """Новый блок с другой ролью или слишком длинный кусок начинают новый кусок."""
    last_unit, last_item = draft.last_member
    if unit.block_id == last_unit.block_id:
        return False
    if unit.page - draft.units[0].page >= MAX_PAGES:
        return True
    return grouped and role_group(item["roles"]) != role_group(last_item["roles"])


def _walk(
    sequence: list[_Unit],
    members: dict[UUID, dict],
    foreign: set[UUID],
    grouped: bool,
    markers: set[UUID],
) -> list[_Draft]:
    """Пройти материал по порядку и собрать куски из опор `members`.

    `markers` — упоминания этой же темы (заголовки «Свойства совершенства:», «Пример:»):
    внутри куска они его не рвут, перед куском становятся его заголовком.
    """
    drafts: list[_Draft] = []
    current: _Draft | None = None
    pending: list[_Unit] = []
    soft = 0
    for unit in sequence:
        item = members.get(unit.id)
        if item is not None:
            if current is not None and _split_here(current, unit, item, grouped):
                drafts.append(current)
                current = None
            if current is None:
                leading = _leading(pending, markers)
                current = _Draft(units=leading, heading=leading[0] if leading else None)
            else:
                current.units.extend(pending)
            current.units.append(unit)
            current.members.append((unit, item))
            pending, soft = [], 0
            continue
        if unit.id in foreign and not unit.transparent:
            if current is not None:
                drafts.append(current)
            current, pending, soft = None, [], 0
            continue
        pending.append(unit)
        if not (unit.transparent or unit.id in markers):
            soft += 1
            if soft > MAX_SOFT_GAP and current is not None:
                drafts.append(current)
                current = None
    if current is not None:
        drafts.append(current)
    return drafts


def _passage(draft: _Draft) -> dict:
    items = [item for _, item in draft.members]
    first = items[0]
    units = draft.units
    heading = draft.heading
    title = (heading.text if heading else draft.members[0][0].block_title) or ""
    body = [
        unit.text.strip()
        for unit in units
        if unit is not heading and not unit.page_number and unit.kind != "image"
    ]
    preview = " ".join(" ".join(body).split())
    roles = sorted(
        {role for item in items for role in item["roles"]},
        key=lambda role: ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER),
    )
    groups = Counter(role_group(item["roles"]) for item in items)
    statuses = {item["status"] for item in items}
    status = (
        "manual" if "manual" in statuses
        else "confirmed" if statuses == {"confirmed"}
        else "machine"
    )
    kinds = [item["semantic_kind"] for item in items]
    return {
        **{key: value for key, value in first.items() if key.startswith("_")},
        "id": first["id"],
        "binding_id": first["binding_id"],
        "binding_ids": [item["binding_id"] for item in items],
        "member_ids": [item["id"] for item in items],
        "topic_id": first["topic_id"],
        "material_id": first["material_id"],
        "material_name": first["material_name"],
        "title": " ".join(title.split())[:160],
        "page_from": units[0].page,
        "page_to": units[-1].page,
        "from_fragment_id": str(units[0].id),
        "to_fragment_id": str(units[-1].id),
        "fragment_ids": [item["fragment_ids"][0] for item in items],
        "fragment_count": len(items),
        "quote": preview[:PREVIEW_CHARS] + ("…" if len(preview) > PREVIEW_CHARS else ""),
        "text": "\n".join(body),
        "description": first["description"],
        "roles": roles,
        "group": groups.most_common(1)[0][0] if groups else "explanations",
        "semantic_kind": "content" if "content" in kinds else kinds[0],
        "status": status,
        "mechanism": first["mechanism"],
        "quality": max(
            (item["quality"] for item in items),
            key=lambda value: QUALITY_ORDER.index(value) if value in QUALITY_ORDER else 0,
        ),
        "available": all(item["available"] for item in items),
        "stale": any(item["stale"] for item in items),
        "hidden": all(item["hidden"] for item in items),
        "preferred": any(item["preferred"] for item in items),
        "legacy": all(item["legacy"] for item in items),
        "_position": (units[0].page, units[0].order),
    }


def build(session: Session, project_id: UUID, node_id: UUID, items: list[dict]) -> list[dict]:
    """Свернуть пофрагментные опоры темы в куски; порядок — порядок чтения материала.

    Каждая опора несёт служебные `_material`, `_revision`, `_page`: по ним берётся
    последовательность фрагментов её ревизии. Одна выборка фрагментов и одна выборка
    чужих связей на пару «материал, ревизия» — сотня опор не даёт сотни запросов.
    """
    by_scope: dict[tuple[UUID, int], list[dict]] = defaultdict(list)
    for item in items:
        by_scope[(item["_material"], item["_revision"])].append(item)
    passages: list[dict] = []
    for (material_id, revision), scoped in by_scope.items():
        pages = [item["_page"] for item in scoped]
        sequence = _sequence(session, material_id, revision, min(pages), max(pages))
        foreign = _foreign_content(session, project_id, node_id, [unit.id for unit in sequence])
        by_category: dict[str, dict[UUID, dict]] = defaultdict(dict)
        for item in scoped:
            by_category[category(item)][UUID(item["fragment_ids"][0])] = item
        known = {unit.id for unit in sequence}
        markers = set(by_category["mentions"])
        covered: set[UUID] = set()
        # Содержательные куски первыми: упоминание внутри куска уже прочитано вместе
        # с ним и отдельной карточкой в «Упоминаниях» только шумит.
        # Скрытое пользователем рвёт кусок: иначе сосед снова втянул бы его в чтение.
        blocked = foreign | set(by_category["hidden"])
        for name in sorted(by_category, key=lambda value: value != "content"):
            members = by_category[name]
            drafts = _walk(sequence, members, blocked, name == "content", markers)
            for draft in drafts:
                inside = [unit for unit, _ in draft.members]
                if name == "content":
                    covered.update(unit.id for unit in draft.units)
                elif name in {"mentions", "legacy"} and all(
                    unit.id in covered or unit.page_number for unit in inside
                ):
                    continue
                passages.append({**_passage(draft), "category": name})
            # Фрагмента нет в выборке только при сбое данных — опора не теряется.
            for fragment_id, item in members.items():
                if fragment_id not in known:
                    unit = _Unit(fragment_id, -1, item["_page"], UUID(int=0), None,
                                 "paragraph", item["quote"], True)
                    lone = _Draft(units=[unit], members=[(unit, item)])
                    passages.append({**_passage(lone), "category": name})
    return passages
