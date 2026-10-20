from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Выбор провайдера: auto (MiMo, Gemini, GigaChat по очереди), gemini, mimo или gigachat
    llm_provider: str = "auto"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    mimo_api_key: str = ""
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.6-flash"
    # GigaChat (Сбер): ключ авторизации из личного кабинета, токен получается автоматически
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    # api.giga.chat из документации не отвечал при проверке; этот адрес работает
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    # Путь к сертификату НУЦ Минцифры (Russian Trusted Root CA) в формате PEM
    gigachat_ca_bundle: str = "certs/russian_trusted_root_ca.pem"

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
        configured = {
            "gemini": bool(self.gemini_api_key.strip()),
            "mimo": bool(self.mimo_api_key.strip()),
            "gigachat": bool(self.gigachat_auth_key.strip()),
        }
        auto = ["mimo", "gemini", "gigachat"]
        choice = self.llm_provider.strip().lower()
        preferred = [choice] if choice in configured else auto
        return [name for name in preferred if configured[name]]

    def model_for(self, provider: str) -> str:
        return {"mimo": self.mimo_model, "gigachat": self.gigachat_model}.get(provider, self.gemini_model)

    @property
    def llm_configured(self) -> bool:
        return bool(self.provider_order())


@lru_cache
def get_settings() -> Settings:
    return Settings()
