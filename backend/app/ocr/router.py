from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.ocr import settings
from app.ocr.schemas import (
    OcrCloudModelRead,
    OcrCloudSettingsWrite,
    OcrEngineWrite,
    OcrGlobalSettingsWrite,
    OcrSettingsRead,
)

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/settings/ocr", tags=["ocr-settings"])


@router.get("", response_model=OcrSettingsRead)
def get_ocr_settings(session: SessionDependency, refresh: bool = False) -> OcrSettingsRead:
    return settings.read_settings(session)


@router.put("", response_model=OcrSettingsRead)
def put_ocr_settings(
    command: OcrGlobalSettingsWrite, session: SessionDependency
) -> OcrSettingsRead:
    return settings.update_global_settings(session, command)


@router.put("/engines/{mode}", response_model=OcrSettingsRead)
def put_ocr_engine(
    mode: str, command: OcrEngineWrite, session: SessionDependency
) -> OcrSettingsRead:
    return settings.update_engine(session, mode, command)


@router.get("/cloud/models", response_model=list[OcrCloudModelRead])
def get_cloud_models(session: SessionDependency) -> list[OcrCloudModelRead]:
    """Кандидаты в распознаватели страниц: годные первыми, с причиной у остальных."""
    return settings.cloud_models(session)


@router.put("/cloud", response_model=OcrSettingsRead)
def put_cloud_settings(
    command: OcrCloudSettingsWrite, session: SessionDependency
) -> OcrSettingsRead:
    """Выбор модели уходит в настройки шлюза, стратегия — в строку движка.

    `ai_model_modality_unsupported` — выбрана модель, не принимающая картинки.
    """
    return settings.update_cloud(session, command)


# Загрузка отвечает сразу: сама она идёт в фоновом потоке, а прогресс приезжает
# следующим GET. Держать HTTP-запрос на двух гигабайтах нельзя.
@router.post("/models/{model_key}/install", response_model=OcrSettingsRead)
def install_model(model_key: str, session: SessionDependency) -> OcrSettingsRead:
    return settings.install_model(session, model_key)


@router.post("/models/{model_key}/cancel", response_model=OcrSettingsRead)
def cancel_model(model_key: str, session: SessionDependency) -> OcrSettingsRead:
    return settings.cancel_model(session, model_key)


@router.delete("/models/{model_key}", response_model=OcrSettingsRead)
def remove_model(model_key: str, session: SessionDependency) -> OcrSettingsRead:
    return settings.remove_model(session, model_key)
