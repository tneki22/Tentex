"""Клиент SearXNG и чтение найденных страниц (`app.materials.web_search`)."""

from email.message import Message
from urllib.error import HTTPError

import pymupdf as fitz
import pytest

from app.config import settings
from app.materials import web_search


def test_search_response_keeps_web_pages_and_video_length() -> None:
    page = web_search.parse_search_response(
        {
            "results": [
                {"url": "https://example.org/a", "title": " Лекция  1 ", "content": "Процессы",
                 "engine": "duckduckgo"},
                {"url": "magnet:?xt=urn:btih:abc", "title": "Торрент"},
                {"url": "https://www.youtube.com/watch?v=x", "title": "Видео",
                 "engine": "youtube", "length": "40:46", "author": "Кафедра"},
                {"url": "https://example.org/c", "title": "Лишний"},
            ],
            "unresponsive_engines": [["google", "timeout"], ["wikidata", "timeout"]],
        },
        limit=2,
    )
    assert [hit.url for hit in page.hits] == [
        "https://example.org/a", "https://www.youtube.com/watch?v=x",
    ]
    assert page.hits[0].title == "Лекция 1"
    assert page.hits[0].duration is None
    assert (page.hits[1].duration, page.hits[1].author) == ("40:46", "Кафедра")
    assert page.unresponsive_engines == ("google", "wikidata")


def test_video_length_in_seconds_becomes_clock_time() -> None:
    page = web_search.parse_search_response(
        {"results": [
            {"url": "https://a.example/v", "title": "A", "length": "720.0"},
            {"url": "https://b.example/v", "title": "B", "length": 3182},
            {"url": "https://c.example/v", "title": "C", "length": "1:02:33"},
            {"url": "https://d.example/v", "title": "D", "length": "0"},
        ]},
        limit=10,
    )
    assert [hit.duration for hit in page.hits] == ["12:00", "53:02", "1:02:33", None]


def test_search_reports_unreachable_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "searxng_url", "http://127.0.0.1:9")
    with pytest.raises(web_search.WebSearchUnavailableError) as caught:
        web_search.search("процессы", category="general", language="ru")
    assert caught.value.code == "web_search_unavailable"
    assert caught.value.status == 503


def test_search_reports_disabled_json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise HTTPError("http://searxng/search", 403, "Forbidden", Message(), None)

    monkeypatch.setattr(web_search, "urlopen", forbidden)
    with pytest.raises(web_search.WebSearchUnavailableError) as caught:
        web_search.search("процессы", category="general", language="ru")
    assert caught.value.code == "web_search_misconfigured"


class _Response:
    def __init__(self, body: bytes, content_type: str, url: str) -> None:
        self._body = body
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _serve(monkeypatch: pytest.MonkeyPatch, response: _Response) -> None:
    class Opener:
        def open(self, *_args: object, **_kwargs: object) -> _Response:
            return response

    monkeypatch.setattr(web_search, "_validate_public_url", lambda _url: None)
    monkeypatch.setattr(web_search, "build_opener", lambda *_handlers: Opener())


def test_probe_counts_words_and_links_to_files(monkeypatch: pytest.MonkeyPatch) -> None:
    words = " ".join(["слово"] * 360)
    html = (
        "<html><head><title>Конспект</title><script>var x = 1;</script></head><body>"
        f"<p>{words}</p><a href='/files/os.pdf'>PDF</a><a href='/lec2.DJVU?dl=1'>DJVU</a>"
        "<a href='/about'>О сайте</a></body></html>"
    ).encode()
    _serve(monkeypatch, _Response(html, "text/html; charset=utf-8", "https://example.org/n"))
    probe = web_search.probe_page("https://example.org/n")
    assert probe is not None
    assert probe.kind == "html"
    assert probe.words == 364  # 360 слов текста и подписи трёх ссылок
    assert probe.reading_minutes == 2
    assert probe.file_links == 2
    assert probe.excerpt.startswith("слово слово")


def test_probe_counts_pdf_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    document = fitz.open()
    for _ in range(3):
        document.new_page()
    body = document.tobytes()
    _serve(monkeypatch, _Response(body, "application/pdf", "https://example.org/book.pdf"))
    probe = web_search.probe_page("https://example.org/book.pdf")
    assert probe is not None
    assert (probe.kind, probe.pages, probe.size_bytes) == ("pdf", 3, len(body))


def test_probe_skips_private_addresses() -> None:
    assert web_search.probe_page("http://127.0.0.1/admin") is None
