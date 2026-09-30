from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.ai.gateway import MAX_AUDIO_BYTES, ModelGateway
from app.ai.schemas import AiTranscriptionRead
from app.ai.settings import AiGatewayError
from app.db import get_session

router = APIRouter(prefix="/api/ai", tags=["ai-dictation"])

# Что пишет MediaRecorder: Chrome и Firefox — webm/ogg, Safari — mp4. Провайдеры
# принимают формат по расширению, поэтому тип содержимого сводится к нему.
_AUDIO_FORMATS = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
    "audio/aac": "aac",
}


def _audio_format(content_type: str | None) -> str:
    media_type = (content_type or "").split(";")[0].strip().lower()
    try:
        return _AUDIO_FORMATS[media_type]
    except KeyError:
        raise AiGatewayError(
            "Этот формат записи не поддерживается",
            code="ai_audio_format_unsupported",
            status=415,
            context={"content_type": media_type},
        ) from None


@router.post("/transcriptions", response_model=AiTranscriptionRead)
async def transcribe_audio(
    file: UploadFile, session: Annotated[Session, Depends(get_session)]
) -> AiTranscriptionRead:
    audio_format = _audio_format(file.content_type)
    # Читаем на байт больше потолка: шлюз отличит «ровно в лимит» от «больше».
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    result = await ModelGateway(session).transcribe(audio, audio_format)
    return AiTranscriptionRead(
        text=result.text, run_id=result.run_id, duration_ms=result.duration_ms
    )
