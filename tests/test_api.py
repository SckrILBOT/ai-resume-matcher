import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_llm_service
from app.schemas.analysis import AnalysisResult
from app.services.llm_service import LLMAnswer

FAKE = AnalysisResult(
    overall_match_score=82,
    category_scores={"hard_skills_score": 80, "experience_score": 75, "ats_readability_score": 90},
    executive_summary="Сильный кандидат.",
    matched_keywords=["Python", "FastAPI"],
    missing_keywords=["Redis"],
    bullet_improvements=[{"original_or_weak_point": "a", "improved_bullet": "b", "why_it_works": "c"}] * 4,
    cover_letter="Здравствуйте!",
)


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def analyze(self, resume, job, tone):
        self.calls.append((resume, job, tone))
        return LLMAnswer(FAKE, "gigachat", "GigaChat-2-Max", fallback=True)


@pytest.fixture
def llm():
    fake = FakeLLM()
    app.dependency_overrides[get_llm_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def pdf_bytes(text="Python developer resume"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_index_and_health(client):
    assert client.get("/").status_code == 200
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and "api_key" not in body


def test_demo(client):
    data = client.get("/api/demo").json()
    assert data["resume_text"] and data["job_text"]


def test_analyze_text(client, llm):
    r = client.post("/api/analyze", data={"resume_text": "cv", "job_text": "job", "tone": "Краткий и по делу"})
    assert r.status_code == 200
    assert r.json()["overall_match_score"] == 82
    assert r.json()["llm"] == {"provider": "gigachat", "vendor": "Сбер", "model": "GigaChat-2-Max", "label": "GigaChat 2 Max", "fallback": True}
    assert llm.calls


def test_analyze_pdf(client, llm):
    r = client.post(
        "/api/analyze",
        files={"resume_file": ("cv.pdf", pdf_bytes(), "application/pdf")},
        data={"job_text": "job", "tone": "Профессиональный"},
    )
    assert r.status_code == 200
    assert "Python developer" in llm.calls[0][0]


def test_no_resume(client, llm):
    r = client.post("/api/analyze", data={"job_text": "job", "tone": "Профессиональный"})
    assert r.status_code == 400 and r.json()["code"] == "NO_RESUME"


def test_no_job(client, llm):
    r = client.post("/api/analyze", data={"resume_text": "cv", "tone": "Профессиональный"})
    assert r.status_code == 400 and r.json()["code"] == "NO_JOB"


def test_bad_tone(client, llm):
    r = client.post("/api/analyze", data={"resume_text": "cv", "job_text": "j", "tone": "Грубый"})
    assert r.status_code == 400 and r.json()["code"] == "BAD_TONE"


def test_fake_pdf(client, llm):
    r = client.post(
        "/api/analyze",
        files={"resume_file": ("cv.pdf", b"not a pdf", "application/pdf")},
        data={"job_text": "job", "tone": "Профессиональный"},
    )
    assert r.status_code == 415


def test_private_url_rejected(client, llm):
    r = client.post("/api/analyze", data={"resume_text": "cv", "job_url": "http://127.0.0.1/x", "tone": "Профессиональный"})
    assert r.status_code == 400 and r.json()["code"] == "BAD_URL"


def test_missing_tone_is_unified_error(client, llm):
    r = client.post("/api/analyze", data={"resume_text": "cv", "job_text": "j"})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
