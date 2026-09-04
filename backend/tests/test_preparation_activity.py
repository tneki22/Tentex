from datetime import UTC, datetime, timedelta
from uuid import uuid4

from conftest import make_exam_project, make_topic_node

from app.preparation.activity import add_intervals, save_manual, time_totals
from app.preparation.schemas import (
    ManualActivityWrite,
    PreparationConfig,
    TimeBatchWrite,
    TimeIntervalWrite,
)


def test_two_tabs_are_unioned_and_repeated_delivery_and_manual_seconds_do_not_duplicate(
    session,
) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    started = datetime.now(UTC) - timedelta(days=1, hours=2)
    session_id = uuid4()
    command = TimeBatchWrite(
        intervals=[
            TimeIntervalWrite(
                id=uuid4(),
                session_id=session_id,
                node_id=node.id,
                kind="reading",
                started_at=started,
                ended_at=started + timedelta(minutes=5),
            ),
            TimeIntervalWrite(
                id=uuid4(),
                session_id=uuid4(),
                node_id=node.id,
                kind="reading",
                started_at=started + timedelta(minutes=2),
                ended_at=started + timedelta(minutes=7),
            ),
        ]
    )

    add_intervals(session, project.id, command)
    add_intervals(session, project.id, command)
    save_manual(
        session,
        project.id,
        ManualActivityWrite(
            id=uuid4(), node_id=node.id, occurred_at=started, seconds=120, note="Разбор"
        ),
    )

    by_kind, by_node = time_totals(
        session, project.id, started.date(), PreparationConfig(timezone="UTC")
    )
    assert by_kind == {"reading": 7 * 60, "manual": 120}
    assert by_node[node.id] == 9 * 60
