"""Учебниковый календарь использует уроки, не меняя экзаменационный план."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.lesson_planning import service
from app.lesson_planning.schemas import (
    DistributionWrite,
    LessonPlanItem,
    LessonTimeBatch,
    LessonTimeInterval,
    PlanWrite,
)
from app.models import (
    GoalPassport,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonStatus,
    LessonTopic,
    ModuleKey,
    utc_now,
)
from app.preparation.calendar import day_bounds
from app.preparation.data import get_settings
from app.preparation.models import StudyInterval
from app.projects import service as project_service
from app.projects.errors import ProjectDomainError
from app.projects.schemas import (
    GoalPassportWrite,
    ProjectSettingsProjectWrite,
    ProjectSettingsWrite,
)
from tests.conftest import make_textbook_project, make_topic_node


def _project(session):
    project = make_textbook_project(session)
    project.enabled_modules = [ModuleKey.LESSONS.value, ModuleKey.LESSON_PLANNING.value]
    session.commit()
    return project


def _lesson(session, project, node, title, *, status=LessonStatus.READY, content=True):
    lesson = Lesson(
        id=uuid4(), project_id=project.id, title=title, status=status,
        duration_minutes=30, revision=1,
    )
    session.add(lesson)
    session.flush()
    session.add(
        LessonTopic(
            lesson_id=lesson.id, project_id=project.id, program_node_id=node.id,
            sort_order=0, topic_title_snapshot=node.title,
        )
    )
    if content:
        session.add(
            LessonBlock(
                id=uuid4(), lesson_id=lesson.id, sort_order=0,
                kind=LessonBlockKind.NOTE, origin=LessonBlockOrigin.MANUAL,
                body_md="Содержимое урока",
            )
        )
    session.commit()
    return lesson


def test_distribution_uses_ready_lessons_and_deadline_inclusively(session):
    project = _project(session)
    node = make_topic_node(session, project, title="Тема")
    lessons = [_lesson(session, project, node, str(i)) for i in range(3)]
    _lesson(session, project, node, "Пустой", content=False)
    _lesson(session, project, node, "Черновик", status=LessonStatus.DRAFT)
    today = service.overview(session, project.id).today
    project.deadline = today + timedelta(days=1)
    session.add(
        GoalPassport(project_id=project.id, minutes_per_day=30, days_per_week=7)
    )
    session.commit()

    preview = service.preview(session, project.id, DistributionWrite())

    assert len(preview.items) == 2
    assert {item.on_date for item in preview.items} == {today, project.deadline}
    assert set(preview.unassigned_ids) == {lessons[2].id}
    assert preview.estimated_finish == today + timedelta(days=2)


def test_no_deadline_and_manual_assignment_survive_rebuild(session):
    project = _project(session)
    node = make_topic_node(session, project, title="Тема")
    first = _lesson(session, project, node, "Первый")
    second = _lesson(session, project, node, "Второй")
    today = service.overview(session, project.id).today
    chosen = today + timedelta(days=10)
    manual = LessonPlanItem(
        id=uuid4(), lesson_id=first.id, title=first.title,
        on_date=chosen, minutes=30, origin="manual",
    )
    saved = service.save_plan(session, project.id, PlanWrite(expected_revision=0, items=[manual]))
    assert saved.revision == 1

    preview = service.preview(session, project.id, DistributionWrite(mode="rebuild_future"))

    assert manual in preview.items
    assert any(item.lesson_id == second.id for item in preview.items)
    assert not preview.unassigned_ids
    assert preview.estimated_finish == chosen
    with pytest.raises(ProjectDomainError) as stale:
        service.save_plan(session, project.id, PlanWrite(expected_revision=0, items=[]))
    assert stale.value.code == "lesson_plan_stale"


def test_time_requires_enabled_nonempty_lesson_and_is_idempotent(session):
    project = _project(session)
    node = make_topic_node(session, project, title="Тема")
    lesson = _lesson(session, project, node, "Урок")
    empty = _lesson(session, project, node, "Пустой", content=False)
    now = datetime.now(UTC)
    interval = LessonTimeInterval(
        id=uuid4(), session_id=uuid4(), lesson_id=lesson.id,
        started_at=now - timedelta(seconds=90), ended_at=now - timedelta(seconds=30),
    )
    result = service.add_intervals(session, project.id, LessonTimeBatch(intervals=[interval]))
    repeated = service.add_intervals(session, project.id, LessonTimeBatch(intervals=[interval]))
    assert result.accepted_ids == repeated.accepted_ids == [interval.id]
    assert session.get(StudyInterval, interval.id).lesson_title == "Урок"
    with pytest.raises(ProjectDomainError) as conflict:
        service.add_intervals(
            session, project.id,
            LessonTimeBatch(intervals=[interval.model_copy(update={"lesson_id": empty.id})]),
        )
    assert conflict.value.code == "study_interval_conflict"

    empty_interval = interval.model_copy(update={"id": uuid4(), "lesson_id": empty.id})
    ignored = service.add_intervals(
        session, project.id, LessonTimeBatch(intervals=[empty_interval])
    )
    assert ignored.ignored_ids == [empty_interval.id]

    project.enabled_modules = [ModuleKey.LESSONS.value]
    project.lesson_planning_disabled_at = utc_now()
    session.commit()
    after = interval.model_copy(update={
        "id": uuid4(), "started_at": now + timedelta(seconds=10),
        "ended_at": now + timedelta(seconds=20),
    })
    assert service.add_intervals(
        session, project.id, LessonTimeBatch(intervals=[after])
    ).ignored_ids == [after.id]


def test_completion_and_time_remain_separate(session):
    project = _project(session)
    node = make_topic_node(session, project, title="Тема")
    lesson = _lesson(session, project, node, "Урок")
    now = datetime.now(UTC)
    interval = LessonTimeInterval(
        id=uuid4(), session_id=uuid4(), lesson_id=lesson.id,
        started_at=now - timedelta(seconds=60), ended_at=now,
    )
    service.add_intervals(session, project.id, LessonTimeBatch(intervals=[interval]))
    lesson.completed_at = utc_now()
    session.commit()
    assert service.overview(session, project.id).today_seconds > 0
    lesson.completed_at = None
    session.commit()
    assert session.get(StudyInterval, interval.id) is not None


def test_overlapping_intervals_and_four_am_boundary(session):
    project = _project(session)
    node = make_topic_node(session, project, title="Тема")
    lesson = _lesson(session, project, node, "Урок")
    today = service.overview(session, project.id).today
    start, end = day_bounds(today, get_settings(session, project.id).config)
    first = StudyInterval(
        id=uuid4(), session_id=uuid4(), project_id=project.id,
        lesson_id=lesson.id, lesson_title=lesson.title, node_id=None, kind="lesson",
        started_at=(end - timedelta(seconds=60)).replace(tzinfo=None),
        ended_at=(end + timedelta(seconds=30)).replace(tzinfo=None),
    )
    second = StudyInterval(
        id=uuid4(), session_id=uuid4(), project_id=project.id,
        lesson_id=lesson.id, lesson_title=lesson.title, node_id=None, kind="lesson",
        started_at=(end - timedelta(seconds=30)).replace(tzinfo=None),
        ended_at=(end + timedelta(seconds=60)).replace(tzinfo=None),
    )
    session.add_all([first, second])
    session.commit()

    before, _ = service._today_time(session, project.id, today)
    after, _ = service._today_time(session, project.id, today + timedelta(days=1))

    assert before == 60
    assert after == 60


def test_program_change_keeps_unavailable_assignment_until_removed(session):
    project = _project(session)
    node = make_topic_node(session, project, title="Тема")
    lesson = _lesson(session, project, node, "Урок")
    today = service.overview(session, project.id).today
    item = LessonPlanItem(
        id=uuid4(), lesson_id=lesson.id, title=lesson.title,
        on_date=today + timedelta(days=1), minutes=30, origin="manual",
    )
    service.save_plan(session, project.id, PlanWrite(expected_revision=0, items=[item]))
    node.is_archived = True
    session.commit()

    changed = service.overview(session, project.id)
    assert changed.items == [item]
    assert changed.unavailable_ids == [item.id]
    removed = service.save_plan(
        session, project.id, PlanWrite(expected_revision=changed.revision, items=[])
    )
    assert removed.items == []


def test_settings_switch_records_disable_boundary(session):
    project = _project(session)
    before = datetime.now(UTC).replace(tzinfo=None)
    project_service.update_project_settings(
        session, project.id,
        ProjectSettingsWrite(
            project=ProjectSettingsProjectWrite(
                name=project.name, enabled_modules=[ModuleKey.LESSONS]
            ),
            goal_passport=GoalPassportWrite(),
        ),
    )

    session.refresh(project)
    assert ModuleKey.LESSON_PLANNING.value not in project.enabled_modules
    assert project.lesson_planning_disabled_at is not None
    assert project.lesson_planning_disabled_at >= before
