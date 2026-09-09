"""HTTP-слой карточек: только контракт, параметры и вызовы сервиса."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.cards import service
from app.cards.schemas import (
    CardBulkWrite,
    CardCreate,
    CardListRead,
    CardOverviewRead,
    CardRead,
    CardSessionCreate,
    CardSessionRead,
    CardUpdate,
    FragmentPrefillRead,
    RevisionWrite,
    SessionDeferWrite,
    SessionFinishWrite,
    SessionProgressWrite,
    SessionRetryWrite,
    SessionReviewWrite,
)
from app.db import get_session
from app.projects.errors import ProjectDomainError

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/projects/{project_id}", tags=["cards"])


@router.get("/cards/overview", response_model=CardOverviewRead)
def get_overview(
    project_id: UUID,
    session: SessionDependency,
    period: int = 7,
) -> CardOverviewRead:
    """Сводка календарного покрытия и карточной аналитики."""
    if period not in {7, 30}:
        raise ProjectDomainError(
            "Период аналитики должен быть 7 или 30 дней",
            status=422,
            code="card_period_invalid",
        )
    return service.overview(session, project_id, period)


@router.get("/cards", response_model=CardListRead)
def get_cards(
    project_id: UUID,
    session: SessionDependency,
    query: str | None = None,
    unit_id: UUID | None = None,
    state: Literal["active", "suspended"] | None = None,
    source: Literal["none", "fragment", "reference"] | None = None,
    rating: Literal["unrated", "hard", "recalled", "lost"] | None = None,
    include_deleted: bool = False,
) -> CardListRead:
    """Поиск и фильтры Банка выполняются на сервере."""
    return service.list_cards(
        session,
        project_id,
        query=query,
        unit_id=unit_id,
        state=state,
        source=source,
        rating=rating,
        include_deleted=include_deleted,
    )


@router.post("/cards", response_model=CardRead, status_code=201)
def post_card(project_id: UUID, command: CardCreate, session: SessionDependency) -> CardRead:
    """Ручное создание карточки."""
    return service.create_card(session, project_id, command)


@router.patch("/cards/{card_id}", response_model=CardRead)
def patch_card(
    project_id: UUID,
    card_id: UUID,
    command: CardUpdate,
    session: SessionDependency,
) -> CardRead:
    """Редактирование с проверкой ревизии."""
    return service.update_card(session, project_id, card_id, command)


@router.delete("/cards/{card_id}", response_model=CardRead)
def delete_card(
    project_id: UUID,
    card_id: UUID,
    session: SessionDependency,
    expected_revision: Annotated[int, Query(ge=1)],
) -> CardRead:
    """Мягкое удаление одной карточки."""
    result = service.bulk_cards(
        session,
        project_id,
        CardBulkWrite(
            action="delete",
            items=[{"id": card_id, "expected_revision": expected_revision}],
        ),
    )
    return next(item for item in result.items if item.id == card_id)


@router.post("/cards/{card_id}/restore", response_model=CardRead)
def restore_card(
    project_id: UUID,
    card_id: UUID,
    command: RevisionWrite,
    session: SessionDependency,
) -> CardRead:
    """Восстановление мягко удалённой карточки."""
    result = service.bulk_cards(
        session,
        project_id,
        CardBulkWrite(
            action="restore",
            items=[{"id": card_id, "expected_revision": command.expected_revision}],
        ),
    )
    return next(item for item in result.items if item.id == card_id)


@router.post("/cards/bulk", response_model=CardListRead)
def post_cards_bulk(
    project_id: UUID, command: CardBulkWrite, session: SessionDependency
) -> CardListRead:
    """Массовое состояние, удаление или восстановление."""
    return service.bulk_cards(session, project_id, command)


@router.get("/cards/fragments/{fragment_id}/prefill", response_model=FragmentPrefillRead)
def get_fragment_prefill(
    project_id: UUID, fragment_id: UUID, session: SessionDependency
) -> FragmentPrefillRead:
    """Проверенный источник для перехода «В карточку»."""
    return service.fragment_prefill(session, project_id, fragment_id)


@router.post("/card-sessions", response_model=CardSessionRead, status_code=201)
def post_session(
    project_id: UUID, command: CardSessionCreate, session: SessionDependency
) -> CardSessionRead:
    """Создать сохраняемый снимок очереди."""
    return service.create_session(session, project_id, command)


@router.get("/card-sessions/active", response_model=CardSessionRead)
def get_active_session(project_id: UUID, session: SessionDependency) -> CardSessionRead:
    """Продолжить активный сеанс."""
    return service.get_session(session, project_id)


@router.get("/card-sessions/{session_id}", response_model=CardSessionRead)
def get_session(project_id: UUID, session_id: UUID, session: SessionDependency) -> CardSessionRead:
    """Прочитать конкретный сеанс, включая итоговый."""
    return service.get_session(session, project_id, session_id)


@router.patch("/card-sessions/{session_id}", response_model=CardSessionRead)
def patch_session(
    project_id: UUID,
    session_id: UUID,
    command: SessionProgressWrite,
    session: SessionDependency,
) -> CardSessionRead:
    """Сохранить позицию и активное время."""
    return service.save_progress(session, project_id, session_id, command)


@router.post("/card-sessions/{session_id}/open", response_model=CardSessionRead)
def post_open(
    project_id: UUID,
    session_id: UUID,
    command: RevisionWrite,
    session: SessionDependency,
) -> CardSessionRead:
    """Открыть календарную единицу первой карточкой."""
    return service.open_current_unit(session, project_id, session_id, command.expected_revision)


@router.post(
    "/card-sessions/{session_id}/cards/{card_id}/review",
    response_model=CardSessionRead,
)
def post_review(
    project_id: UUID,
    session_id: UUID,
    card_id: UUID,
    command: SessionReviewWrite,
    session: SessionDependency,
) -> CardSessionRead:
    """Сохранить одну из четырёх самооценок идемпотентно."""
    return service.review_card(session, project_id, session_id, card_id, command)


@router.post(
    "/card-sessions/{session_id}/cards/{card_id}/defer",
    response_model=CardSessionRead,
)
def post_defer(
    project_id: UUID,
    session_id: UUID,
    card_id: UUID,
    command: SessionDeferWrite,
    session: SessionDependency,
) -> CardSessionRead:
    """Отложить карточку без включения в среднюю уверенность."""
    return service.defer_card(session, project_id, session_id, card_id, command)


@router.post("/card-sessions/{session_id}/finish", response_model=CardSessionRead)
def post_finish(
    project_id: UUID,
    session_id: UUID,
    command: SessionFinishWrite,
    session: SessionDependency,
) -> CardSessionRead:
    """Завершить либо явно отменить сеанс."""
    return service.finish_session(session, project_id, session_id, command)


@router.post("/card-sessions/{session_id}/retry", response_model=CardSessionRead)
def post_retry(
    project_id: UUID,
    session_id: UUID,
    command: SessionRetryWrite,
    session: SessionDependency,
) -> CardSessionRead:
    """Повторить только сложные и отложенные карточки."""
    return service.retry_session(session, project_id, session_id, command)
