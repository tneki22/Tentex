"""Вычислимые назначения SM-2 собирают вопросы билета по ближайшему сроку."""

from datetime import timedelta
from uuid import uuid5

from app.preparation.calendar import study_date
from app.preparation.evidence import project_attempts, replay
from app.preparation.schemas import PlanItem


def due_items(session, project_id, config, unit_rows, existing, completed, deadline):
    """Автоповтор не редактирует план и исчезает после следующей проверки."""
    evidence = replay(project_attempts(session, project_id), config)
    result = []
    for unit in unit_rows:
        dues = [
            study_date(evidence[t].last_at, config) + timedelta(days=evidence[t].state.interval)
            for t in unit.topic_ids
            if t in evidence and evidence[t].last_at
        ]
        if not dues:
            continue
        due = min(dues)
        if deadline and due > deadline:
            continue
        key = uuid5(project_id, f"review:{unit.id}:{due.isoformat()}")
        if any(
            i.id == key
            or (
                i.unit_id == unit.id
                and i.kind in {"review", "final", "gaps"}
                and i.on_date <= due
                and i.id not in completed
            )
            for i in existing
        ):
            continue
        result.append(
            PlanItem(
                id=key,
                unit_id=unit.id,
                on_date=due,
                kind="review",
                minutes=max(1, round(unit.minutes * 0.5)),
                origin="local",
                estimate_source=unit.estimate_source,
                reason="Повторение SM-2 по ближайшему сроку",
            )
        )
    return result
