from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import SessionLocal, upgrade_database
from app.projects.demo import seed_demo_project
from app.projects.errors import ProjectDomainError
from app.projects.router import router as projects_router

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    """Пульс сервера. Фронтенд дёргает его на служебном экране «Состояние»."""
    return {"status": "ok", "service": "tentex-api"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    database_existed = settings.database_path.exists()
    upgrade_database()
    if settings.seed_demo_project:
        with SessionLocal() as session:
            # Пример создаётся только при первом запуске базы. На следующих
            # версиях seed может дозаполнить новые fixture-данные существующего
            # примера, но не воскресит проект, который пользователь удалил.
            seed_demo_project(session, create_if_missing=not database_existed)
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

    @app.exception_handler(ProjectDomainError)
    async def domain_error(_: Request, error: ProjectDomainError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={
                "detail": error.detail,
                "code": error.code,
                "context": error.context,
            },
        )

    app.include_router(api)
    app.include_router(projects_router)
    return app


app = create_app()
