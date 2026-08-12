import html
import ipaddress
import re
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.projects.errors import ProjectDomainError

MAX_REMOTE_BYTES = 10 * 1024 * 1024


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProjectDomainError(
            "Введите публичный URL с http:// или https://",
            status=422,
            code="material_url_invalid",
        )
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except OSError as error:
        raise ProjectDomainError(
            "Не удалось найти сервер по этому адресу",
            status=422,
            code="material_url_unreachable",
        ) from error
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise ProjectDomainError(
                "Локальные и служебные адреса нельзя добавлять как материал",
                status=422,
                code="material_url_private",
            )


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ReadableHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.parts: list[str] = []
        self._ignored = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        value = data.strip()
        if not value:
            return
        if self._in_title:
            self.title = f"{self.title} {value}".strip()
        else:
            self.parts.append(value)

    def text(self) -> str:
        value = " ".join(self.parts)
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r" *\n *", "\n", value)
        return re.sub(r"\n{3,}", "\n\n", value).strip()


def fetch_web_page(url: str) -> tuple[str, str, str, datetime]:
    _validate_public_url(url)
    request = Request(url, headers={"User-Agent": "Tentex/0.1 local material snapshot"})
    try:
        with build_opener(_SafeRedirect()).open(request, timeout=15) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain"}:
                raise ProjectDomainError(
                    "По URL нужен текст или веб-страница",
                    status=422,
                    code="material_url_unsupported",
                )
            raw = response.read(MAX_REMOTE_BYTES + 1)
            if len(raw) > MAX_REMOTE_BYTES:
                raise ProjectDomainError(
                    "Снимок страницы больше 10 МБ",
                    status=413,
                    code="material_too_large",
                )
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            final_url = response.geturl()
    except ProjectDomainError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ProjectDomainError(
            "Не удалось получить страницу. Проверьте адрес и доступ к сети.",
            status=422,
            code="material_url_unreachable",
        ) from error

    if content_type == "text/html":
        parser = _ReadableHtml()
        parser.feed(text)
        title = parser.title or urlparse(final_url).hostname or "Веб-страница"
        body = parser.text()
    else:
        title = urlparse(final_url).path.rsplit("/", 1)[-1] or "Веб-страница"
        body = text.strip()
    if not body:
        raise ProjectDomainError(
            "На странице не найден читаемый текст",
            status=422,
            code="material_url_empty",
        )
    captured = datetime.now(UTC).replace(tzinfo=None)
    markdown = f"# {html.unescape(title)}\n\nИсточник: {final_url}\n\n{body}"
    return f"{title}.md", markdown, final_url, captured


def _youtube_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "m.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if not video_id and parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/")[2]
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        raise ProjectDomainError(
            "Введите ссылку на публичное YouTube-видео",
            status=422,
            code="material_youtube_invalid",
        )
    return video_id


def fetch_youtube_transcript(url: str) -> tuple[str, str, str, datetime]:
    video_id = _youtube_id(url)
    try:
        from youtube_transcript_api import IpBlocked, RequestBlocked, YouTubeTranscriptApi

        transcript = YouTubeTranscriptApi().fetch(video_id, languages=["ru", "en"])
    except (IpBlocked, RequestBlocked) as error:
        raise ProjectDomainError(
            "YouTube заблокировал запрос из этой сети. "
            "Повторите из другой сети или загрузите транскрипт текстом.",
            status=503,
            code="material_youtube_network_blocked",
        ) from error
    except Exception as error:
        raise ProjectDomainError(
            "Субтитры недоступны. Проверьте, что видео публичное и у него есть субтитры.",
            status=422,
            code="material_youtube_transcript_unavailable",
        ) from error
    rows = []
    for item in transcript:
        start = float(item.start)
        stamp = f"{int(start // 60):02d}:{int(start % 60):02d}"
        rows.append(f"[{stamp}] {item.text.strip()}")
    if not rows:
        raise ProjectDomainError(
            "В субтитрах нет текста",
            status=422,
            code="material_youtube_transcript_empty",
        )
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    captured = datetime.now(UTC).replace(tzinfo=None)
    markdown = f"# Транскрипт YouTube\n\nИсточник: {canonical}\n\n" + "\n\n".join(rows)
    return f"YouTube {video_id}.md", markdown, canonical, captured
