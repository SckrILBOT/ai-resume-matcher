import pymupdf as fitz
import pytest

from app.config import Settings
from app.errors import AppError
from app.services.parser_service import (
    extract_pdf_text,
    fetch_job_text,
    html_to_text,
    validate_public_url,
)

SETTINGS = Settings(gemini_api_key="x")


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_html_to_text_strips_scripts():
    html = "<html><body><script>alert(1)</script><style>p{}</style><main><p>Python developer</p></main></body></html>"
    text = html_to_text(html, 1000)
    assert "Python developer" in text
    assert "alert" not in text and "p{}" not in text


async def test_pdf_ok():
    assert "Hello" in await extract_pdf_text(make_pdf("Hello resume"), SETTINGS)


async def test_pdf_without_text_layer():
    with pytest.raises(AppError) as e:
        await extract_pdf_text(make_pdf(""), SETTINGS)
    assert e.value.code == "SCAN_PDF_NO_TEXT"


async def test_not_a_pdf():
    with pytest.raises(AppError) as e:
        await extract_pdf_text(b"hello world", SETTINGS)
    assert e.value.status_code == 415


async def test_pdf_too_large():
    s = Settings(gemini_api_key="x", max_pdf_size_mb=1)
    with pytest.raises(AppError) as e:
        await extract_pdf_text(b"%PDF-" + b"0" * (2 * 1024 * 1024), s)
    assert e.value.status_code == 413


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com", "http://127.0.0.1/admin", "http://localhost:8000", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data"],
)
async def test_ssrf_blocked(url):
    with pytest.raises(AppError) as e:
        await validate_public_url(url)
    assert e.value.code == "BAD_URL"


async def test_fetch_rejects_private_url():
    with pytest.raises(AppError):
        await fetch_job_text("http://192.168.1.1/job", SETTINGS)
