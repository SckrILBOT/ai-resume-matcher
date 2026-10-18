from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    max_pdf_size_mb: int = 10
    max_resume_chars: int = 20_000
    max_job_chars: int = 15_000
    url_fetch_timeout_s: float = 10.0
    llm_timeout_s: float = 90.0
    app_env: str = "development"

    @property
    def llm_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
