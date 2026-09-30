"""«Урок из найденного» — страницы, отмеченные в поиске, одной командой.

Нужен теме без диапазона оглавления, где «Быстрому уроку» не на что опереться:
пользователь отмечает найденные места, и они становятся кусками черновика в
порядке выбора. Каждая страница добавляется тем же `_add_page`, что и кнопка
«Страницу» в панели, поэтому привязки ручные — выбор сделал человек. Новый урок
отменяется как созданный (`lesson_create`), дополнение — как правка блоков.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lessons.editing import _add_page, _block_data, _Edit, _ordered_blocks, _topics_data
from app.lessons.schemas import ApiModel, LessonBlockWrite, LessonChangeResult
from app.lessons.service import (
    ACTION_LESSON_BLOCKS,
    ACTION_LESSON_CREATE,
    _change_result,
    _require_lesson,
    _require_lessons_project,
    _require_revision,
    _require_study_node,
)
from app.models import Lesson, LessonStatus, LessonTopic, ProjectActionLog, utc_now
from app.projects.errors import ProjectDomainError


class FoundPage(ApiModel):
    material_id: UUID
    page: int = Field(ge=1)


class LessonFromSearchWrite(ApiModel):
    program_node_id: UUID
    pages: list[FoundPage] = Field(min_length=1, max_length=30)
    # Задан — страницы дописываются в конец этого урока, иначе создаётся черновик.
    lesson_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)


def _unique(pages: list[FoundPage]) -> list[FoundPage]:
    seen: set[tuple[UUID, int]] = set()
    result: list[FoundPage] = []
    for item in pages:
        key = (item.material_id, item.page)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _append_pages(edit: _Edit, node_id: UUID, pages: list[FoundPage]) -> None:
    for item in pages:
        edit.command = LessonBlockWrite(
            expected_revision=edit.lesson.revision,
            operation="add_page",
            material_id=item.material_id,
            page_from=item.page,
            after_block_id=edit.blocks[-1].id if edit.blocks else None,
            program_node_id=node_id,
        )
        _add_page(edit)
        edit.session.flush()


def create_lesson_from_search(
    session: Session, project_id: UUID, command: LessonFromSearchWrite
) -> LessonChangeResult:
    """Черновик из найденных страниц или их дописывание в урок — одна запись отмены."""
    pages = _unique(command.pages)
    with project_write_transaction(session, project_id):
        project = _require_lessons_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, command.program_node_id)
        if command.lesson_id is None:
            now = utc_now()
            lesson = Lesson(
                id=uuid4(), project_id=project.id, title=node.title,
                status=LessonStatus.DRAFT, revision=1, created_at=now, updated_at=now,
            )
            session.add(lesson)
            session.add(LessonTopic(
                lesson_id=lesson.id, program_node_id=node.id, project_id=project.id,
                sort_order=0, topic_title_snapshot=node.title,
            ))
            session.flush()
            before = None
        else:
            lesson = _require_lesson(session, project_id, command.lesson_id)
            if command.expected_revision is None:
                raise ProjectDomainError(
                    "Нужна ревизия урока", status=422, code="lesson_revision_required",
                )
            _require_revision(lesson, command.expected_revision)
            before = [
                _block_data(session, block) for block in _ordered_blocks(session, lesson.id)
            ]
            topics = _topics_data(session, lesson.id)
        edit = _Edit(
            session, lesson, _ordered_blocks(session, lesson.id),
            LessonBlockWrite(expected_revision=lesson.revision, operation="add_page"),
        )
        _append_pages(edit, node.id, pages)
        for index, block in enumerate(edit.blocks):
            block.sort_order = index
        binding_ids = [str(item) for item in edit.binding_ids]
        if before is None:
            session.add(ProjectActionLog(
                project_id=project.id, action_type=ACTION_LESSON_CREATE,
                phase="active", payload_version=1, target_title=lesson.title,
                inverse_data={"lesson_id": str(lesson.id), "binding_ids": binding_ids},
            ))
        else:
            lesson.revision += 1
            lesson.updated_at = utc_now()
            session.add(ProjectActionLog(
                project_id=project.id, action_type=ACTION_LESSON_BLOCKS,
                phase="active", payload_version=1, target_title=lesson.title,
                inverse_data={"lesson_id": str(lesson.id), "blocks": before, "topics": topics,
                              "binding_ids": binding_ids},
            ))
        session.flush()
        return _change_result(session, lesson)
