from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDER_VENDORS = {
    "gemini": "Google",
    "yandex": "Яндекс",
    "deepseek": "через Яндекс",
    "gigachat": "Сбер",
    "mimo": "Xiaomi",
}
# Подсказки для выбора модели на сайте: (особенность, обычное время ответа)
PROVIDER_NOTES = {
    "yandex": ("быстро и аккуратно", "5–15 секунд"),
    "deepseek": ("подробнее, но заметно дольше", "40–90 секунд"),
    "gemini": ("иногда бывает перегружен", "10–30 секунд"),
    "gigachat": ("проще по качеству разбора", "10–20 секунд"),
    "mimo": ("", "10–30 секунд"),
}


def model_label(model: str) -> str:
    """Человекочитаемое имя модели: gemini-3.8-flash -> Gemini 3.8 Flash, yandexgpt-5.1/latest -> YandexGPT 5.1."""
    special = {
        "gigachat": "GigaChat",
        "mimo": "MiMo",
        "yandexgpt": "YandexGPT",
        "deepseek": "DeepSeek",
        "aliceai": "Alice AI",
        "llm": "LLM",
    }
    base = model.split("/")[0]  # yandexgpt-5.1/latest -> yandexgpt-5.1
    return " ".join(special.get(part.lower(), part[:1].upper() + part[1:]) for part in base.split("-"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Цепочка по умолчанию: yandex, gemini, gigachat, mimo. Можно зафиксировать один провайдер.
    llm_provider: str = "auto"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    mimo_api_key: str = ""
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.6-flash"
    # YandexGPT (Yandex AI Studio): API-ключ сервисного аккаунта и идентификатор каталога
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_model: str = "yandexgpt-5.1/latest"  # версия yagpt-5.1-2025-08
    yandex_base_url: str = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    yandex_max_tokens: int = 4000
    # DeepSeek через тот же аккаунт Яндекса: только по выбору пользователя (рассуждает, отвечает дольше)
    deepseek_model: str = "deepseek-v4.1-flash/latest"
    deepseek_max_tokens: int = 8000
    # GigaChat (Сбер): ключ авторизации из личного кабинета, токен получается автоматически
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2-Max"
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

    def _configured(self) -> dict[str, bool]:
        yandex = bool(self.yandex_api_key.strip() and self.yandex_folder_id.strip())
        return {
            "gemini": bool(self.gemini_api_key.strip()),
            "mimo": bool(self.mimo_api_key.strip()),
            "yandex": yandex,
            "deepseek": yandex,
            "gigachat": bool(self.gigachat_auth_key.strip()),
        }

    def provider_order(self) -> list[str]:
        """Автоматическая цепочка: первый основной, остальные резервные. DeepSeek сюда не входит."""
        configured = self._configured()
        chain = ["yandex", "gemini", "gigachat", "mimo"]
        choice = self.llm_provider.strip().lower()
        preferred = [choice] if choice in configured else chain
        return [name for name in preferred if configured[name]]

    def optional_providers(self) -> list[str]:
        """Модели, доступные только по выбору пользователя."""
        return ["deepseek"] if self._configured()["deepseek"] else []

    def model_for(self, provider: str) -> str:
        models = {
            "mimo": self.mimo_model,
            "gigachat": self.gigachat_model,
            "yandex": self.yandex_model,
            "deepseek": self.deepseek_model,
        }
        return models.get(provider, self.gemini_model)

    def models_info(self) -> list[dict]:
        """Все модели, которые можно выбрать на сайте. Первая используется по умолчанию."""
        chain = self.provider_order()
        info = []
        for name in [*chain, *self.optional_providers()]:
            note, eta = PROVIDER_NOTES.get(name, ("", ""))
            if name == chain[0] if chain else False:
                role = "по умолчанию"
            elif name in chain:
                role = "резервная"
            else:
                role = "по выбору"
            info.append(
                {
                    "provider": name,
                    "vendor": PROVIDER_VENDORS[name],
                    "model": self.model_for(name),
                    "label": model_label(self.model_for(name)),
                    "role": role,
                    "note": note,
                    "eta": eta,
                }
            )
        return info

    @property
    def llm_configured(self) -> bool:
        return bool(self.provider_order())


@lru_cache
def get_settings() -> Settings:
    return Settings()
