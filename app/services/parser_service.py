import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import pymupdf
import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.errors import AppError

MIN_JOB_CHARS = 300
MAX_REDIRECTS = 3
MAX_HTML_BYTES = 2 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; AIResumeMatcher/1.0)"
_REMOVED_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"]


def normalize_text(text: str, limit: int) -> str:
    text = text.replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:limit]


def _extract_pdf_sync(data: bytes) -> str:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        raise AppError(415, "Не удалось прочитать PDF-файл. Файл повреждён?", "PDF_UNREADABLE") from exc


async def extract_pdf_text(data: bytes, settings: Settings) -> str:
    if len(data) > settings.max_pdf_size_mb * 1024 * 1024:
        raise AppError(413, f"PDF больше {settings.max_pdf_size_mb} МБ", "PDF_TOO_LARGE")
    if not data.lstrip()[:5] == b"%PDF-":
        raise AppError(415, "Файл не является PDF", "NOT_PDF")
    text = normalize_text(await asyncio.to_thread(_extract_pdf_sync, data), settings.max_resume_chars)
    if not text:
        raise AppError(
            422, "Не удалось извлечь текст из PDF. Вставьте резюме текстом.", "SCAN_PDF_NO_TEXT"
        )
    return text


def html_to_text(html: str, limit: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_REMOVED_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    return normalize_text(root.get_text("\n"), limit)


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


async def validate_public_url(url: str) -> None:
    """Защита от SSRF: только http(s) и только публичные адреса."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AppError(400, "Допустимы только ссылки http:// и https://", "BAD_URL")
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise AppError(502, "Не удалось найти сайт по этой ссылке", "URL_UNREACHABLE") from exc
    if not infos or not all(_is_public_ip(info[4][0]) for info in infos):
        raise AppError(400, "Ссылка ведёт на недопустимый адрес", "BAD_URL")


async def fetch_job_text(url: str, settings: Settings) -> str:
    url = url.strip()
    try:
        async with httpx.AsyncClient(
            timeout=settings.url_fetch_timeout_s,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                await validate_public_url(url)
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            break
                        url = urljoin(url, location)
                        continue
                    if resp.status_code >= 400:
                        raise AppError(
                            502, f"Сайт вакансии вернул ошибку {resp.status_code}. Вставьте текст вручную.",
                            "URL_HTTP_ERROR",
                        )
                    body = b""
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_HTML_BYTES:
                            break
                    html = body.decode(resp.encoding or "utf-8", errors="replace")
                    break
            else:
                raise AppError(502, "Слишком много редиректов", "URL_REDIRECTS")
    except httpx.TimeoutException as exc:
        raise AppError(504, "Сайт вакансии не ответил вовремя", "URL_TIMEOUT") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "Не удалось загрузить страницу вакансии", "URL_UNREACHABLE") from exc

    text = html_to_text(html, settings.max_job_chars)
    if len(text) < MIN_JOB_CHARS:
        raise AppError(
            502,
            "Не удалось извлечь текст вакансии (возможно, сайт загружается через JavaScript или блокирует "
            "ботов). Вставьте текст вакансии вручную.",
            "JOB_TEXT_TOO_SHORT",
        )
    return text
