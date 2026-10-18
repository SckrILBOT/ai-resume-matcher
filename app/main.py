import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.demo.demo_data import DEMO_JOB, DEMO_RESUME
from app.errors import AppError
from app.schemas.analysis import AnalysisResult, Tone
from app.services.llm_service import LLMService
from app.services.parser_service import (
    extract_pdf_text,
    fetch_job_text,
    normalize_text,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AI Resume & ATS Matcher", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@lru_cache
def get_llm_service() -> LLMService:
    return LLMService(get_settings())


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"detail": "Некорректные данные запроса", "code": "VALIDATION_ERROR"}
    )


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/api/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return {"status": "ok", "model": settings.gemini_model, "llm_configured": settings.llm_configured}


@app.get("/api/demo")
async def demo() -> dict:
    return {"resume_text": DEMO_RESUME, "job_text": DEMO_JOB}


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze(
    settings: Annotated[Settings, Depends(get_settings)],
    llm: Annotated[LLMService, Depends(get_llm_service)],
    tone: Annotated[str, Form()],
    resume_file: Annotated[UploadFile | None, File()] = None,
    resume_text: Annotated[str, Form()] = "",
    job_text: Annotated[str, Form()] = "",
    job_url: Annotated[str, Form()] = "",
) -> AnalysisResult:
    started = time.perf_counter()

    try:
        tone_enum = Tone(tone)
    except ValueError:
        raise AppError(400, "Неизвестный тон письма", "BAD_TONE")

    has_file = resume_file is not None and bool(resume_file.filename)
    if has_file:
        data = await resume_file.read(settings.max_pdf_size_mb * 1024 * 1024 + 1)
        resume = await extract_pdf_text(data, settings)
    elif resume_text.strip():
        resume = normalize_text(resume_text, settings.max_resume_chars)
    else:
        raise AppError(400, "Загрузите PDF или вставьте текст резюме", "NO_RESUME")

    if job_text.strip():
        job = normalize_text(job_text, settings.max_job_chars)
    elif job_url.strip():
        job = await fetch_job_text(job_url, settings)
    else:
        raise AppError(400, "Вставьте текст вакансии или ссылку на неё", "NO_JOB")

    result = await llm.analyze(resume, job, tone_enum)
    logger.info(
        "analyze ok: resume=%s chars, job=%s chars, %.1fs",
        len(resume), len(job), time.perf_counter() - started,
    )
    return result
