"""Hardware gate for the local textbook OCR service on a real PDF."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import pymupdf as fitz


DEFAULT_PAGES = "1,6,13,14,15,28,38,42,61,68"


def parse_pages(value: str, page_count: int) -> list[int]:
    pages: set[int] = set()
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start, end = (int(item) for item in token.split("-", 1))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(token))
    invalid = sorted(page for page in pages if page < 1 or page > page_count)
    if invalid:
        raise ValueError(f"Pages outside 1..{page_count}: {invalid}")
    return sorted(pages)


def parse_page(service_url: str, page_number: int, image: bytes, timeout: int) -> dict:
    payload = json.dumps(
        {
            "page_number": page_number,
            "image_base64": base64.b64encode(image).decode("ascii"),
        }
    ).encode()
    request = urllib.request.Request(
        f"{service_url.rstrip('/')}/parse",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {body}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--service-url", default="http://127.0.0.1:8090")
    parser.add_argument("--pages", default=DEFAULT_PAGES)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    document = fitz.open(args.pdf)
    pages = list(range(1, document.page_count + 1)) if args.all else parse_pages(
        args.pages, document.page_count
    )
    print(f"pdf={args.pdf} pages={len(pages)}/{document.page_count}", flush=True)

    started = time.perf_counter()
    for page_number in pages:
        page_started = time.perf_counter()
        page = document.load_page(page_number - 1)
        scale = args.dpi / 72
        image = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
        result = parse_page(args.service_url, page_number, image, args.timeout)
        kinds = Counter(str(item.get("label") or "unknown") for item in result.get("elements", []))
        executor = next(
            (
                item.removeprefix("textbook_executor:")
                for item in result.get("diagnostics", [])
                if item.startswith("textbook_executor:")
            ),
            "unknown",
        )
        print(
            json.dumps(
                {
                    "page": page_number,
                    "seconds": round(time.perf_counter() - page_started, 2),
                    "executor": executor,
                    "elements": sum(kinds.values()),
                    "kinds": kinds,
                    "markdown_chars": len(result.get("markdown") or ""),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    print(
        json.dumps(
            {"status": "passed", "pages": len(pages), "seconds": round(time.perf_counter() - started, 2)},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
