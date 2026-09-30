"""Ресурсы PDF не равны рисункам: проверяем видимые области и маршруты."""

from io import BytesIO

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw

from app.materials import processing_plan, storage
from app.materials.parsers import native, page_geometry, pdf_visuals, text_layer
from app.materials.parsers.base import IMAGE_PLACEHOLDER, ParsedElement, ParsedPage
from app.models import ParserMode
from app.ocr.engines import OcrRuntimeParams

PROSE = "These complete sentences belong to the text of the document."


def _png(*, transparent: bool = False) -> bytes:
    image = Image.new("RGBA" if transparent else "RGB", (200, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 25, 175, 175), fill="red")
    if transparent:
        image.putalpha(64)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _page():
    document = fitz.open()
    return document, document.new_page(width=500, height=700)


def _prose(page, *, y=80):
    for offset in range(4):
        page.insert_text((30, y + 22 * offset), PROSE, fontsize=11)


def test_tiled_background_and_scan_share_the_same_rule():
    document, page = _page()
    for top in (0, 350):
        page.insert_image(fitz.Rect(0, top, 500, top + 350), stream=_png(), keep_proportion=False)
    _prose(page)
    assert pdf_visuals.raster_regions(page) == []
    assert page_geometry.page_geometry(page, []).figures == ()
    document.close()


def test_a_small_textured_panel_is_a_backdrop_too():
    document, page = _page()
    page.insert_image(fitz.Rect(20, 60, 420, 175), stream=_png(), keep_proportion=False)
    _prose(page)
    assert pdf_visuals.raster_regions(page) == []
    document.close()


def test_frontmost_photo_is_not_removed_because_old_text_is_beneath_it():
    document, page = _page()
    _prose(page)
    page.insert_image(page.rect, stream=_png(), keep_proportion=False)
    assert len(pdf_visuals.raster_regions(page)) == 1
    document.close()


def test_scan_with_only_a_page_number_keeps_its_content():
    document, page = _page()
    page.insert_image(page.rect, stream=_png(), keep_proportion=False)
    page.insert_text((30, 650), "Page 12. Chapter about routing", fontsize=11)
    assert len(pdf_visuals.raster_regions(page)) == 1
    assert text_layer.diagnose(page).route == "partial"
    document.close()


def test_pdf_artifact_is_a_backdrop_even_when_painted_after_the_text():
    document, page = _page()
    _prose(page)
    page.insert_image(page.rect, stream=_png(), keep_proportion=False)
    content = page.get_contents()[-1]
    document.update_stream(content, b"/Artifact <</Type /Page>> BDC\n"
                           + document.xref_stream(content) + b"\nEMC")
    assert pdf_visuals.raster_regions(page) == []
    assert page_geometry.page_geometry(page, []).figures == ()
    # Строка '/Artifact' в пользовательском тексте ничего не исключает.
    document.close()


def test_artifact_scope_does_not_spread_to_content_with_the_same_xref():
    document, page = _page()
    page.insert_image(fitz.Rect(20, 60, 420, 175), stream=_png(), keep_proportion=False)
    content = page.get_contents()[-1]
    document.update_stream(content, b"/Artifact BMC\n" + document.xref_stream(content) + b"\nEMC")
    _prose(page)
    page.insert_image(fitz.Rect(100, 300, 300, 500), stream=_png())
    regions = pdf_visuals.raster_regions(page)
    assert len(regions) == 1 and regions[0].rect == fitz.Rect(100, 300, 300, 500)
    assert not regions[0].artifact
    document.close()


def test_overlapping_occurrences_merge_but_separate_occurrences_remain():
    document, page = _page()
    data = _png()
    for offset in range(7):
        page.insert_image(fitz.Rect(30 + offset, 200 + offset, 230 + offset, 400 + offset),
                          stream=data)
    page.insert_image(fitz.Rect(280, 450, 480, 650), stream=data)
    regions = pdf_visuals.raster_regions(page)
    assert len(regions) == 2
    assert regions[0].rect == fitz.Rect(30, 200, 236, 406)
    assert regions[1].rect == fitz.Rect(280, 450, 480, 650)
    document.close()


