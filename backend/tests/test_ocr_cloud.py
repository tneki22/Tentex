"""Режим распознавания «Облако»: выбор модели, отбор кандидатов и разбор ответа."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.materials.parsers.cloud_vlm import CloudRecognizer, latex_issues
from app.models import AiModelCatalogEntry, AiProviderConnection, AiSettings, utc_now
from app.ocr import cloud_catalog
from app.ocr import settings as ocr_settings
from app.ocr.schemas import OcrCloudSettingsWrite
from app.projects.errors import ProjectDomainError

VISION_MODEL = "test/vision-model"


@pytest.fixture
def vision_model(session: Session, ai_config: str) -> str:
    """Модель, принимающая картинки, рядом с обычной текстовой из `ai_config`."""
    del ai_config
    provider_id = session.query(AiProviderConnection.id).scalar()
    now = utc_now()
    session.add(
        AiModelCatalogEntry(
            provider_id=provider_id,
            model_id=VISION_MODEL,
            display_name="Test vision model",
            context_length=200_000,
            max_completion_tokens=16_000,
            supported_parameters=["response_format"],
            input_modalities=["text", "image"],
            output_modalities=["text"],
            prompt_price_usd=Decimal("0.00000015"),
            completion_price_usd=Decimal("0.00000047"),
            pricing_snapshot_at=now,
            catalog_snapshot_at=now,
            is_manually_added=True,
            is_available=True,
        )
    )
    session.commit()
    return VISION_MODEL


def _provider_id(session: Session) -> UUID:
    """Идентификатор провайдера из фикстуры.

    Чтение открывает транзакцию, а сервис сразу после этого начинает свою.
    Разрываем явно — тот же приём, что и между вызовами в `test_ai_settings`.
    """
    provider_id = session.query(AiProviderConnection.id).scalar()
    session.rollback()
    return provider_id


# ── Выбор модели ─────────────────────────────────────────────────────────────


def test_cloud_is_unavailable_until_external_models_are_enabled(session: Session) -> None:
    snapshot = ocr_settings.read_settings(session)
    cloud = next(item for item in snapshot.engines if item.mode == "cloud")

    assert cloud.readiness == "unavailable"
    assert snapshot.cloud.external_models_enabled is False


def test_cloud_asks_for_a_model_when_none_is_chosen(session: Session, ai_config: str) -> None:
    del ai_config
    cloud = next(
        item for item in ocr_settings.read_settings(session).engines if item.mode == "cloud"
    )

    assert cloud.readiness == "needs_models"
    assert "принимает изображения" in cloud.status_detail


def test_choosing_a_model_makes_the_mode_ready(session: Session, vision_model: str) -> None:
    """Выбор уходит в настройки шлюза: там же ключи, лимиты и учёт стоимости."""
    snapshot = ocr_settings.update_cloud(
        session,
        OcrCloudSettingsWrite(
            provider_id=_provider_id(session), model_id=vision_model, strategy="page"
        ),
    )

    cloud = next(item for item in snapshot.engines if item.mode == "cloud")
    assert cloud.readiness == "ready"
    assert cloud.active_label == vision_model
    assert snapshot.cloud.model_id == vision_model
    assert snapshot.cloud.strategy == "page"
    assert session.get(AiSettings, 1).default_vision_model_id == vision_model


def test_chosen_strategy_reaches_the_parser(session: Session, vision_model: str) -> None:
    ocr_settings.update_cloud(
        session,
        OcrCloudSettingsWrite(
            provider_id=_provider_id(session), model_id=vision_model, strategy="page"
        ),
    )
    session.rollback()

    assert ocr_settings.runtime_params(session).cloud_strategy == "page"


def test_default_strategy_sends_out_only_what_cannot_be_read_locally(session: Session) -> None:
    assert ocr_settings.runtime_params(session).cloud_strategy == "auto"


def test_a_text_only_model_cannot_be_chosen(session: Session, ai_config: str) -> None:
    with pytest.raises(ProjectDomainError) as caught:
        ocr_settings.update_cloud(
            session,
            OcrCloudSettingsWrite(
                provider_id=_provider_id(session), model_id=ai_config, strategy="auto"
            ),
        )

    assert caught.value.code == "ai_model_modality_unsupported"


def test_clearing_the_model_returns_the_mode_to_needs_models(
    session: Session, vision_model: str
) -> None:
    ocr_settings.update_cloud(
        session,
        OcrCloudSettingsWrite(
            provider_id=_provider_id(session), model_id=vision_model, strategy="auto"
        ),
    )
    session.rollback()

    snapshot = ocr_settings.update_cloud(
        session, OcrCloudSettingsWrite(provider_id=None, model_id=None, strategy="auto")
    )

    cloud = next(item for item in snapshot.engines if item.mode == "cloud")
    assert cloud.readiness == "needs_models"
    assert snapshot.cloud.model_id is None


# ── Отбор кандидатов ─────────────────────────────────────────────────────────


def test_candidate_list_hides_text_models_and_keeps_the_rest_with_a_reason(
    session: Session, vision_model: str
) -> None:
    candidates = ocr_settings.cloud_models(session)

    assert [item.model_id for item in candidates] == [vision_model]
    assert candidates[0].suitable is True
    assert candidates[0].price_per_page_usd is not None


def test_a_vision_model_without_structured_output_is_listed_but_refused(
    session: Session, vision_model: str
) -> None:
    """Прятать непригодные нельзя: иначе отбор выглядит произволом."""
    del vision_model
    row = session.get(AiModelCatalogEntry, (_provider_id(session), VISION_MODEL))
    row.supported_parameters = ["temperature"]
    session.commit()

    candidate = ocr_settings.cloud_models(session)[0]

    assert candidate.suitable is False
    assert candidate.reason == "Не умеет отвечать по схеме"


@pytest.mark.parametrize(
    ("context_length", "reason"),
    [
        (8_000, "Слишком короткий контекст для страницы"),
        (200_000, ""),
    ],
)
def test_context_length_gates_the_candidate(context_length: int, reason: str) -> None:
    decision = cloud_catalog.verdict(
        model_id="any/model",
        input_modalities=["image"],
        supported_parameters=["response_format"],
        context_length=context_length,
        max_completion_tokens=16_000,
        prompt_price_usd=None,
        completion_price_usd=None,
    )

    assert decision.reason == reason


def test_price_per_page_counts_a_whole_page_not_a_token() -> None:
    """Сравнивать модели построчно в прайсе бесполезно — считаем страницу целиком."""
    price = cloud_catalog.price_per_page(Decimal("0.00000015"), Decimal("0.00000047"))

    assert price == pytest.approx(Decimal("0.00088"), abs=Decimal("0.00002"))


# ── Разбор ответа модели ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Обычный текст без формул", []),
        ("Формула $x^2 + y^2 = z^2$ внутри строки", []),
        ("Оборванная формула $x^2 + y", ["unbalanced_inline_math"]),
        ("$$\\frac{1}{2}$$", []),
        ("$$\\frac{1}{2}", ["unbalanced_display_math"]),
        ("\\begin{aligned} x = 1 \\end{aligned}", []),
        ("\\begin{aligned} x = 1", ["unbalanced_environment"]),
        ("Скобка \\frac{1}{2", ["unbalanced_braces"]),
    ],
)
def test_latex_issues_finds_what_katex_will_refuse_to_render(
    text: str, expected: list[str]
) -> None:
    assert latex_issues(text) == expected


def _answer(payload: dict[str, object]) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(payload, ensure_ascii=False),
        actual_model_id=VISION_MODEL,
        usage=ProviderUsage(input_tokens=1800, output_tokens=400),
    )


def _recognizer(session: Session, payload: dict[str, object]) -> CloudRecognizer:
    return CloudRecognizer(session, transport=FakeTransport(completions=[_answer(payload)]))


def test_recognised_page_keeps_the_order_and_marks_the_source(
    session: Session, vision_model: str
) -> None:
    ocr_settings.update_cloud(
        session,
        OcrCloudSettingsWrite(
            provider_id=_provider_id(session), model_id=vision_model, strategy="auto"
        ),
    )
    session.rollback()
    recognizer = _recognizer(
        session,
        {
            "elements": [
                {
                    "kind": "heading",
                    "text": "§ 7.4. Формула Ньютона — Лейбница",
                    "bbox": [0.08, 0.08, 0.68, 0.12],
                    "level": 1,
                    "confidence": 0.99,
                },
                {
                    "kind": "formula",
                    "text": "$$\\int_a^b f(x)\\,dx = F(b) - F(a). \\tag{7.1}$$",
                    "bbox": [0.2, 0.19, 0.8, 0.23],
                    "level": None,
                    "confidence": 0.93,
                },
            ],
            "page_confidence": 0.95,
        },
    )

    page = recognizer.recognize_page(b"png-bytes", 8, 595.0, 842.0)

    assert [item.kind for item in page.elements] == ["heading", "formula"]
    assert all(item.recognition_source == "vl" for item in page.elements)
    assert page.quality == "ocr"
    assert "\\tag{7.1}" in page.markdown


def test_a_page_without_coordinates_is_kept_but_flagged(
    session: Session, vision_model: str
) -> None:
    """Фрагменту без координат не на что указывать в просмотрщике — это брак."""
    ocr_settings.update_cloud(
        session,
        OcrCloudSettingsWrite(
            provider_id=_provider_id(session), model_id=vision_model, strategy="auto"
        ),
    )
    session.rollback()
    recognizer = _recognizer(
        session,
        {
            "elements": [
                {
                    "kind": "paragraph",
                    "text": "Пусть функция непрерывна на отрезке.",
                    "bbox": [0.5, 0.5, 0.1, 0.1],
                    "level": None,
                    "confidence": 0.9,
                }
            ],
            "page_confidence": 0.9,
        },
    )

    page = recognizer.recognize_page(b"png-bytes", 3, 595.0, 842.0)

    assert page.quality == "ocr_low"
    assert any(item.startswith("bbox_missing") for item in page.diagnostics)
    assert page.elements[0].bbox == (0.0, 0.0, 1.0, 1.0)


def test_a_broken_formula_lowers_confidence_of_the_whole_page(
    session: Session, vision_model: str
) -> None:
    ocr_settings.update_cloud(
        session,
        OcrCloudSettingsWrite(
            provider_id=_provider_id(session), model_id=vision_model, strategy="auto"
        ),
    )
    session.rollback()
    recognizer = _recognizer(
        session,
        {
            "elements": [
                {
                    "kind": "formula",
                    "text": "$$\\frac{1}{2",
                    "bbox": [0.2, 0.2, 0.8, 0.3],
                    "level": None,
                    "confidence": 0.95,
                }
            ],
            "page_confidence": 0.95,
        },
    )

    page = recognizer.recognize_page(b"png-bytes", 4, 595.0, 842.0)

    assert page.quality == "ocr_low"
    assert "unbalanced_display_math" in page.diagnostics
    assert page.elements[0].confidence == pytest.approx(0.4)
