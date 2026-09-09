"""Структурная валидация Tentex OCR Bench v2."""
from __future__ import annotations
import json
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parent
PDF = ROOT / "tentex_ocr_bench_v2_24p.pdf"
GT = ROOT / "ground_truth"


def require(cond, message):
    if not cond:
        raise AssertionError(message)


def main():
    require(PDF.exists(), f"missing {PDF.name}")
    doc = fitz.open(PDF)
    require(len(doc) == 24, f"expected 24 pages, got {len(doc)}")

    # Все страницы A4; только 19–21 обязаны иметь нативный text layer.
    for i, page in enumerate(doc, 1):
        require(abs(page.rect.width - 595.276) < 1.0, f"p{i}: bad width {page.rect.width}")
        require(abs(page.rect.height - 841.89) < 1.0, f"p{i}: bad height {page.rect.height}")
        text = page.get_text("text").strip()
        images = page.get_images(full=True)
        if 19 <= i <= 21:
            require(len(text) >= 350, f"p{i}: native text layer too small ({len(text)})")
            require(len(images) == 0, f"p{i}: native page unexpectedly contains images")
        else:
            require(len(text) == 0, f"p{i}: raster page unexpectedly has text layer")
            require(len(images) >= 1, f"p{i}: raster page has no image")

    native_text = "\n".join(doc[i - 1].get_text("text") for i in (19, 20, 21))
    for token in ("Нативный PDF", "∫", "∑", "det", "Var", "ℙ"):
        require(token in native_text, f"native text layer lacks token {token!r}")

    md_files = sorted(GT.glob("page_*.md"))
    require(len(md_files) == 24, f"expected 24 GT markdown files, got {len(md_files)}")
    for i, path in enumerate(md_files, 1):
        require(path.name == f"page_{i:02d}.md", f"GT numbering gap at {path}")
        txt = path.read_text(encoding="utf-8")
        require(len(txt) > 350, f"{path.name}: suspiciously short")
        require(txt.startswith("---\n"), f"{path.name}: missing front matter")

    manifest = json.loads((GT / "manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("version") == "2.0", "manifest version must be 2.0")
    require(manifest.get("page_count") == 24, "manifest page_count must be 24")
    pages = manifest.get("pages", [])
    require(len(pages) == 24, f"manifest has {len(pages)} page rows")
    require([p["page"] for p in pages] == list(range(1, 25)), "manifest pages not 1..24")

    for i in range(11, 17):
        geom_path = ROOT / "photo_geometry" / f"page_{i:02d}.json"
        jpg_path = ROOT / "photo_pages" / f"page_{i:02d}.jpg"
        require(geom_path.exists(), f"missing {geom_path}")
        require(jpg_path.exists(), f"missing {jpg_path}")
        geom = json.loads(geom_path.read_text(encoding="utf-8"))
        require(len(geom["page_corners_px"]) == 4, f"p{i}: corners != 4")
        require(len(geom["page_corners_normalized"]) == 4, f"p{i}: normalized corners != 4")
        for x, y in geom["page_corners_normalized"]:
            require(0 <= x <= 1 and 0 <= y <= 1, f"p{i}: normalized corner outside image")

    for p in [
        ROOT / "native_latex" / "native_formulas.tex",
        ROOT / "native_latex" / "native_formulas.pdf",
        ROOT / "sources" / "contents_user_example.pdf",
        ROOT / "reference_photos" / "cad_notes.jpg",
        ROOT / "reference_photos" / "combinatorics_tasks.jpg",
        ROOT / "reference_photos" / "recurrences_pascal.jpg",
        ROOT / "README.md",
        ROOT / "SOURCES.md",
    ]:
        require(p.exists(), f"missing required file {p}")

    print("OK: 24 pages")
    print("OK: pages 19–21 have native extractable text and zero images")
    print("OK: 21 raster/photo/TOC pages have image content and no text layer")
    print("OK: 24 ground-truth Markdown files and manifest v2")
    print("OK: 6 phone-photo geometry sidecars")
    print("OK: source and reference materials present")


if __name__ == "__main__":
    main()
