"""Оценка PDF не повторяет дорогой анализ при опросе одного материала."""

from types import SimpleNamespace

import pymupdf

from app.materials import processing_plan
from app.ocr.engines import OcrRuntimeParams


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
