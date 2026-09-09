from datetime import UTC, datetime, timedelta
from uuid import uuid4

from conftest import make_exam_project, make_topic_node

from app.preparation import progress, queue
from app.preparation.activity import add_intervals, history, save_manual, time_totals
from app.preparation.calendar import naive_utc, study_date
from app.preparation.data import get_settings
from app.preparation.models import StudyInterval
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
    started = datetime.now(UTC) - timedelta(minutes=10)
    queue.start_queue(session, project.id, now=started)
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


def test_interval_before_day_start_is_acknowledged_without_counting(session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    started = datetime.now(UTC) - timedelta(minutes=2)
    interval_id = uuid4()
    command = TimeBatchWrite(
        intervals=[
            TimeIntervalWrite(
                id=interval_id,
                session_id=uuid4(),
                node_id=node.id,
                kind="reading",
                started_at=started,
                ended_at=started + timedelta(minutes=1),
            )
        ]
    )

    result = add_intervals(session, project.id, command)

    assert result.accepted_ids == []
    assert result.ignored_ids == [interval_id]
    assert session.get(StudyInterval, interval_id) is None


def test_legacy_automatic_facts_before_start_are_hidden_from_metrics(session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    started = datetime.now(UTC) - timedelta(minutes=2)
    config = get_settings(session, project.id).config
    session.add(
        StudyInterval(
            id=uuid4(),
            project_id=project.id,
            session_id=uuid4(),
            node_id=node.id,
            kind="reading",
            started_at=naive_utc(started),
            ended_at=naive_utc(started + timedelta(minutes=1)),
        )
    )
    progress.record_event(
        session,
        project.id,
        "view",
        node.title,
        key="legacy-view",
        node_id=node.id,
        at=started,
    )
    session.commit()

    assert time_totals(
        session, project.id, study_date(started, config), config
    ) == ({}, {})
    assert history(session, project.id, node_id=node.id).items == []


def test_interval_crossing_day_start_is_clamped_to_the_started_part(session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    day_started = datetime.now(UTC) - timedelta(minutes=2)
    queue.start_queue(session, project.id, now=day_started)
    interval_id = uuid4()

    result = add_intervals(
        session,
        project.id,
        TimeBatchWrite(
            intervals=[
                TimeIntervalWrite(
                    id=interval_id,
                    session_id=uuid4(),
                    node_id=node.id,
                    kind="reading",
                    started_at=day_started - timedelta(minutes=1),
                    ended_at=day_started + timedelta(minutes=1),
                )
            ]
        ),
    )

    stored = session.get(StudyInterval, interval_id)
    assert result.accepted_ids == [interval_id]
    assert stored is not None
    assert stored.started_at == day_started.replace(tzinfo=None)
    assert (stored.ended_at - stored.started_at).total_seconds() == 60


def test_history_combines_adjacent_time_and_hides_redundant_view(session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вопрос")
    started = datetime.now(UTC) - timedelta(minutes=3)
    queue.start_queue(session, project.id, now=started)
    progress.record_opening(session, project.id, node.id)
    add_intervals(
        session,
        project.id,
        TimeBatchWrite(
            intervals=[
                TimeIntervalWrite(
                    id=uuid4(),
                    session_id=uuid4(),
                    node_id=node.id,
                    kind="reading",
                    started_at=started,
                    ended_at=started + timedelta(minutes=1),
                ),
                TimeIntervalWrite(
                    id=uuid4(),
                    session_id=uuid4(),
                    node_id=node.id,
                    kind="reading",
                    started_at=started + timedelta(minutes=2),
                    ended_at=started + timedelta(minutes=3),
                ),
            ]
        ),
    )

    rows = history(session, project.id, node_id=node.id).items

    assert len(rows) == 1
    assert rows[0].kind == "reading"
    assert rows[0].seconds == 120