def test_native_uses_composited_crop_and_the_correct_resource(tmp_path, monkeypatch):
    document, page = _page()
    background = page.insert_image(page.rect, stream=_png(), keep_proportion=False)
    _prose(page)
    page.draw_rect(fitz.Rect(100, 200, 300, 400), fill=(1, 1, 1))
    own = page.insert_image(fitz.Rect(100, 200, 300, 400), stream=_png(transparent=True))
    monkeypatch.setattr(storage.settings, "data_dir", tmp_path)

    parsed = native._native_pdf_page(page, 1, "test", repeated_xrefs=frozenset({background}))

    images = [element for element in parsed.elements if element.kind == "image"]
    assert len(images) == 1
    assert images[0].image.signals == ()
    assert pdf_visuals.raster_regions(page)[0].xrefs == frozenset({own})
    with Image.open(storage.material_path(images[0].asset_path)) as crop:
        # Маска 25% делает красный светлее. Исходный растр был ярко-красным.
        assert crop.getpixel((crop.width // 2, crop.height // 2))[1] > 100
    document.close()


def test_crop_follows_pdf_clipping_not_the_resource_dimensions(tmp_path, monkeypatch):
    source, image_page = _page()
    image_page.insert_image(fitz.Rect(0, 0, 400, 400), stream=_png())
    document, page = _page()
    page.show_pdf_page(fitz.Rect(100, 200, 300, 400), source, 0,
                       clip=fitz.Rect(100, 100, 300, 300))
    _prose(page)
    monkeypatch.setattr(storage.settings, "data_dir", tmp_path)

    region = pdf_visuals.raster_regions(page)[0]
    assert region.rect == fitz.Rect(100, 200, 300, 400)
    parsed = native._native_pdf_page(page, 1, "clip")
    element = next(element for element in parsed.elements if element.kind == "image")
    assert element.bbox == (0.2, 200 / 700, 0.6, 400 / 700)
    document.close()
    source.close()


@pytest.mark.parametrize("strategy", ["auto", "page", "economy"])
def test_vector_content_changes_adaptive_route_and_cost_together(tmp_path, strategy):
    document, page = _page()
    _prose(page)
    # Формула или схема, набранная контурами: текста у этой области нет.
    page.draw_bezier((100, 300), (100, 380), (300, 300), (300, 380))
    path = tmp_path / "vectors.pdf"
    document.save(path)
    params = OcrRuntimeParams(cloud_strategy=strategy)
    unmapped = pdf_visuals.has_unmapped_graphics(page)
    assert unmapped
    route = native._page_route(text_layer.diagnose(page), ParserMode.CLOUD, params,
                               True, strategy == "page", unmapped_graphics=unmapped)
    shape = processing_plan._local_pdf_shape(path, (1,), strategy, params.raster_scale)
    assert (route in native.CLOUD_PAGE_ROUTES) == (strategy != "economy")
    assert shape.whole_pages == (1 if strategy != "economy" else 0)
    document.close()


def test_full_page_background_path_cannot_swallow_a_figure():
    document, page = _page()
    page.draw_rect(page.rect, fill=(1, 1, 1))
    _prose(page)
    page.insert_image(fitz.Rect(100, 200, 300, 400), stream=_png())
    geometry = page_geometry.page_geometry(page, [])
    assert geometry.figures == ((0.2, 200 / 700, 0.6, 400 / 700),)
    assert not pdf_visuals.has_unmapped_graphics(page)
    document.close()


def test_layout_parts_become_one_crop_of_the_complete_raster(tmp_path, monkeypatch):
    document, page = _page()
    page.insert_image(fitz.Rect(100, 200, 300, 400), stream=_png())
    _prose(page)
    monkeypatch.setattr(storage.settings, "data_dir", tmp_path)
    legacy = native._native_pdf_page(page, 1, "parts")
    parsed = ParsedPage(1, 500, 700, "", "", "native", (
        ParsedElement("image", IMAGE_PLACEHOLDER, (0.2, 200 / 700, 0.6, 300 / 700)),
        ParsedElement("image", IMAGE_PLACEHOLDER, (0.2, 300 / 700, 0.6, 400 / 700)),
    ))
    reconciled = native._reconcile_layout_images(page, parsed, legacy.elements, "parts")
    assert len(reconciled.elements) == 1
    assert reconciled.elements[0].bbox == (0.2, 200 / 700, 0.6, 400 / 700)
    assert reconciled.elements[0].asset_path
    document.close()


def test_legitimate_inline_image_is_content():
    document, page = _page()
    _prose(page)
    xref = document.get_new_xref()
    document.update_object(xref, "<<>>")
    colors = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
    document.update_stream(xref, b"q 100 0 0 100 100 200 cm\n"
                           b"BI /W 2 /H 2 /BPC 8 /CS /RGB ID " + colors + b"\nEI\nQ")
    contents = page.get_contents()
    document.xref_set_key(page.xref, "Contents",
                          "[" + " ".join(f"{value} 0 R" for value in (*contents, xref)) + "]")
    assert len(pdf_visuals.raster_regions(page)) == 1
    document.close()


@pytest.mark.parametrize("main_position", ["absent", "before", "after"])
def test_images_in_soft_mask_definitions_are_not_independent_figures(main_position):
    document, page = _page()
    _prose(page)
    source = document.new_page(width=100, height=100)
    image_xref = source.insert_image(source.rect, stream=_png())
    page = document[0]
    form = document.get_new_xref()
    document.update_object(form, "<< /Type /XObject /Subtype /Form /BBox [0 0 500 700] "
                           f"/Resources << /XObject << /I {image_xref} 0 R >> >> "
                           "/Group << /S /Transparency /CS /DeviceGray >> >>")
    document.update_stream(form, b"q 200 0 0 200 100 200 cm /I Do Q")
    state = document.get_new_xref()
    document.update_object(state,
                           f"<< /Type /ExtGState /SMask << /S /Luminosity /G {form} 0 R >> >>")
    resources = int(document.xref_get_key(page.xref, "Resources")[1].split()[0])
    document.xref_set_key(resources, "ExtGState", f"<< /E {state} 0 R >>")
    main_rect = fitz.Rect(250, 430, 400, 580)
    if main_position == "before":
        page.insert_image(main_rect, xref=image_xref)
    content = document.get_new_xref()
    document.update_object(content, "<<>>")
    document.update_stream(content, b"q /E gs .8 g 100 200 200 200 re f Q")
    contents = (*page.get_contents(), content)
    document.xref_set_key(page.xref, "Contents",
                          "[" + " ".join(f"{value} 0 R" for value in contents) + "]")
    if main_position == "after":
        page.insert_image(main_rect, xref=image_xref)
    assert page.get_image_info(), "MuPDF видит bitmap внутри определения SMask"
    regions = pdf_visuals.raster_regions(page)
    assert [region.rect for region in regions] == ([] if main_position == "absent" else [main_rect])
    document.close()


def test_colored_background_cannot_be_recovered_as_a_copy_of_the_whole_page(tmp_path, monkeypatch):
    image = Image.new("RGB", (500, 700), "navy")
    output = BytesIO()
    image.save(output, format="PNG")
    parsed = ParsedPage(1, 500, 700, "", "", "ocr", (
        ParsedElement("heading", "Document title", (0.1, 0.1, 0.9, 0.15)),
    ))
    monkeypatch.setattr(storage.settings, "data_dir", tmp_path)
    recovered = native._missed_regions(parsed, output.getvalue(), "cover")
    assert recovered.elements == parsed.elements
    assert "unread_page_background" in recovered.diagnostics


def test_illustration_with_explanatory_text_is_not_a_page_backdrop():
    document, page = _page()
    _prose(page)
    page.insert_image(fitz.Rect(20, 290, 420, 410), stream=_png(), keep_proportion=False)
    _prose(page, y=310)
    _prose(page, y=500)
    assert len(pdf_visuals.raster_regions(page)) == 1
    document.close()


def test_connected_vector_frames_do_not_merge_separate_raster_illustrations():
    document, page = _page()
    _prose(page)
    first, second = fitz.Rect(50, 300, 200, 450), fitz.Rect(270, 300, 420, 450)
    for rect in (first, second):
        page.insert_image(rect, stream=_png())
        page.draw_rect(rect, radius=0.1)
    page.draw_line((200, 375), (270, 375))
    geometry = page_geometry.page_geometry(page, [])
    assert len(geometry.figures) == 2
    answer = ParsedPage(1, 500, 700, "", "", "ocr", (
        ParsedElement("image", IMAGE_PLACEHOLDER, (0.1, 300 / 700, 0.4, 450 / 700)),
        ParsedElement("image", IMAGE_PLACEHOLDER, (0.54, 300 / 700, 0.84, 450 / 700)),
    ))
    snapped = page_geometry.snap_to_layer(answer, geometry)
    assert len([item for item in snapped.elements if item.kind == "image"]) == 2
    document.close()
