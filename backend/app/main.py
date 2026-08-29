import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.router import router as ai_router
from app.bindings.router import router as bindings_router
from app.config import settings
from app.conspects.router import router as conspects_router
from app.db import SessionLocal, upgrade_database
from app.exam.router import router as exam_router
from app.logging_config import configure_logging
from app.materials.router import router as materials_router
from app.ocr.router import router as ocr_router
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
    configure_logging()
    log = logging.getLogger("tentex.http")

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

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.exception(
                "unhandled error %s %s rid=%s %.1fms",
                request.method,
                request.url.path,
                request_id,
                elapsed_ms,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Внутренняя ошибка сервера",
                    "code": "internal_error",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        log.info(
            "%s %s -> %s rid=%s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
            elapsed_ms,
        )
        return response

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
    app.include_router(materials_router)
    app.include_router(bindings_router)
    app.include_router(conspects_router)
    app.include_router(ai_router)
    app.include_router(ocr_router)
    app.include_router(exam_router)
    return app


app = create_app()
