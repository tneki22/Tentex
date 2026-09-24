from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.projects.errors import ProjectDomainError

# Единственное определение модальностей шлюза: по нему `resolve_model` ищет
# модель по умолчанию (`AiSettings.default_<модальность>_model_id`), поэтому
# новое значение здесь требует и столбца в настройках.
AiModality = Literal["text", "speech", "vision"]
CachePolicy = Literal["none", "exact", "content_hash"]
# «off» — явное «думать не надо»: у части моделей рассуждение включено по
# умолчанию, и отличить его от «параметр не задан» можно только отдельным
# значением. Разворачивает его транспорт, по-своему для каждого профиля.
ReasoningEffort = Literal["off", "low", "medium", "high"]


class TextRoleParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_output_tokens: int = Field(ge=64, le=32_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: ReasoningEffort | None = None


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
    requires_explicit_model: bool = False


ROLE_SPECS = {
    spec.key: spec
    for spec in (
        AiRoleSpec(
            "coverage_overview",
            "Обзор материала",
            "Полный учёт блоков прохода 2.",
            "text",
            frozenset({"structured_output"}),
            "none",
            "verified-07",
            {"max_output_tokens": 8000},
            allow_request_model_override=True,
            requires_explicit_model=True,
        ),
        AiRoleSpec(
            "coverage_research",
            "Исследование материала",
            "Уточнение решений прохода 2.",
            "text",
            frozenset({"structured_output"}),
            "none",
            "verified-07",
            {"max_output_tokens": 8000},
            allow_request_model_override=True,
            requires_explicit_model=True,
        ),
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
            "grouping-v2",
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
            "import-repair-v3",
            {"max_output_tokens": 8000},
        ),
        AiRoleSpec(
            "exam_answer_sections",
            "Разметка файла ответов",
            "Разносит разделы файла эталонных ответов по вопросам программы, когда "
            "заголовки или нумерация разошлись со структурой документа.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "answer-sections-v1",
            {"max_output_tokens": 6000, "temperature": 0},
        ),
        AiRoleSpec(
            "exam_preparation_estimate",
            "Оценка времени подготовки",
            "Предлагает реалистичную дневную нагрузку по сроку и объёму экзамена.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "preparation-estimate-v2",
            {"max_output_tokens": 700},
        ),
        AiRoleSpec(
            "exam_preparation_phases",
            "Блоки подготовки",
            "Предлагает учебные блоки по программе и доступному времени.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "preparation-phases-v1",
            {"max_output_tokens": 4000},
        ),
        AiRoleSpec(
            "exam_preparation_distribution",
            "Распределение подготовки",
            "Распределяет целые билеты и вопросы по дням с проверкой ограничений.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "preparation-distribution-v1",
            {"max_output_tokens": 8000},
        ),
        AiRoleSpec(
            "exam_preparation_coach",
            "Рекомендация дня",
            "Связывает факты занятий с последствиями и следующим действием.",
            "text",
            frozenset({"structured_output"}),
            "exact",
            "preparation-coach-v1",
            {"max_output_tokens": 1000},
        ),
        AiRoleSpec(
            "exam_chat_reply",
            "Ответ экзаменатора",
            "Отвечает в чате и помогает разобраться в теме.",
            "text",
            frozenset({"streaming"}),
            "none",
            "chat-reply-v3",
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
            "retrieval_exhaustive",
            "Обзор всех источников",
            "Последовательно читает зафиксированный корпус и собирает проверяемый отчёт.",
            "text",
            frozenset({"structured_output"}),
            "none",
            "exhaustive-v1",
            {"max_output_tokens": 5000, "temperature": 0},
        ),
        AiRoleSpec(
            "material_page_recognition",
            "Распознавание страницы",
            "Читает страницу или вырез из неё картинкой и возвращает текст с формулами "
            "в LaTeX. Работает в режиме распознавания «Облако».",
            "vision",
            frozenset({"image_input", "structured_output"}),
            # Один и тот же вырез страницы не должен стоить дважды: повторный
            # разбор материала и переразбор отдельных страниц попадают в кэш.
            "content_hash",
            "page-recognition-v1",
            {"max_output_tokens": 8000, "temperature": 0},
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
            "material_audio_transcription",
            "Расшифровка аудиоматериала",
            "Превращает запись лекции или голосовое сообщение в текст с временными метками. "
            "Работает в режиме расшифровки «Облако»; модель берётся из «Для речи».",
            "speech",
            frozenset({"audio_transcription"}),
            "none",
            "audio-material-v1",
            {"language": "ru"},
            parameter_model=SpeechRoleParameters,
        ),
        AiRoleSpec(
            "study_outline_extract",
            "Оглавление учебника",
            "Восстанавливает структуру учебника, когда закладок и печатного оглавления нет.",
            "text",
            frozenset({"structured_output"}),
            "content_hash",
            "outline-v1",
            {"max_output_tokens": 6000, "temperature": 0},
        ),
        AiRoleSpec(
            "study_program_assistant",
            "Помощник по программе учебника",
            "Строит и правит дерево программы учебника в чате: резюме, плюсы, "
            "минусы и операции над узлами одним структурированным ответом.",
            "text",
            frozenset({"structured_output"}),
            "none",
            "study-program-v1",
            {"max_output_tokens": 8000},
            # Модель выбирается прямо в композере чата наравне с экзаменационным:
            # прежний запрет override снят, когда выбор переехал из Параметров в чат.
            True,
        ),
        AiRoleSpec(
            "source_web_search",
            "Поиск материалов в интернете",
            "Чат в Материалах: составляет запросы к локальному поисковику SearXNG "
            "по программе и цели проекта и отбирает из выдачи учебные источники.",
            "text",
            frozenset({"structured_output"}),
            "none",
            "source-search-chat-v1",
            {"max_output_tokens": 6000},
            # Модель выбирается в композере чата, как у остальных чатов.
            True,
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
        # Отдельная роль, а не `speech_transcription`: та может быть выключена в
        # Параметрах, а проверка явно выбранной модели от этого зависеть не должна.
        AiRoleSpec(
            "settings_speech_model_test",
            "Проверка модели распознавания речи",
            "Проверяет, принимает ли явно выбранная модель аудио.",
            "speech",
            frozenset({"audio_transcription"}),
            cache_policy="none",
            prompt_version="settings-speech-model-test-v1",
            default_parameters={"language": "ru"},
            allow_request_model_override=True,
            parameter_model=SpeechRoleParameters,
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
