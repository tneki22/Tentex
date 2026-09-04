"""Контекст подготовки: ни обрезки дерева, ни разбиения билета между пакетами."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.preparation import planner, reporting
from app.preparation.schemas import OverviewRead, PreparationAiWrite, UnitRead
from app.projects.program_context import build_program_context

# Ограничиваем размер ответа и рабочего пакета, а не обрезаем исходные вопросы.
BATCH_UNITS = 20
BATCH_BYTES = 24_000


@dataclass
class PreparationContext:
    """Один снимок используется всеми стадиями последовательного запуска."""

    overview: OverviewRead
    program: list[dict]
    fingerprint: str


def build_context(
    session: Session, project_id: UUID, command: PreparationAiWrite, now: datetime | None = None
) -> PreparationContext:
    """Проверить ревизии и прочесть программу целиком в серверном порядке."""
    now = now or datetime.now(UTC)
    planner.validate_revisions(
        session,
        project_id,
        command.expected_plan_revision,
        command.expected_program_revision,
        command.expected_settings_revision,
    )
    overview = reporting.overview(session, project_id, now=now)
    program = build_program_context(session, project_id)
    digest = hashlib.sha256(
        json.dumps(program, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return PreparationContext(overview, program, digest)


def protected_items(context: PreparationContext):
    """Выполнение, прошлые даты и закрепления нельзя переписать предложением ИИ."""
    view = context.overview
    return [
        item
        for item in view.plan.items
        if item.pinned or item.on_date < view.today or item.id in view.plan.completed_ids
    ]


def pending_units(context: PreparationContext) -> list[UnitRead]:
    """Первичное назначение защищённой единицы не дублируется новым планом."""
    assigned = {
        item.unit_id for item in protected_items(context) if item.kind in {"learn", "answer"}
    }
    return [unit for unit in context.overview.units if unit.id not in assigned]


def unit_batches(context: PreparationContext) -> list[list[UnitRead]]:
    """Пакет содержит только целые единицы, каждый исходный unit встречается однажды."""
    batches, current, size = [], [], 0
    for unit in pending_units(context):
        unit_size = len(json.dumps(unit.model_dump(mode="json"), ensure_ascii=False).encode())
        if current and (len(current) >= BATCH_UNITS or size + unit_size > BATCH_BYTES):
            batches.append(current)
            current, size = [], 0
        current.append(unit)
        size += unit_size
    if current:
        batches.append(current)
    return batches


def batch_program(context: PreparationContext, units: list[UnitRead]) -> list[dict]:
    """Передать все разделы и всех потомков выбранных билетов/вопросов без потерь."""
    selected = {str(unit.id) for unit in units}
    selected.update(str(topic) for unit in units for topic in unit.topic_ids)
    for node in context.program:
        if node["parent_id"] in selected:
            selected.add(node["id"])
    return [
        node for node in context.program if node["node_type"] == "section" or node["id"] in selected
    ]


def facts(context: PreparationContext) -> dict[str, str]:
    """Текст факта формирует сервер, модель не подменяет числа или статус знаний."""
    view = context.overview
    today = next((day for day in view.days if day.date == view.today), None)
    yesterday = next((day for day in view.days if day.date == view.today - timedelta(days=1)), None)
    return {
        "today": f"Сегодня доступно {today.remaining_minutes if today else 0} минут.",
        "remaining": f"Осталось работы на {view.summary.remaining_work_minutes} минут; "
        f"доступно {view.summary.available_minutes} минут.",
        "yesterday": f"Вчера завершено {yesterday.completed_count if yesterday else 0} из "
        f"{yesterday.planned_count if yesterday else 0} заданий.",
    }
