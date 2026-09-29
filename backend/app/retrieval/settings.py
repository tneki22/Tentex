from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    EmbeddingBackendKind,
    EmbeddingProfile,
    Material,
    MaterialState,
    RetrievalChunk,
    RetrievalIndex,
    RetrievalSettings,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from app.retrieval.embeddings import backend_for_profile
from app.retrieval.local_models import model_path
from app.retrieval.recipes import DEFAULT_TEMPLATE, model_recipe
from app.retrieval.schemas import (
    EmbeddingProfileRead,
    EmbeddingProfileWrite,
    RetrievalSettingsRead,
    RetrievalSettingsWrite,
)

DEFAULT_RERANKER_MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"


def create_profile(session: Session, command: EmbeddingProfileWrite) -> EmbeddingProfileRead:
    with session.begin():
        if session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.label == command.label)):
            raise ProjectConflictError(
                "Профиль с таким названием уже существует",
                code="retrieval_profile_label_exists",
            )
        values = command.model_dump()
        recipe = model_recipe(command.model_id)
        untouched = DEFAULT_TEMPLATE == command.query_template == command.document_template
        if recipe is not None and untouched:
            values["query_template"] = recipe.query_template
            values["document_template"] = recipe.document_template
            if command.pooling == "mean":
                values["pooling"] = recipe.pooling
        profile = EmbeddingProfile(id=uuid4(), **values)
        profile.installed = profile.backend_kind == EmbeddingBackendKind.OPENAI_COMPATIBLE
        session.add(profile)
    return EmbeddingProfileRead.model_validate(profile)


async def test_profile(session: Session, profile_id: UUID) -> EmbeddingProfileRead:
    profile = session.get(EmbeddingProfile, profile_id)
    if profile is None:
        raise ProjectNotFoundError("Embedding-профиль не найден")
    try:
        vectors = await backend_for_profile(session, profile).embed_documents(
            ["Проверка embedding-профиля Tentex"]
        )
        dimension = len(vectors[0])
        if profile.dimension is not None and profile.dimension != dimension:
            raise ProjectConflictError(
                "Размерность модели изменилась — создайте новый профиль и индекс",
                code="retrieval_dimension_mismatch",
            )
        profile.dimension = dimension
        profile.installed = True
        profile.test_error = None
        # Первый проверенный профиль сразу годится для сборки индекса: иначе кнопка
        # «Собрать кандидат» остаётся серой, и причину нигде не видно.
        row = session.get(RetrievalSettings, 1)
        if row is None:
            row = RetrievalSettings(id=1)
            session.add(row)
        if row.default_profile_id is None:
            row.default_profile_id = profile.id
    except Exception as error:
        profile.test_error = str(error)
        profile.tested_at = utc_now()
        session.commit()
        raise
    profile.tested_at = utc_now()
    session.commit()
    return EmbeddingProfileRead.model_validate(profile)


def read_settings(session: Session) -> RetrievalSettingsRead:
    row = session.get(RetrievalSettings, 1)
    profiles = list(session.scalars(select(EmbeddingProfile).order_by(EmbeddingProfile.created_at)))
    active = (
        session.get(RetrievalIndex, row.active_index_id) if row and row.active_index_id else None
    )
    total = (
        session.scalar(
            select(func.count()).select_from(Material).where(Material.status == MaterialState.READY)
        )
        or 0
    )
    ready_materials = 0
    reasons: list[str] = []
    if active is None:
        reasons.append("Semantic-индекс ещё не активирован")
    else:
        # На Windows bind-mount проверка ревизии для каждого chunk делает тысячи
        # чтений SQLite. Материалов существенно меньше; индекс (index_id, material_id)
        # позволяет остановиться на первом подходящем chunk каждого материала.
        current_chunk = (
            select(RetrievalChunk.id)
            .where(
                RetrievalChunk.index_id == active.id,
                RetrievalChunk.material_id == Material.id,
                RetrievalChunk.revision == Material.active_parse_revision,
            )
            .exists()
        )
        ready_materials = session.scalar(
            select(func.count()).select_from(Material).where(current_chunk)
        ) or 0
        if ready_materials < total:
            reasons.append("Часть источников — только поиск по словам")
    return RetrievalSettingsRead(
        default_profile_id=row.default_profile_id if row else None,
        preset=row.preset if row else "balanced",
        expert_parameters=row.expert_parameters if row else {},
        active_index=active,
        profiles=[EmbeddingProfileRead.model_validate(profile) for profile in profiles],
        ready_materials=ready_materials,
        total_ready_materials=total,
        degraded=bool(reasons),
        degradation_reasons=reasons,
    )


def update_settings(session: Session, command: RetrievalSettingsWrite) -> RetrievalSettingsRead:
    with session.begin():
        row = session.get(RetrievalSettings, 1)
        if row is None:
            row = RetrievalSettings(id=1)
            session.add(row)
        if (
            command.default_profile_id
            and session.get(EmbeddingProfile, command.default_profile_id) is None
        ):
            raise ProjectNotFoundError("Embedding-профиль не найден")
        if command.preset == "accurate":
            # Пресет «Точно» переставляет места reranker'ом: без установленной модели он
            # молча превратился бы в «Сбалансированно», а в настройках остался бы «Точно».
            reranker_id = str(
                command.expert_parameters.get("reranker_model_id", DEFAULT_RERANKER_MODEL_ID)
            )
            if not model_path(reranker_id).is_dir():
                raise ProjectConflictError(
                    "Профиль «Точно» требует установленную модель reranker",
                    code="retrieval_reranker_missing",
                )
        row.default_profile_id = command.default_profile_id
        row.preset = command.preset
        row.expert_parameters = command.expert_parameters
        row.updated_at = utc_now()
    return read_settings(session)
