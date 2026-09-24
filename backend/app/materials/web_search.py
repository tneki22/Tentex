"""Поиск в интернете через локальный SearXNG и лёгкое чтение найденных страниц.

SearXNG — метапоисковик в соседнем контейнере (`docker-compose.yml`, `searxng/`):
бесплатный, без ключей и без привязки к провайдеру модели. Здесь только выдача и
объём страниц; что из найденного показать и почему, решает чат поиска
(`app/projects/source_search_chat.py`).

Чтение страниц идёт по образцу `external.py`: только публичные адреса (защита от
SSRF, в том числе на редиректах), предел размера и типа содержимого, короткий
таймаут. Страница, которую не удалось прочитать, не ошибка — у неё просто нет объёма.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, urlopen

import pymupdf as fitz

from app.config import settings
from app.materials.external import _ReadableHtml, _SafeRedirect, _validate_public_url
from app.projects.errors import ProjectDomainError

log = logging.getLogger("tentex.web_search")

SearchCategory = Literal["general", "videos", "science"]
SearchLanguage = Literal["ru", "en", "all"]

SEARCH_TIMEOUT_SECONDS = 20
PROBE_TIMEOUT_SECONDS = 6
# Общий предел на чтение пачки страниц: медленный сайт не держит весь ход чата.
PROBE_BATCH_SECONDS = 12
MAX_HTML_BYTES = 2 * 1024 * 1024
# PDF крупнее скачивать ради числа страниц дорого: показываем только размер.
MAX_PDF_BYTES = 15 * 1024 * 1024
EXCERPT_CHARS = 1200
WORDS_PER_MINUTE = 180
FILE_LINK = re.compile(r"\.(pdf|djvu|docx?|epub)(?:$|[?#])", re.IGNORECASE)
PROBE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Tentex/0.1; local study assistant)",
    "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5",
}


class WebSearchUnavailableError(ProjectDomainError):
    def __init__(self, detail: str, code: str = "web_search_unavailable") -> None:
        super().__init__(detail, status=503, code=code)


@dataclass(frozen=True)
class WebHit:
    url: str
    title: str
    snippet: str
    engine: str
    # Длительность видео из выдачи («40:46»); у страниц — None.
    duration: str | None = None
    author: str | None = None


@dataclass(frozen=True)
class WebSearchPage:
    hits: tuple[WebHit, ...]
    unresponsive_engines: tuple[str, ...]


@dataclass(frozen=True)
class PageProbe:
    kind: Literal["html", "pdf", "text"]
    words: int | None = None
    pages: int | None = None
    size_bytes: int | None = None
    # Ссылки на файлы учебных форматов: у «страницы со ссылками» их много, а текста мало.
    file_links: int = 0
    excerpt: str = ""

    @property
    def reading_minutes(self) -> int | None:
        return max(1, round(self.words / WORDS_PER_MINUTE)) if self.words else None


def _clean(text: object, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _duration(value: object) -> str | None:
    """Длительность видео: одни движки дают «40:46», другие — секунды («720.0»)."""
    text = _clean(value, 20)
    try:
        seconds = round(float(text))
    except ValueError:
        return text or None
    if seconds <= 0:
        return None
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def parse_search_response(payload: dict[str, object], limit: int) -> WebSearchPage:
    """Выдача SearXNG в JSON → попадания без пустых и нестраничных адресов."""
    hits: list[WebHit] = []
    for raw in payload.get("results") or []:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "")
        if urlsplit(url).scheme not in {"http", "https"}:
            continue
        hits.append(WebHit(
            url=url,
            title=_clean(raw.get("title"), 300) or urlsplit(url).netloc,
            snippet=_clean(raw.get("content"), 400),
            engine=str(raw.get("engine") or ""),
            duration=_duration(raw.get("length")),
            author=_clean(raw.get("author"), 120) or None,
        ))
        if len(hits) >= limit:
            break
    unresponsive = tuple(
        str(item[0]) for item in payload.get("unresponsive_engines") or []
        if isinstance(item, list | tuple) and item
    )
    return WebSearchPage(hits=tuple(hits), unresponsive_engines=unresponsive)


def search(
    query: str, *, category: SearchCategory, language: SearchLanguage, limit: int = 8
) -> WebSearchPage:
    params = {
        "q": query,
        "format": "json",
        "categories": category,
        "language": language,
        "safesearch": 1,
    }
    url = f"{settings.searxng_url.rstrip('/')}/search?{urlencode(params)}"
    try:
        with urlopen(Request(url), timeout=SEARCH_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 403:
            raise WebSearchUnavailableError(
                "SearXNG не отдаёт выдачу в JSON: включите формат json в searxng/settings.yml",
                code="web_search_misconfigured",
            ) from error
        raise WebSearchUnavailableError(
            f"Поисковый сервис SearXNG ответил ошибкой {error.code}"
        ) from error
    except (URLError, TimeoutError, OSError, ValueError) as error:
        raise WebSearchUnavailableError(
            "Поисковый сервис SearXNG не отвечает — запустите его: docker compose up -d searxng"
        ) from error
    return parse_search_response(payload, limit)


async def search_many(
    queries: Iterable[tuple[str, SearchCategory, SearchLanguage]], limit: int = 8
) -> list[WebSearchPage]:
    """Все запросы хода параллельно; недоступность сервиса — общая ошибка хода."""
    return list(await asyncio.gather(*(
        asyncio.to_thread(search, query, category=category, language=language, limit=limit)
        for query, category, language in queries
    )))


class _ProbeHtml(_ReadableHtml):
    def __init__(self) -> None:
        super().__init__()
        self.file_links = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        if tag == "a" and any(key == "href" and value and FILE_LINK.search(value)
                              for key, value in attrs):
            self.file_links += 1


def _pdf_pages(data: bytes) -> int | None:
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            return document.page_count
    except (RuntimeError, ValueError):
        return None


def probe_page(url: str) -> PageProbe | None:
    """Объём и начало текста страницы; None, если её не удалось прочитать."""
    try:
        _validate_public_url(url)
        opener = build_opener(_SafeRedirect())
        with opener.open(Request(url, headers=PROBE_HEADERS), timeout=PROBE_TIMEOUT_SECONDS) as r:
            content_type = r.headers.get_content_type()
            declared = int(r.headers.get("Content-Length") or 0) or None
            is_pdf = urlsplit(r.geturl()).path.lower().endswith(".pdf")
            if content_type == "application/pdf" or is_pdf:
                if declared and declared > MAX_PDF_BYTES:
                    return PageProbe(kind="pdf", size_bytes=declared)
                data = r.read(MAX_PDF_BYTES + 1)
                if len(data) > MAX_PDF_BYTES:
                    return PageProbe(kind="pdf", size_bytes=declared or len(data))
                return PageProbe(kind="pdf", pages=_pdf_pages(data), size_bytes=len(data))
            if content_type not in {"text/html", "text/plain"}:
                return None
            raw = r.read(MAX_HTML_BYTES)
            text = raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except (ProjectDomainError, HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
    if content_type == "text/plain":
        body = text.strip()
        return PageProbe(kind="text", words=len(body.split()), excerpt=_clean(body, EXCERPT_CHARS))
    parser = _ProbeHtml()
    parser.feed(text)
    body = parser.text()
    return PageProbe(
        kind="html",
        words=len(body.split()),
        file_links=parser.file_links,
        excerpt=_clean(body, EXCERPT_CHARS),
    )


async def probe_pages(urls: list[str]) -> dict[str, PageProbe]:
    """Прочитать страницы параллельно; не успевшие за общий предел остаются без объёма."""
    if not urls:
        return {}
    tasks = {asyncio.ensure_future(asyncio.to_thread(probe_page, url)): url for url in urls}
    done, pending = await asyncio.wait(tasks, timeout=PROBE_BATCH_SECONDS)
    for task in pending:
        task.cancel()
    result: dict[str, PageProbe] = {}
    for task in done:
        try:
            probe = task.result()
        except Exception:  # сбой одной страницы не должен ронять ход
            log.exception("Page probe failed")
            continue
        if probe is not None:
            result[tasks[task]] = probe
    if pending:
        log.info("Page probes timed out: %d of %d", len(pending), len(urls))
    return result
