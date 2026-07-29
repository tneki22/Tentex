from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    """Пульс сервера. Фронтенд дёргает его на служебном экране «Состояние»."""
    return {"status": "ok", "service": "tentex-api"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tentex API",
        description="Подготовка к экзамену: программа, материалы, покрытие в обе стороны.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    app.include_router(api)
    return app


app = create_app()
