"""Задания урока: проверка семи форм, отбраковка черновиков, предложение, попытки."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import FakeTransport
from app.lessons import ai_practice, proposals, service, task_check, tasks
from app.lessons.ai_prompts import TaskDraft
from app.lessons.ai_schemas import LessonProposalApplyWrite
from app.lessons.task_schemas import LessonPracticeWrite, StudyTaskAttemptWrite
from app.models import (
    AttemptOutcome,
    BackgroundJob,
    BackgroundJobState,
    GradeMethod,
    LessonBasis,
    LessonBlockKind,
    StudyTask,
    StudyTaskForm,
)
from app.projects.errors import ProjectDomainError
from tests.test_lesson_proposals import _lesson, _reply, _undo
from tests.test_lessons import make_lessons_project

PASSED, PARTIAL, FAILED = AttemptOutcome.PASSED, AttemptOutcome.PARTIAL, AttemptOutcome.FAILED


@pytest.fixture
def project(session: Session, ai_config: str):
    del ai_config
    return make_lessons_project(session)


def _draft(form, **fields) -> dict:
    base = {
        "form": form, "prompt_md": "Условие", "options": None, "correct": None, "blanks": None,
        "value": None, "tolerance": None, "relative": None, "unit": None, "steps": None,
        "pairs": None, "reference_md": None, "points": None,
        "explanation_md": "Потому что так в куске [S1].", "hint_md": None,
        "difficulty": "understand", "after_block": None,
    }
    return {**base, **fields}


def _prepare(**fields):
    return tasks.prepare(TaskDraft.model_validate(_draft(**fields)), {"S1"},
                         LessonBasis.SOURCES_AND_MODEL)


# --- проверка по ключу ---------------------------------------------------------------------


def test_choice_forms_check_by_key():
    single = {"options": ["a", "b", "c"]}
    assert task_check.check(StudyTaskForm.SINGLE_CHOICE, single, {"correct": [1]},
                            {"choice": 1}).outcome == PASSED
    assert task_check.check(StudyTaskForm.SINGLE_CHOICE, single, {"correct": [1]},
                            {"choice": 2}).outcome == FAILED
    many = {"options": ["a", "b", "c", "d"]}
    key = {"correct": [0, 2]}
    assert task_check.check(StudyTaskForm.MULTIPLE_CHOICE, many, key,
                            {"choices": [0, 2]}).outcome == PASSED
    partial = task_check.check(StudyTaskForm.MULTIPLE_CHOICE, many, key, {"choices": [0]})
    assert partial.outcome == PARTIAL and partial.score == 0.5
    # «Отметить всё» не проходит: лишний выбор снимает столько же, сколько даёт верный.
    everything = task_check.check(StudyTaskForm.MULTIPLE_CHOICE, many, key,
                                  {"choices": [0, 1, 2, 3]})
    assert everything.outcome == FAILED
    with pytest.raises(task_check.AnswerShapeError):
        task_check.check(StudyTaskForm.SINGLE_CHOICE, single, {"correct": [1]}, {"choice": 7})


def test_blanks_ignore_case_yo_spaces_and_accept_numbers():
    key = {"answers": [["Ёмкость", "емкость канала"], ["64"]]}
    result = task_check.check(StudyTaskForm.FILL_BLANKS, {"blanks": 2}, key,
                              {"blanks": ["  ЕМКОСТЬ  канала.", "64 байта"]})
    assert result.outcome == PASSED and result.items == [True, True]
    wrong = task_check.check(StudyTaskForm.FILL_BLANKS, {"blanks": 2}, key,
                             {"blanks": ["скорость", "64,0"]})
    assert wrong.outcome == PARTIAL and wrong.items == [False, True]
    # Число в ключе засчитывается числом, но не «10» за «10BASE-T».
    words = {"answers": [["10BASE-T"]]}
    assert task_check.check(StudyTaskForm.FILL_BLANKS, {"blanks": 1}, words,
                            {"blanks": ["10"]}).outcome == FAILED


def test_numeric_tolerance_absolute_and_relative():
    absolute = {"value": 51.2, "tolerance": 0.1, "relative": False}
    assert task_check.check(StudyTaskForm.NUMERIC, {"unit": "мкс"}, absolute,
                            {"value": "51,25 мкс"}).outcome == PASSED
    assert task_check.check(StudyTaskForm.NUMERIC, {"unit": "мкс"}, absolute,
                            {"value": "51.4"}).outcome == FAILED
    relative = {"value": 1000, "tolerance": 0.05, "relative": True}
    assert task_check.check(StudyTaskForm.NUMERIC, {}, relative,
                            {"value": "1 040"}).outcome == PASSED
    exact = {"value": 1500, "tolerance": 0, "relative": False}
    assert task_check.check(StudyTaskForm.NUMERIC, {}, exact, {"value": 1500}).outcome == PASSED
    with pytest.raises(task_check.AnswerShapeError):
        task_check.check(StudyTaskForm.NUMERIC, {}, exact, {"value": "много"})


def test_ordering_and_matching_give_partial_credit():
    ordering = task_check.check(StudyTaskForm.ORDERING, {"items": ["x", "y", "z"]},
                                {"order": [2, 0, 1]}, {"order": [2, 1, 0]})
    assert ordering.outcome == PARTIAL and ordering.items == [True, False, False]
    with pytest.raises(task_check.AnswerShapeError):
        task_check.check(StudyTaskForm.ORDERING, {"items": ["x", "y", "z"]},
                         {"order": [2, 0, 1]}, {"order": [0, 0, 1]})
    pairs = {"left": ["a", "b", "c"], "right": ["3", "1", "2"]}
    matching = task_check.check(StudyTaskForm.MATCHING, pairs, {"match": [1, 2, 0]},
                                {"pairs": [1, 0, None]})
    assert matching.outcome == PARTIAL and matching.items == [True, False, False]


# --- черновик модели → задание ------------------------------------------------------------


def test_prepare_rejects_invalid_forms():
    problems = [
        _prepare(form="single_choice", options=["a", "b", "c"], correct=[1, 2]),
        _prepare(form="multiple_choice", options=["a", "b", "c"], correct=[5]),
        _prepare(form="fill_blanks", prompt_md="Есть {{1}} и {{2}}", blanks=[["x"]]),
        _prepare(form="fill_blanks", prompt_md="Без пропусков", blanks=[["x"]]),
        _prepare(form="numeric", value=None),
        _prepare(form="ordering", steps=["a", "b", "a"]),
        _prepare(form="matching", pairs=[{"left": "a", "right": "1"}, {"left": "b", "right": "1"},
                                         {"left": "c", "right": "2"}]),
        _prepare(form="open_answer", reference_md="  "),
    ]
    assert all(isinstance(item, str) for item in problems), problems


def test_prepared_key_matches_shuffled_payload():
    ordering = _prepare(form="ordering", prompt_md="Порядок",
                        steps=["один", "два", "три", "четыре"])
    assert ordering.payload["items"] != ["один", "два", "три", "четыре"]
    shown = [ordering.payload["items"][index] for index in ordering.answer_key["order"]]
    assert shown == ["один", "два", "три", "четыре"]
    assert task_check.check(StudyTaskForm.ORDERING, ordering.payload, ordering.answer_key,
                            {"order": ordering.answer_key["order"]}).outcome == PASSED

    matching = _prepare(form="matching", prompt_md="Пары", pairs=[
        {"left": "MAC", "right": "доступ к среде"}, {"left": "LLC", "right": "логический канал"},
        {"left": "PHY", "right": "сигналы"},
    ])
    right = matching.payload["right"]
    assert [right[index] for index in matching.answer_key["match"]] == [
        "доступ к среде", "логический канал", "сигналы",
    ]
    choice = _prepare(form="single_choice", options=["a", "b", "c"], correct=[2],
                      explanation_md="Так [S1] и [S7].")
    assert choice.answer_key == {"correct": [1]} and choice.supports == ["S1"]
    assert "[S" not in choice.explanation_md


# --- предложение, попытки и отмена -----------------------------------------------------------


def _practice(session, project, lesson, drafts, summary="Задания на понимание"):
    started = asyncio.run(ai_practice.start(session, project.id, lesson.id, LessonPracticeWrite(
        expected_revision=lesson.revision, count=3,
    )))
    job = session.get(BackgroundJob, started.job_id)
    process_ai_job(session, job, ModelGateway(session, FakeTransport(completions=[
        _reply({"summary": summary, "tasks": drafts}),
    ]), retry_backoff=()))
    session.expire_all()
    return session.get(BackgroundJob, started.job_id)


def _attempt(session, project, lesson_id, activity_id, gateway=None, **answer):
    return asyncio.run(tasks.submit_attempt(
        session, gateway or ModelGateway(session, FakeTransport(completions=[])),
        project.id, lesson_id, activity_id, StudyTaskAttemptWrite(**answer),
    ))


def test_practice_proposal_applies_tasks_and_checks_attempts(session, project):
    lesson = _lesson(session, project)
    job = _practice(session, project, lesson, [
        _draft("single_choice", prompt_md="Что делят станции?", options=["среду", "адрес", "кадр"],
               correct=[1], after_block="B2"),
        _draft("fill_blanks", prompt_md="Одновременная передача — {{1}}.",
               blanks=[["коллизия", "коллизией"]]),
        _draft("single_choice", prompt_md="Сломанное", options=["a", "b"], correct=[1, 2]),
    ])

    assert job.state == BackgroundJobState.COMPLETED, job.error
    result = job.checkpoint["result"]
    assert result["kind"] == "practice"
    assert [op["op"] for op in result["ops"]] == ["insert_task", "insert_task"]
    assert len(result["dropped"]) == 1 and "Задание 3" in result["dropped"][0]

    applied = proposals.apply_proposal(
        session, project.id, lesson.id, job.id, LessonProposalApplyWrite(
            op_ids=[op["id"] for op in result["ops"]], expected_revision=lesson.revision,
        ),
    )
    kinds = [block.kind for block in applied.lesson.blocks]
    assert kinds == [LessonBlockKind.NOTE, LessonBlockKind.SOURCE, LessonBlockKind.ACTIVITY,
                     LessonBlockKind.NOTE, LessonBlockKind.ACTIVITY]
    choice, blanks = applied.lesson.blocks[2].task, applied.lesson.blocks[4].task
    assert choice.form == StudyTaskForm.SINGLE_CHOICE and choice.sources[0].page_from == 10
    assert blanks.form == StudyTaskForm.FILL_BLANKS

    wrong = _attempt(session, project, lesson.id, choice.activity_id, answer={"choice": 1})
    right = _attempt(session, project, lesson.id, choice.activity_id, answer={"choice": 0})
    assert (wrong.outcome, right.outcome) == (FAILED, PASSED)
    assert right.method == GradeMethod.EXACT_MATCH and right.ordinal == 2
    filled = _attempt(session, project, lesson.id, blanks.activity_id,
                      answer={"blanks": ["Коллизией"]})
    assert filled.outcome == PASSED
    with pytest.raises(ProjectDomainError):
        _attempt(session, project, lesson.id, blanks.activity_id, answer={"choice": 0})

    read = service.get_lesson(session, project.id, lesson.id)
    task = read.blocks[2].task
    assert task.attempts == 2 and task.last_attempt.outcome == PASSED

    # Одна отмена убирает задания из урока, а попытки остаются в истории.
    _undo(session, project)
    session.expire_all()
    read = service.get_lesson(session, project.id, lesson.id)
    assert LessonBlockKind.ACTIVITY not in [block.kind for block in read.blocks]
    stored = session.get(StudyTask, choice.activity_id)
    assert stored.deleted_at is not None


def test_open_answer_waits_without_models_then_judge_checks(session, project):
    lesson = _lesson(session, project)
    job = _practice(session, project, lesson, [
        _draft("open_answer", prompt_md="Почему станции делят среду?",
               reference_md="Среда общая, передаёт одна станция.", points=["среда общая"]),
    ])
    op = job.checkpoint["result"]["ops"][0]
    applied = proposals.apply_proposal(session, project.id, lesson.id, job.id,
                                       LessonProposalApplyWrite(op_ids=[op["id"]],
                                                                expected_revision=lesson.revision))
    task = applied.lesson.blocks[-1].task

    offline = ModelGateway(session, FakeTransport(completions=[]))
    offline.preflight = _raise_disabled  # type: ignore[method-assign]
    offline.complete = _raise_disabled  # type: ignore[method-assign]
    pending = _attempt(session, project, lesson.id, task.activity_id, gateway=offline,
                       text="Потому что среда одна на всех.")
    assert pending.outcome is None and pending.pending_reason

    verdict = {"outcome": "passed", "credited": [{"point": "среда общая",
                                                  "quote": "среда одна на всех"}],
               "missed": [], "wrong": [], "summary": "Суть верна."}
    judged = asyncio.run(tasks.check_pending(
        session, ModelGateway(session, FakeTransport(completions=[_reply(verdict)])),
        project.id, lesson.id, task.activity_id, pending.id,
    ))
    assert judged.outcome == PASSED and judged.method == GradeMethod.AI_JUDGE
    assert judged.credited == ["среда общая"]


async def _raise_disabled(*args, **kwargs):
    from app.ai.settings import AiGatewayError

    raise AiGatewayError("Внешние модели выключены", code="ai_disabled")


def test_usage_cost_is_counted_for_practice(session, project):
    lesson = _lesson(session, project)
    job = _practice(session, project, lesson, [
        _draft("numeric", prompt_md="Сколько байт?", value=64, tolerance=0, relative=False,
               unit="байт"),
    ])
    assert Decimal(job.checkpoint["result"]["cost_usd"]) > 0
