"""7.2: «Только нужное» — доисследование блоков, которым нужен обзор."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.coverage.queries import overview
from app.coverage.research import process_coverage_job
from app.coverage.schemas import RunPlan, RunStart
from app.coverage.service import preflight, start_run
from app.materials.worker import claim_job
from app.models import (
    Binding,
    BindingStatus,
    CoverageBlockResult,
    CoverageTask,
    MaterialBlock,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError
from tests.conftest import make_topic_node
from tests.test_coverage import answer, launch, setup_source


def mixed_answer(task_input, first, second):
    """Блоки 0–5 про первую тему, 6–8 не решены, 9 про вторую."""
    result = answer(task_input, first.id)
    for index, item in enumerate(result):
        if 6 <= index <= 8:
            result[index] = {
                "target_id": item["target_id"],
                "outcome": "unresolved",
                "reason": "нужно уточнить",
                "dispositions": [
                    {**part, "outcome": "unresolved"} for part in item["dispositions"]
                ],
                "links": [],
            }
        elif index == 9:
            result[index]["links"] = [
                {**link, "topic_id": str(second.id)} for link in item["links"]
            ]
    return result


def researched(session):
    """Десять блоков: 6 разобраны, 3 не решены, 1 устарел после переименования темы."""
    project, first, material = setup_source(session, 10)
    second = make_topic_node(session, project, title="Кванторы")
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: mixed_answer(task, first, second))
    second.title = "Другое название"
    session.commit()
    blocks = list(
        session.scalars(
            select(MaterialBlock.id)
            .where(MaterialBlock.material_id == material.id)
            .order_by(MaterialBlock.sort_order)
        )
    )
    return project, first, second, material, blocks


def incremental(session, project, material, **fields):
    plan = RunPlan(
        material_ids=[material.id], mode="incremental",
        expected_program_revision=project.program_revision, **fields,
    )
    checked = preflight(session, project.id, plan)
    command = RunStart(
        **plan.model_dump(), request_key=str(uuid4()), preflight_fingerprint=checked["fingerprint"]
    )
    return checked, command


def run_rows(session, run_id):
    return list(
        session.scalars(select(CoverageBlockResult).where(CoverageBlockResult.run_id == run_id))
    )


def test_only_what_is_needed_reads_exactly_the_blocks_that_ask_for_it(session):
    project, first, _, material, blocks = researched(session)
    before = overview(session, project.id)["distribution"]
    assert (before["linked"], before["unresolved"], before["stale"]) == (6, 3, 1)
    kept = {
        row.fragment_id: row.id
        for row in session.scalars(select(Binding).where(Binding.program_node_id == first.id))
    }

    checked, command = incremental(session, project, material)
    # Оба числа диалога: «Только нужное · 4 блока» и «Всё заново · 10 блоков».
    assert (checked["blocks"], checked["blocks_needed"], checked["blocks_all"]) == (4, 4, 10)
    run_id = start_run(session, project.id, command)

    tasks = list(session.scalars(select(CoverageTask).where(CoverageTask.run_id == run_id)))
    assert sum(len(task.targets) for task in tasks) == 4
    assert {row.block_id for row in run_rows(session, run_id)} == set(blocks[6:])

    job = claim_job(session, "test-worker", "ai")
    process_coverage_job(session, job, lambda task: answer(task, first.id))

    after = overview(session, project.id)["distribution"]
    assert (after["linked"], after["unresolved"], after["stale"]) == (10, 0, 0)
    # Остальные шесть блоков сохранили свои связи: запуск их не читал.
    survivors = {
        row.fragment_id: row.id
        for row in session.scalars(
            select(Binding).where(
                Binding.program_node_id == first.id, Binding.status == BindingStatus.MACHINE
            )
        )
    }
    assert {key: survivors[key] for key in kept} == kept


def test_explicit_blocks_join_the_scope_and_foreign_ones_are_refused(session):
    project, first, second, material, blocks = researched(session)
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, first.id))
    assert overview(session, project.id)["distribution"]["linked"] == 10

    empty, command = incremental(session, project, material)
    assert (empty["blocks"], empty["blocks_needed"], empty["blocks_all"]) == (0, 0, 10)
    with pytest.raises(ProjectConflictError) as nothing:
        start_run(session, project.id, command)
    assert nothing.value.code == "coverage_scope_empty"

    checked, command = incremental(session, project, material, block_ids=[blocks[0], blocks[1]])
    assert (checked["blocks"], checked["blocks_needed"]) == (2, 2)
    run_id = start_run(session, project.id, command)
    assert {row.block_id for row in run_rows(session, run_id)} == {blocks[0], blocks[1]}

    other = MaterialBlock(
        id=uuid4(), material_id=uuid4(), revision=1, sort_order=0, page_from=1, page_to=1
    )
    with pytest.raises(ProjectDomainError) as foreign:
        incremental(session, project, material, block_ids=[other.id])
    assert foreign.value.code == "coverage_block_unknown"


def test_full_run_reads_everything_and_takes_no_explicit_blocks(session):
    project, _, _, material, blocks = researched(session)

    plan = RunPlan(
        material_ids=[material.id], expected_program_revision=project.program_revision
    )
    checked = preflight(session, project.id, plan)
    assert (checked["blocks"], checked["blocks_all"], checked["blocks_needed"]) == (10, 10, 4)

    with pytest.raises(ValidationError):
        RunPlan(material_ids=[material.id], expected_program_revision=0, block_ids=[blocks[0]])
