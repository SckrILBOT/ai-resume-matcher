from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Выбор провайдера: auto (MiMo, затем Gemini как запасной), gemini или mimo
    llm_provider: str = "auto"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    mimo_api_key: str = ""
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.6-flash"

    llm_timeout_s: float = 90.0
    llm_attempts: int = 2
    llm_retry_delay_s: float = 1.5

    max_pdf_size_mb: int = 10
    max_resume_chars: int = 20_000
    max_job_chars: int = 15_000
    url_fetch_timeout_s: float = 10.0
    app_env: str = "development"

    def provider_order(self) -> list[str]:
        """Провайдеры с заданным ключом в порядке попыток: первый основной, остальные запасные."""
        configured = {"gemini": bool(self.gemini_api_key.strip()), "mimo": bool(self.mimo_api_key.strip())}
        preferred = {"gemini": ["gemini"], "mimo": ["mimo"]}.get(self.llm_provider.strip().lower(), ["mimo", "gemini"])
        return [name for name in preferred if configured[name]]

    def model_for(self, provider: str) -> str:
        return self.mimo_model if provider == "mimo" else self.gemini_model

    @property
    def llm_configured(self) -> bool:
        return bool(self.provider_order())


@lru_cache
def get_settings() -> Settings:
    return Settings()
