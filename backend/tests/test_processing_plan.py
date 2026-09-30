"""Оценка PDF не повторяет дорогой анализ при опросе одного материала."""

from decimal import Decimal
from types import SimpleNamespace

import pymupdf
import pytest

from app.materials import processing_plan
from app.materials.schemas import ProcessingStart
from app.models import ParserMode
from app.ocr.engines import OcrRuntimeParams
from app.projects.errors import ProjectConflictError


def test_pdf_shape_samples_and_reuses_diagnosis(tmp_path, monkeypatch):
    """Несколько запросов одного PDF диагностируют ограниченную выборку один раз."""
    path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    for _ in range(80):
        document.new_page()
    document.save(path)
    document.close()

    examined = []

    def diagnose(page):
        examined.append(page.number)
        return SimpleNamespace(route="scan")

    monkeypatch.setattr(processing_plan, "diagnose", diagnose)
    params = OcrRuntimeParams(cloud_strategy="auto")
    pages = list(range(1, 81))

    first = processing_plan._calculate_pdf_shape(
        path, tuple(pages), params.cloud_strategy, params.raster_scale
    )

    assert first.sampled
    assert first.whole_pages == 80
    assert len(examined) <= processing_plan.MAX_SAMPLED_PAGES

    submitted = []

    class Executor:
        def submit(self, *args):
            submitted.append(args)
            return SimpleNamespace(result=lambda: first)

    monkeypatch.setattr(processing_plan, "_shape_executor", Executor())
    processing_plan._cached_pdf_shape.cache_clear()
    assert processing_plan._pdf_shape(path, pages, params) == first
    assert processing_plan._pdf_shape(path, pages, params) == first
    assert len(submitted) == 1


def test_quick_budget_does_not_need_pdf_estimate(monkeypatch):
    """Быстрый лимит известной модели не запускает диагностику страниц."""
    selection = SimpleNamespace(model_id="vision")
    monkeypatch.setattr(processing_plan, "page_model", lambda session: selection)
    monkeypatch.setattr(
        processing_plan, "_price", lambda session, model: (Decimal("0.001"), Decimal("0.002"))
    )
    command = ProcessingStart(parser_mode=ParserMode.CLOUD)

    budget = processing_plan.run_budget(None, command, 46, "describe")

    assert budget["max_cost_usd"] == "10"
    assert budget["max_calls"] == 46 * processing_plan.QUICK_CALLS_PER_PAGE + 4
    assert budget["allow_unknown_price"] is False


def test_quick_budget_unknown_price_needs_consent(monkeypatch):
    """Без тарифа подтверждение остаётся обязательным до первого вызова."""
    monkeypatch.setattr(processing_plan, "page_model", lambda session: None)
    with pytest.raises(ProjectConflictError) as caught:
        processing_plan.run_budget(
            None, ProcessingStart(parser_mode=ParserMode.CLOUD), 1, "skip"
        )
    assert caught.value.code == "ai_price_unknown"
    budget = processing_plan.run_budget(
        None, ProcessingStart(parser_mode=ParserMode.CLOUD, confirm_unknown_price=True),
        1, "skip",
    )
    assert budget["max_cost_usd"] is None
    assert budget["max_calls"] == processing_plan.QUICK_CALLS_PER_PAGE + 4
