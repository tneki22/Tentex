from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.projects.errors import ProjectDomainError

AiModality = Literal["text", "speech"]
CachePolicy = Literal["none", "exact", "content_hash"]


class TextRoleParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_output_tokens: int = Field(ge=64, le=32_000)
    temperature: float | None = Field(default=None, ge=0, le=2)


class ModelTestParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Рассуждающая модель тратит бюджет на размышление раньше, чем напишет первое
    # слово ответа. Тесный лимит здесь давал пустой ответ у любой такой модели.
    max_output_tokens: int = Field(ge=64, le=8_000)


class SpeechRoleParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(pattern=r"^[a-z]{2}$")


@dataclass(frozen=True)
class AiRoleSpec:
    key: str
    title: str
    description: str
    modality: AiModality
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    cache_policy: CachePolicy = "none"
    prompt_version: str = "1"
    default_parameters: dict[str, object] = field(default_factory=dict)
    allow_request_model_override: bool = False
    parameter_model: type[BaseModel] = TextRoleParameters
    visible: bool = True


ROLE_SPECS = {
    spec.key: spec
    for spec in (
        AiRoleSpec(
            "material_text_cleanup",
            "Уборка текста материала",
            "Исправляет оформление страницы и показывает результат перед сохранением.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "cleanup-v1",
            {"max_output_tokens": 6000},
        ),
        AiRoleSpec(
            "exam_program_grouping",
            "Разделы вопросов экзамена",
            "Объединяет вопросы по темам, чтобы в программе было проще ориентироваться.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "grouping-v1",
            {"max_output_tokens": 4000},
        ),
        AiRoleSpec(
            "exam_import_repair",
            "Исправление списка вопросов",
            "Восстанавливает список после сбоя разбора файла: сшивает разорванные пункты, "
            "снимает переносы и склейки слов, убирает заголовки, ошибочно попавшие в вопросы, "
            "и расставляет явные подпункты.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "import-repair-v2",
            {"max_output_tokens": 8000},
        ),
        AiRoleSpec(
            "exam_preparation_estimate",
            "Оценка времени подготовки",
            "Предлагает реалистичную дневную нагрузку по сроку и объёму экзамена.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "preparation-estimate-v1",
            {"max_output_tokens": 700},
        ),
        AiRoleSpec(
            "exam_chat_reply",
            "Ответ экзаменатора",
            "Отвечает в чате и помогает разобраться в теме.",
            "text",
            frozenset({"streaming"}),
            "none",
            "chat-reply-v2",
            {"max_output_tokens": 3000},
            True,
        ),
        AiRoleSpec(
            "exam_answer_judge",
            "Проверка ответа",
            "Сравнивает ваш ответ с эталоном и объясняет результат.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "answer-judge-v1",
            {"max_output_tokens": 4000},
            True,
        ),
        AiRoleSpec(
            "exam_chat_memory",
            "Память раздела",
            "Кратко сохраняет важное из прошлых сообщений, чтобы разговор не терял контекст.",
            "text",
            frozenset({"structured_output"}),
            "none",
            "chat-memory-v1",
            {"max_output_tokens": 1000},
        ),
        AiRoleSpec(
            "speech_transcription",
            "Распознавание речи",
            "Превращает голос в текст, который можно отредактировать.",
            "speech",
            frozenset({"audio_transcription"}),
            "content_hash",
            "speech-transcription-v1",
            {"language": "ru"},
            parameter_model=SpeechRoleParameters,
        ),
        AiRoleSpec(
            "settings_model_test",
            "Проверка модели",
            "Проверяет, отвечает ли явно выбранная модель.",
            "text",
            cache_policy="none",
            prompt_version="settings-model-test-v1",
            default_parameters={"max_output_tokens": 1500},
            allow_request_model_override=True,
            parameter_model=ModelTestParameters,
            visible=False,
        ),
    )
}


def get_role_spec(role: str) -> AiRoleSpec:
    try:
        return ROLE_SPECS[role]
    except KeyError as error:
        raise ProjectDomainError(
            "Неизвестная роль внешней модели",
            status=404,
            code="ai_role_not_found",
            context={"role": role},
        ) from error


def validate_role_parameters(role: str, values: dict[str, object]) -> dict[str, object]:
    spec = get_role_spec(role)
    merged = spec.default_parameters | values
    try:
        return spec.parameter_model.model_validate(merged).model_dump(exclude_none=True)
    except ValidationError as error:
        raise ProjectDomainError(
            "Параметры роли не прошли проверку",
            status=422,
            code="ai_role_parameters_invalid",
            context={"role": role, "errors": error.errors(include_input=False)},
        ) from error
