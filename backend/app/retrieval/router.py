from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.background.schemas import BackgroundJobStartRead
from app.db import get_session
from app.models import (
    RetrievalBenchmarkCase,
    RetrievalBenchmarkRun,
    RetrievalExhaustiveRun,
    RetrievalIndex,
)
from app.retrieval import benchmarks, exhaustive, indexing, local_models
from app.retrieval import settings as retrieval_settings
from app.retrieval.schemas import (
    BenchmarkCaseWrite,
    BenchmarkRunRead,
    EmbeddingProfileRead,
    EmbeddingProfileWrite,
    ExhaustiveRunRead,
    ExhaustiveRunWrite,
    LocalModelRead,
    RetrievalIndexBuildRead,
    RetrievalIndexBuildWrite,
    RetrievalIndexRead,
    RetrievalSearchRead,
    RetrievalSearchWrite,
    RetrievalSettingsRead,
    RetrievalSettingsWrite,
)
from app.retrieval.search import HybridRetriever

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api", tags=["retrieval"])


class LocalModelInstallWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=3, max_length=300)
    revision: str | None = Field(default=None, max_length=100)


@router.get("/settings/retrieval", response_model=RetrievalSettingsRead)
def get_retrieval_settings(session: SessionDependency) -> RetrievalSettingsRead:
    return retrieval_settings.read_settings(session)


@router.put("/settings/retrieval", response_model=RetrievalSettingsRead)
def put_retrieval_settings(
    command: RetrievalSettingsWrite, session: SessionDependency
) -> RetrievalSettingsRead:
    return retrieval_settings.update_settings(session, command)


@router.post(
    "/settings/retrieval/profiles",
    response_model=EmbeddingProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def post_embedding_profile(
    command: EmbeddingProfileWrite, session: SessionDependency
) -> EmbeddingProfileRead:
    return retrieval_settings.create_profile(session, command)


@router.post("/settings/retrieval/profiles/{profile_id}/test", response_model=EmbeddingProfileRead)
async def test_embedding_profile(
    profile_id: UUID, session: SessionDependency
) -> EmbeddingProfileRead:
    return await retrieval_settings.test_profile(session, profile_id)


@router.get("/settings/retrieval/local-models", response_model=list[LocalModelRead])
def get_local_models(session: SessionDependency) -> list[LocalModelRead]:
    return local_models.list_models(session)


@router.post(
    "/settings/retrieval/local-models/install",
    response_model=BackgroundJobStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def install_local_model(
    command: LocalModelInstallWrite, session: SessionDependency
) -> BackgroundJobStartRead:
    return BackgroundJobStartRead(
        job_id=local_models.start_install(session, command.model_id, command.revision)
    )


@router.delete("/settings/retrieval/local-models", status_code=status.HTTP_204_NO_CONTENT)
def delete_local_model(
    model_id: Annotated[str, Query(min_length=3, max_length=300)],
    session: SessionDependency,
) -> None:
    local_models.remove_model(session, model_id)


@router.get("/retrieval/indexes", response_model=list[RetrievalIndexRead])
def get_indexes(session: SessionDependency) -> list[RetrievalIndex]:
    return list(session.scalars(select(RetrievalIndex).order_by(RetrievalIndex.created_at.desc())))


@router.post(
    "/retrieval/indexes",
    response_model=RetrievalIndexBuildRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_index(
    command: RetrievalIndexBuildWrite, session: SessionDependency
) -> RetrievalIndexBuildRead:
    return indexing.start_index_build(session, command)


@router.post("/retrieval/indexes/{index_id}/activate", response_model=RetrievalIndexRead)
def activate_index(index_id: UUID, session: SessionDependency) -> RetrievalIndex:
    return indexing.activate_index(session, index_id)


@router.delete("/retrieval/indexes/{index_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_index(index_id: UUID, session: SessionDependency) -> None:
    indexing.delete_inactive_index(session, index_id)


@router.post(
    "/retrieval/indexes/materials/{material_id}",
    response_model=BackgroundJobStartRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def index_material(material_id: UUID, session: SessionDependency) -> BackgroundJobStartRead:
    """Поставить один готовый материал в очередь инкрементальной индексации."""
    return BackgroundJobStartRead(job_id=indexing.queue_material_reindex(session, material_id))


@router.post("/retrieval/search", response_model=RetrievalSearchRead)
async def search(command: RetrievalSearchWrite, session: SessionDependency) -> RetrievalSearchRead:
    return await HybridRetriever().search(session, command)


@router.post("/library/search", response_model=RetrievalSearchRead)
async def search_library(
    command: RetrievalSearchWrite, session: SessionDependency
) -> RetrievalSearchRead:
    return await HybridRetriever().search(session, command)


@router.get("/retrieval/benchmarks/cases", response_model=list[BenchmarkCaseWrite])
def get_benchmark_cases(session: SessionDependency) -> list[BenchmarkCaseWrite]:
    return [
        BenchmarkCaseWrite(
            query=row.query,
            relevant_material_ids=[UUID(item) for item in row.relevant_material_ids],
            relevant_locator_ids=row.relevant_locator_ids,
            tags=row.tags,
        )
        for row in session.scalars(select(RetrievalBenchmarkCase))
    ]


@router.post(
    "/retrieval/benchmarks/cases",
    response_model=BenchmarkCaseWrite,
    status_code=status.HTTP_201_CREATED,
)
def post_benchmark_case(
    command: BenchmarkCaseWrite, session: SessionDependency
) -> BenchmarkCaseWrite:
    benchmarks.add_case(session, command)
    return command


@router.get("/retrieval/benchmarks", response_model=list[BenchmarkRunRead])
def get_benchmark_runs(session: SessionDependency) -> list[RetrievalBenchmarkRun]:
    return list(
        session.scalars(
            select(RetrievalBenchmarkRun).order_by(RetrievalBenchmarkRun.created_at.desc())
        )
    )


@router.post("/retrieval/benchmarks/{index_id}", response_model=BenchmarkRunRead)
async def run_benchmark(index_id: UUID, session: SessionDependency) -> BenchmarkRunRead:
    return await benchmarks.run_benchmark(session, index_id)


@router.post(
    "/projects/{project_id}/chat/sessions/{session_id}/exhaustive",
    response_model=ExhaustiveRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_exhaustive_run(
    project_id: UUID,
    session_id: UUID,
    command: ExhaustiveRunWrite,
    session: SessionDependency,
) -> ExhaustiveRunRead:
    return exhaustive.start_run(session, project_id, session_id, command)


@router.get("/retrieval/exhaustive/{run_id}", response_model=ExhaustiveRunRead)
def get_exhaustive_run(run_id: UUID, session: SessionDependency) -> RetrievalExhaustiveRun:
    return exhaustive.get_run(session, run_id)
