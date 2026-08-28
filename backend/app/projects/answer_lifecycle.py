"""Единая политика жизненного цикла эталонного ответа.

Привязка фрагментов и наличие эталона — разные факты. Этот модуль отвечает
только за слот эталона и не знает, как раздел был найден в материале.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    utc_now,
)


class AnswerImportAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    RESTORED = "restored"
    UNCHANGED = "unchanged"
    PRESERVED = "preserved"


@dataclass(frozen=True, slots=True)
class ImportedAnswerCandidate:
    project_id: UUID
    node_id: UUID
    text: str
    match_method: ReferenceAnswerMatchMethod
    matched_title: str
    source_label: str
    source_material_id: UUID
    source_page_from: int
    source_page_to: int


@dataclass(frozen=True, slots=True)
class AnswerImportOutcome:
    node_id: UUID
    action: AnswerImportAction
    is_available: bool


def is_reference_answer_available(answer: ReferenceAnswer | None) -> bool:
    """Слот доступен только когда в нём есть активный эталон.

    Пустой текст допустим: это ответ, который читается по изображению источника.
    """

    return answer is not None and answer.is_active


def _same_import(answer: ReferenceAnswer, candidate: ImportedAnswerCandidate) -> bool:
    return (
        answer.origin_kind == ReferenceAnswerOrigin.IMPORT
        and answer.text == candidate.text
        and answer.match_method == candidate.match_method
        and answer.matched_title == candidate.matched_title
        and answer.source_label == candidate.source_label
        and answer.source_material_id == candidate.source_material_id
        and answer.source_page_from == candidate.source_page_from
        and answer.source_page_to == candidate.source_page_to
        and not answer.is_confirmed
    )


def _replace_with_import(
    answer: ReferenceAnswer,
    candidate: ImportedAnswerCandidate,
) -> None:
    """Меняем все поля происхождения вместе, не оставляя ручной provenance."""

    answer.text = candidate.text
    answer.origin_kind = ReferenceAnswerOrigin.IMPORT
    answer.match_method = candidate.match_method
    answer.matched_title = candidate.matched_title
    answer.is_confirmed = False
    answer.is_active = True
    answer.source_label = candidate.source_label
    answer.source_material_id = candidate.source_material_id
    answer.source_page_from = candidate.source_page_from
    answer.source_page_to = candidate.source_page_to
    answer.updated_at = utc_now()


def apply_imported_answer(
    session: Session,
    candidate: ImportedAnswerCandidate,
) -> AnswerImportOutcome:
    """Применить найденный в файле раздел к слоту эталона.

    Неактивная строка — tombstone, поэтому явный повторный импорт имеет право
    восстановить её. Активный ручной или подтверждённый ответ автоматика не
    перезаписывает.
    """

    answer = session.get(ReferenceAnswer, (candidate.project_id, candidate.node_id))
    if answer is None:
        now = utc_now()
        session.add(
            ReferenceAnswer(
                project_id=candidate.project_id,
                program_node_id=candidate.node_id,
                text=candidate.text,
                origin_kind=ReferenceAnswerOrigin.IMPORT,
                match_method=candidate.match_method,
                matched_title=candidate.matched_title,
                is_confirmed=False,
                is_active=True,
                revision=0,
                source_label=candidate.source_label,
                source_material_id=candidate.source_material_id,
                source_page_from=candidate.source_page_from,
                source_page_to=candidate.source_page_to,
                created_at=now,
                updated_at=now,
            )
        )
        return AnswerImportOutcome(candidate.node_id, AnswerImportAction.CREATED, True)

    if not is_reference_answer_available(answer):
        _replace_with_import(answer, candidate)
        answer.revision += 1
        return AnswerImportOutcome(candidate.node_id, AnswerImportAction.RESTORED, True)

    if answer.origin_kind == ReferenceAnswerOrigin.MANUAL or answer.is_confirmed:
        return AnswerImportOutcome(candidate.node_id, AnswerImportAction.PRESERVED, True)

    if answer.source_material_id != candidate.source_material_id:
        return AnswerImportOutcome(candidate.node_id, AnswerImportAction.PRESERVED, True)

    if _same_import(answer, candidate):
        return AnswerImportOutcome(candidate.node_id, AnswerImportAction.UNCHANGED, True)

    _replace_with_import(answer, candidate)
    answer.revision += 1
    return AnswerImportOutcome(candidate.node_id, AnswerImportAction.UPDATED, True)
