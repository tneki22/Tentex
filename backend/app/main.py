from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import upgrade_database
from app.projects.router import router as projects_router
from app.projects.service import (
    ProjectConflictError,
    ProjectInvariantError,
    ProjectNotFoundError,
)

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    """Пульс сервера. Фронтенд дёргает его на служебном экране «Состояние»."""
    return {"status": "ok", "service": "tentex-api"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tentex API",
        description="Подготовка к экзамену: программа, материалы, покрытие в обе стороны.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ProjectNotFoundError)
    async def not_found(_: Request, error: ProjectNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(ProjectConflictError)
    async def conflict(_: Request, error: ProjectConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ProjectInvariantError)
    async def invariant(_: Request, error: ProjectInvariantError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    app.include_router(api)
    app.include_router(projects_router)
    return app


app = create_app()
