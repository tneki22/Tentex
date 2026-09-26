"""Конвейер изображений: диагноз слоя, отбор кандидатов, описания и их запуск.

Внешняя модель подменена: заглушкой на уровне порта распознавания или
`FakeTransport` шлюза. Проверяется решение Tentex — что уходит наружу, сколько
раз и что становится с ответом, — а не качество модели.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.job_budget import JobBudget, budget_state
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.materials import image_descriptions, library
from app.materials.image_candidates import XREF_REPEATED, auto_send, classify
from app.materials.image_meta import with_description
from app.materials.parsers import native, text_layer
from app.materials.parsers.base import (
    IMAGE_PLACEHOLDER,
    MODEL_DESCRIPTION_MARK,
    DescribedImage,
    ImageDescription,
    ImageMeta,
    ImageProvenance,
    ImageRequest,
    ParsedElement,
    ParsedPage,
    RecognizedRegion,
    RegionRequest,
)
from app.materials.parsers.cloud_vlm import (
    CloudImageDescription,
    CloudRecognizer,
    validate_description,
)
from app.materials.schemas import ImageDescriptionStart
from app.materials.storage import store_material_asset
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    AiSettings,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    MaterialFragment,
    MaterialPage,
    MaterialRevision,
    MaterialRevisionOrigin,
    PageQuality,
    ParserMode,
    utc_now,
)
from app.ocr.engines import OcrRuntimeParams
from app.projects.errors import ProjectDomainError
from tests.conftest import make_material

VISION_MODEL = "test/vision-model"


# ── Картинки и страницы ─────────────────────────────────────────────────────


def _png(size: tuple[int, int], seed: int = 0) -> bytes:
    """Картинка с уникальным рисунком: разный `seed` — разный хеш выреза."""
    image = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, size[0] - 4, size[1] - 4), outline="black", width=3)
    draw.line((0, seed % size[1], size[0], size[1] - seed % size[1]), fill="black", width=2)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _page_with(text: str = "", image: bytes | None = None, rect: fitz.Rect | None = None):
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    if image is not None:
        page.insert_image(rect or page.rect, stream=image)
    if text:
        page.insert_textbox(fitz.Rect(60, 60, 540, 800), text, fontsize=11)
    return document, page


PROSE = (
    "Сетевой уровень отвечает за доставку пакетов между узлами разных сетей. "
    "Маршрутизатор выбирает путь по таблице маршрутизации и метрике. "
) * 6
# Одна строка поверх полностраничного растра: номер и колонтитул скана.
PAGE_LINE = "Страница 12. Глава 3, раздел о маршрутизации"


# ── Диагноз текстового слоя ─────────────────────────────────────────────────


def test_a_normal_text_layer_is_trusted() -> None:
    _, page = _page_with(PROSE)

    diagnosis = text_layer.diagnose(page)

    assert diagnosis.route == "text"
    assert not diagnosis.suspicious


def test_a_full_page_raster_with_one_line_is_a_partial_layer() -> None:
    """Скан с номером страницы в слое — не текстовая страница."""
    _, page = _page_with(PAGE_LINE, _png((600, 840)))

    diagnosis = text_layer.diagnose(page)

    assert diagnosis.route == "partial"
    assert "text_layer_partial" in diagnosis.diagnostics()


def test_an_empty_page_is_blank_and_a_bare_raster_is_a_scan() -> None:
    _, blank = _page_with()
    _, scan = _page_with(image=_png((600, 840)))

    assert text_layer.diagnose(blank).route == "blank"
    assert text_layer.diagnose(scan).route == "scan"


def test_cp1251_read_as_latin1_is_a_broken_layer() -> None:
    mojibake = PROSE.encode("cp1251").decode("latin-1")
    _, page = _page_with(mojibake)

    diagnosis = text_layer.diagnose(page)

    assert diagnosis.route == "broken"
    assert "text_layer_mojibake" in diagnosis.reasons


def test_replacement_and_private_use_glyphs_lower_the_layer_quality() -> None:
    """Сломанный шрифт отдаёт U+FFFD и символы частного использования."""
    _, good, _ = text_layer._quality("Обычный текст учебника: IP, TCP, 2 + 2 = 4.")
    _, bad, _ = text_layer._quality("� т�кст �")

    assert good == 1.0
    assert bad < text_layer.MIN_GOOD_RATIO


# ── Маршрут страницы ────────────────────────────────────────────────────────


class DescribingRecognizer:
    """Заглушка модели, которая описывает каждый присланный вырез."""

    def __init__(self) -> None:
        self.pages: list[int] = []
        self.regions: list[RegionRequest] = []
        self.described: list[ImageRequest] = []

    def recognize_page(
        self, image: bytes, page_number: int, width: float, height: float
    ) -> ParsedPage:
        del image
        self.pages.append(page_number)
        element = ParsedElement("paragraph", "Страница целиком", (0.1, 0.1, 0.9, 0.2))
        return ParsedPage(page_number, width, height, "Страница целиком", "Страница целиком",
                          "ocr", (element,), (), 0.9)

    def recognize_regions(
        self, regions: Sequence[RegionRequest], page_number: int
    ) -> list[RecognizedRegion]:
        del page_number
        self.regions.extend(regions)
        return [RecognizedRegion(region.index, "formula", "$$x$$", 0.9) for region in regions]

    def describe_images(self, images: Sequence[ImageRequest]) -> list[DescribedImage]:
        self.described.extend(images)
        return [
            DescribedImage(
                request.index,
                ImageDescription(kind="diagram", title="Схема сети",
                                 summary="Два маршрутизатора соединены каналом связи.",
                                 confidence=0.9),
                "unreviewed",
                (),
                "content",
                run_id="run",
                model_id=VISION_MODEL,
            )
            for request in images
        ]


def _save(document: fitz.Document, path: Path) -> Path:
    document.save(path)
    return path


def _parse(
    path: Path,
    mode: ParserMode,
    recognizer: DescribingRecognizer | None,
    **params: object,
) -> list[ParsedPage]:
    return list(
        native.iter_pages(path, mode, params=OcrRuntimeParams(**params), recognizer=recognizer)
    )


def test_adaptive_cloud_sends_a_partial_page_to_the_model_whole(tmp_path: Path) -> None:
    document, _ = _page_with(PAGE_LINE, _png((600, 840)))
    recognizer = DescribingRecognizer()

    page = _parse(_save(document, tmp_path / "partial.pdf"), ParserMode.CLOUD, recognizer)[0]

    assert recognizer.pages == [1]
    assert "route:partial" in page.diagnostics
    assert "route_fallback:cloud_page" in page.diagnostics


def test_economy_keeps_a_partial_layer_and_flags_the_page(tmp_path: Path) -> None:
    document, _ = _page_with(PAGE_LINE, _png((600, 840)))
    recognizer = DescribingRecognizer()

    page = _parse(
        _save(document, tmp_path / "partial.pdf"), ParserMode.CLOUD, recognizer,
        cloud_strategy="economy",
    )[0]

    assert recognizer.pages == []
    assert page.quality == "ocr_low"


def test_fast_mode_reads_a_partial_page_with_local_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def fake_paddle(path: Path, page_number: int, **_: object) -> ParsedPage:
        del path
        calls.append(page_number)
        element = ParsedElement("paragraph", "Текст со скана", (0.1, 0.1, 0.9, 0.2))
        return ParsedPage(page_number, 595, 842, "Текст со скана", "Текст со скана", "ocr",
                          (element,), (), 0.9)

    monkeypatch.setattr(native.paddle_fast, "parse_image", fake_paddle)
    document, _ = _page_with(PAGE_LINE, _png((600, 840)))

    page = _parse(_save(document, tmp_path / "partial.pdf"), ParserMode.FAST, None)[0]

    assert calls == [1]
    assert "route_fallback:local_ocr" in page.diagnostics
    assert page.plain_text == "Текст со скана"


def test_a_repeated_margin_logo_is_not_described_but_a_unique_diagram_is(
    tmp_path: Path,
) -> None:
    """Логотип на каждой странице — ноль вызовов, схема в теле — один."""
    logo = _png((120, 40), seed=1)
    diagram = _png((500, 300), seed=2)
    document = fitz.open()
    for number in range(2):
        page = document.new_page(width=595, height=842)
        page.insert_image(fitz.Rect(40, 20, 160, 60), stream=logo)
        page.insert_textbox(fitz.Rect(60, 90, 540, 400), PROSE, fontsize=11)
        if number == 0:
            page.insert_image(fitz.Rect(80, 450, 520, 720), stream=diagram)
    recognizer = DescribingRecognizer()

    pages = _parse(
        _save(document, tmp_path / "book.pdf"), ParserMode.CLOUD, recognizer,
        image_mode="describe",
    )

    assert len(recognizer.described) == 1
    described = [
        item for page in pages for item in page.elements
        if item.kind == "image" and item.image and item.image.processing == "described"
    ]
    assert len(described) == 1
    assert described[0].text.startswith(MODEL_DESCRIPTION_MARK)
    logos = [
        item for page in pages for item in page.elements
        if item.kind == "image" and item.image and XREF_REPEATED in item.image.signals
    ]
    assert logos and all(not auto_send(item.image) for item in logos)


def test_a_line_high_raster_is_read_as_a_formula_not_described(tmp_path: Path) -> None:
    """Формула, вставленная PNG высотой в строку, уходит пачкой вырезов, а не на описание."""
    document, page = _page_with(PROSE)
    page.insert_image(fitz.Rect(150, 420, 350, 434), stream=_png((400, 28), seed=6))
    recognizer = DescribingRecognizer()

    pages = _parse(
        _save(document, tmp_path / "inline.pdf"), ParserMode.CLOUD, recognizer,
        image_mode="describe",
    )

    assert recognizer.described == []
    assert [region.kind for region in recognizer.regions] == ["formula"]
    assert any(item.kind == "formula" for item in pages[0].elements)


def test_economy_does_not_describe_a_page_scan_under_a_thin_layer(tmp_path: Path) -> None:
    document, _ = _page_with(PAGE_LINE, _png((600, 840)))
    recognizer = DescribingRecognizer()

    pages = _parse(
        _save(document, tmp_path / "partial.pdf"), ParserMode.CLOUD, recognizer,
        cloud_strategy="economy", image_mode="describe",
    )

    assert recognizer.described == []
    images = [item for item in pages[0].elements if item.kind == "image"]
    assert images and "page_scan" in images[0].image.reasons


def test_skip_mode_marks_images_without_calling_the_model(tmp_path: Path) -> None:
    document, page = _page_with(PROSE)
    page.insert_image(fitz.Rect(80, 450, 520, 720), stream=_png((500, 300), seed=3))
    recognizer = DescribingRecognizer()

    pages = _parse(
        _save(document, tmp_path / "skip.pdf"), ParserMode.CLOUD, recognizer, image_mode="skip"
    )

    assert recognizer.described == []
    images = [item for item in pages[0].elements if item.kind == "image"]
    assert images and all(item.image.processing == "skipped" for item in images)


# ── Отбор кандидатов ────────────────────────────────────────────────────────


def _image(bbox: tuple[float, float, float, float], **meta: object) -> ParsedElement:
    return ParsedElement(
        "image", IMAGE_PLACEHOLDER, bbox, asset_path="assets/x/p1-0-0123456789abcdef.png",
        image=ImageMeta(**meta),  # type: ignore[arg-type]
    )


def test_a_small_repeated_margin_image_is_service() -> None:
    meta = classify(_image((0.05, 0.02, 0.2, 0.06), pixel_size=(120, 40)), repeats=5)

    assert meta.role == "service"
    assert "repeated_margin" in meta.reasons
    assert not auto_send(meta)


def test_a_unique_body_image_goes_to_description() -> None:
    meta = classify(_image((0.1, 0.4, 0.9, 0.8), pixel_size=(800, 400)))

    assert meta.role == "content"
    assert auto_send(meta)


def test_a_repeated_body_image_waits_for_a_person() -> None:
    meta = classify(_image((0.1, 0.4, 0.9, 0.8), signals=(XREF_REPEATED,)))

    assert meta.role == "unknown"
    assert "repeated_body" in meta.reasons
    assert meta.review == "needs_review"
    assert not auto_send(meta)


def test_a_small_image_with_a_caption_is_content_and_a_crumb_is_decorative() -> None:
    captioned = classify(
        _image((0.4, 0.5, 0.5, 0.52), pixel_size=(40, 20), caption="Рис. 3. Легенда")
    )
    crumb = classify(_image((0.4, 0.5, 0.41, 0.51), pixel_size=(10, 10)))

    assert auto_send(captioned)
    assert crumb.role == "decorative"


def test_a_manual_decision_is_not_overwritten() -> None:
    meta = classify(
        _image((0.05, 0.02, 0.2, 0.06), role="content", review="manual"), repeats=10
    )

    assert meta.role == "content"
    assert meta.review == "manual"


# ── Проверка ответа ─────────────────────────────────────────────────────────


def _answer(**overrides: object) -> CloudImageDescription:
    payload: dict[str, object] = {
        "kind": "diagram",
        "content_role": "content",
        "crop_issue": "none",
        "title": "Модель OSI",
        "summary": "Семь уровней модели OSI от физического до прикладного.",
        "visible_objects": ["уровни"],
        "relations": [],
        "labels": ["Физический", "Канальный"],
        "unreadable": [],
        "details": [],
        "table_markdown": "",
        "latex": "",
        "context_note": "",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return CloudImageDescription.model_validate(payload)


def _described(answer: CloudImageDescription) -> ParsedElement:
    verdict = validate_description(answer, 0)
    assert verdict.description is not None
    return with_description(
        _image((0.1, 0.4, 0.9, 0.8)),
        verdict.description,
        review=verdict.review,
        reasons=verdict.reasons,
        role_hint=verdict.role_hint,
        provenance=ImageProvenance("parse", model_id=VISION_MODEL),
    )


def test_a_good_answer_becomes_searchable_text_marked_as_the_models() -> None:
    element = _described(_answer())

    assert element.text.startswith(MODEL_DESCRIPTION_MARK)
    assert "Модель OSI" in element.text
    assert "Надписи: Физический; Канальный" in element.text
    assert element.image.processing == "described"
    assert element.image.review == "unreviewed"


def test_a_cut_off_crop_is_kept_for_review_and_not_indexed() -> None:
    element = _described(_answer(crop_issue="cut_off"))

    assert element.text == IMAGE_PLACEHOLDER
    assert element.image.review == "needs_review"
    assert "crop_suspect" in element.image.reasons


def test_an_empty_answer_is_an_error_not_a_description() -> None:
    verdict = validate_description(_answer(title="", summary=""), 0)

    assert verdict.description is None
    assert "empty_answer" in verdict.reasons


def test_a_picture_that_is_a_formula_becomes_a_formula() -> None:
    element = _described(
        _answer(kind="formula", summary="Формула полной вероятности события.",
                latex=r"P(A) = \sum_i P(A \mid H_i) P(H_i)")
    )

    assert element.kind == "formula"
    assert element.text.startswith("$$")


def test_the_models_opinion_about_decoration_goes_to_review() -> None:
    element = _described(_answer(content_role="decorative"))

    assert element.image.role == "decorative"
    assert element.image.review == "needs_review"
    assert element.text == IMAGE_PLACEHOLDER


def test_reclassifying_the_revision_keeps_the_models_verdict_and_review_reasons() -> None:
    """Пересчёт повторов после разбора не стирает мнение модели и причины проверки."""
    decorative = classify(_described(_answer(content_role="decorative")))
    doubtful = classify(_described(_answer(confidence=0.3)))

    assert decorative.role == "decorative"
    assert "model_role_decorative" in decorative.reasons
    assert "low_confidence" in doubtful.reasons


# ── Вызовы модели и предел запуска ──────────────────────────────────────────


@pytest.fixture
def vision_model(session: Session, ai_config: str) -> str:
    """Зрительная модель и она же модель «Облака» по умолчанию."""
    del ai_config
    provider_id = session.scalar(select(AiProviderConnection.id))
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
            completion_price_usd=Decimal("0.00000060"),
            pricing_snapshot_at=now,
            catalog_snapshot_at=now,
            is_manually_added=True,
            is_available=True,
        )
    )
    settings_row = session.get(AiSettings, 1)
    settings_row.default_vision_provider_id = provider_id
    settings_row.default_vision_model_id = VISION_MODEL
    session.commit()
    return VISION_MODEL


def _completion(**overrides: object) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(_answer(**overrides).model_dump(), ensure_ascii=False),
        actual_model_id=VISION_MODEL,
        usage=ProviderUsage(input_tokens=1600, output_tokens=300),
    )


def _request(index: int, data: bytes, caption: str | None = None) -> ImageRequest:
    return ImageRequest(index, data, 1, native.crop_hash(data), caption, "", "image/png")


def test_the_same_crop_twice_costs_one_call(session: Session, vision_model: str) -> None:
    del vision_model
    session.rollback()
    transport = FakeTransport(completions=[_completion()])
    recognizer = CloudRecognizer(session, transport=transport, retry_backoff=(),
                                 image_retry_backoff=())
    data = _png((300, 200), seed=5)

    try:
        answers = recognizer.describe_images(
            [_request(0, data, "Рис. 1"), _request(1, data, "Рис. 7")]
        )
    finally:
        recognizer.close()

    assert transport.complete_calls == 1
    assert [answer.description.title for answer in answers] == ["Модель OSI", "Модель OSI"]
    assert answers[1].description.context_note == "Подпись: Рис. 7"


def _job(session: Session, budget: dict[str, object]) -> UUID:
    job = BackgroundJob(
        kind=BackgroundJobKind.IMAGE_DESCRIPTIONS,
        state=BackgroundJobState.RUNNING,
        done=0,
        total=1,
        checkpoint={"budget": budget},
        diagnostics=[],
        pause_requested=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(job)
    session.commit()
    return job.id


def test_the_call_limit_stops_the_run_before_the_request(session: Session) -> None:
    budget = JobBudget(session, _job(session, budget_state(
        max_cost_usd=None, max_calls=1, allow_unknown_price=True
    )))

    budget.settle(budget.reserve(100, Decimal("0.001")), ProviderUsage(cost_usd=Decimal("0.0005")))
    with pytest.raises(ProjectDomainError) as caught:
        budget.reserve(100, Decimal("0.001"))

    assert caught.value.code == "run_budget_exhausted"


def test_the_money_limit_counts_open_reserves(session: Session) -> None:
    job_id = _job(session, budget_state(
        max_cost_usd=Decimal("0.01"), max_calls=None, allow_unknown_price=False
    ))
    budget = JobBudget(session, job_id)

    budget.reserve(100, Decimal("0.006"))
    with pytest.raises(ProjectDomainError) as exhausted:
        budget.reserve(100, Decimal("0.006"))
    with pytest.raises(ProjectDomainError) as unknown:
        budget.reserve(100, None)

    assert exhausted.value.code == "run_budget_exhausted"
    assert unknown.value.code == "run_budget_unknown_price"


def test_an_answer_without_usage_stays_spent_at_the_reserve(session: Session) -> None:
    job_id = _job(session, budget_state(
        max_cost_usd=Decimal("1"), max_calls=None, allow_unknown_price=True
    ))
    budget = JobBudget(session, job_id)

    budget.settle(budget.reserve(100, Decimal("0.004")), None)

    session.expire_all()
    state = session.get(BackgroundJob, job_id).checkpoint["budget"]
    assert Decimal(state["spent_usd"]) == Decimal("0.004")
    assert state["uncertain_calls"] == 1


# ── «Описать изображения» готового материала ────────────────────────────────


def _ready_material(session: Session, *, images: int = 2, legacy: bool = False) -> UUID:
    """Готовый материал с одной страницей: абзац и `images` уникальных схем.

    :param legacy: изображения без явного состояния — как у материалов,
        разобранных до появления осей роли и обработки.
    """
    material = make_material(session, "abc123")
    elements = [ParsedElement("paragraph", PROSE[:200], (0.1, 0.05, 0.9, 0.15))]
    for number in range(images):
        data = _png((400, 300), seed=10 + number)
        path = store_material_asset(material.sha256, f"p1-{number}.png", data)
        top = 0.2 + number * 0.35
        meta = None if legacy else ImageMeta(
            role="content", crop_hash=native.crop_hash(data), pixel_size=(400, 300)
        )
        elements.append(
            ParsedElement(
                "image", IMAGE_PLACEHOLDER, (0.1, top, 0.9, top + 0.3), asset_path=path,
                image=meta,
            )
        )
    session.add(
        MaterialPage(
            material_id=material.id, revision=1, page_number=1, width=595, height=842,
            text=PROSE[:200], markdown=PROSE[:200], quality=PageQuality.NATIVE,
            elements=[library.element_to_json(item) for item in elements],
            diagnostics=[], created_at=utc_now(),
        )
    )
    session.flush()
    library.rebuild_structure(session, material.id, 1)
    session.commit()
    return material.id


def _start(session: Session, material_id: UUID, target_ids: list[str]) -> UUID:
    session.rollback()
    started = image_descriptions.start(
        session, material_id, ImageDescriptionStart(expected_revision=1, target_ids=target_ids)
    )
    return started.job_id


def _run(
    session: Session, monkeypatch: pytest.MonkeyPatch, job_id: UUID, transport: FakeTransport
) -> BackgroundJob:
    original = image_descriptions.CloudRecognizer

    def recognizer(*args: object, **kwargs: object) -> CloudRecognizer:
        return original(*args, transport=transport, retry_backoff=(), image_retry_backoff=(),
                        **kwargs)

    monkeypatch.setattr(image_descriptions, "CloudRecognizer", recognizer)
    session.expire_all()
    image_descriptions.process_job(session, session.get(BackgroundJob, job_id))
    session.expire_all()
    return session.get(BackgroundJob, job_id)


def test_describing_a_ready_material_publishes_one_revision(
    session: Session, vision_model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del vision_model
    material_id = _ready_material(session)
    session.rollback()
    listed = image_descriptions.inventory(session, material_id)
    assert [item.id for item in listed.targets] == ["1:1", "1:2"]
    assert listed.price_known

    job_id = _start(session, material_id, [item.id for item in listed.targets])
    transport = FakeTransport(completions=[_completion(), _completion(title="Стек TCP/IP")])
    job = _run(session, monkeypatch, job_id, transport)

    assert job.state == BackgroundJobState.COMPLETED, job.error
    assert job.checkpoint["result"]["described"] == 2
    assert transport.complete_calls == 2
    material = library.material_or_404(session, material_id)
    assert material.active_parse_revision == 2
    texts = list(session.scalars(
        select(MaterialFragment.text)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(MaterialPage.material_id == material_id, MaterialPage.revision == 2,
               MaterialFragment.element_kind == "image")
    ))
    assert len(texts) == 2 and all(text.startswith(MODEL_DESCRIPTION_MARK) for text in texts)
    origin = session.scalar(
        select(MaterialRevision.origin).where(
            MaterialRevision.material_id == material_id, MaterialRevision.revision == 2
        )
    )
    assert origin == MaterialRevisionOrigin.IMAGE_DESCRIPTIONS

    session.rollback()
    again = image_descriptions.inventory(session, material_id)
    assert again.targets == [] and len(again.excluded) == 2
    with pytest.raises(ProjectDomainError) as caught:
        image_descriptions.start(
            session, material_id, ImageDescriptionStart(expected_revision=2, target_ids=["1:1"])
        )
    assert caught.value.code == "image_target_invalid"


def test_images_parsed_before_explicit_state_are_classified_in_the_inventory(
    session: Session, vision_model: str
) -> None:
    """Старый материал: уникальные схемы уходят по умолчанию, а не в «сомнительные»."""
    del vision_model
    material_id = _ready_material(session, legacy=True)
    session.rollback()

    listed = image_descriptions.inventory(session, material_id)

    assert [item.id for item in listed.targets] == ["1:1", "1:2"]
    assert listed.doubtful == []


def test_a_material_changed_during_the_run_gets_no_revision(
    session: Session, vision_model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del vision_model
    material_id = _ready_material(session, images=1)
    job_id = _start(session, material_id, ["1:1"])
    material = library.material_or_404(session, material_id)
    material.active_parse_revision = 5
    session.commit()

    job = _run(session, monkeypatch, job_id, FakeTransport(completions=[_completion()]))

    assert job.state == BackgroundJobState.FAILED
    assert job.checkpoint["result"]["conflict"] == 5
    assert "1:1" in job.checkpoint["results"]
    assert session.scalar(
        select(MaterialPage.id).where(
            MaterialPage.material_id == material_id, MaterialPage.revision > 1
        )
    ) is None


def test_a_cancelled_run_stops_before_the_next_paid_call(
    session: Session, vision_model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del vision_model
    material_id = _ready_material(session, images=1)
    job_id = _start(session, material_id, ["1:1"])
    session.get(BackgroundJob, job_id).pause_requested = True
    session.commit()
    transport = FakeTransport(completions=[_completion()])

    job = _run(session, monkeypatch, job_id, transport)

    assert job.state == BackgroundJobState.CANCELLED
    assert transport.complete_calls == 0
    assert library.material_or_404(session, material_id).active_parse_revision == 1


def test_an_unknown_target_is_refused_before_the_job_exists(
    session: Session, vision_model: str
) -> None:
    del vision_model
    material_id = _ready_material(session, images=1)
    session.rollback()

    with pytest.raises(ProjectDomainError) as caught:
        image_descriptions.start(
            session, material_id, ImageDescriptionStart(expected_revision=1, target_ids=["1:0"])
        )

    assert caught.value.code == "image_target_invalid"
    session.rollback()
    assert session.scalar(select(BackgroundJob.id)) is None
