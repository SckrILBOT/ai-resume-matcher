"""Провайдеры LLM: Gemini (google-genai), Xiaomi MiMo и GigaChat (chat/completions).

Каждый провайдер возвращает текст JSON, а разбор и проверку схемы делает LLMService.
"""
import asyncio
import json
import logging
import re
import ssl
import time
import uuid
from typing import Protocol, get_args, get_origin

import certifi
import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.config import Settings
from app.schemas.analysis import AnalysisResult

logger = logging.getLogger("llm")

# Ошибки, при которых имеет смысл повторить запрос тому же провайдеру
RETRYABLE_KINDS = {"timeout", "unavailable", "quota", "bad_response"}


class ProviderError(Exception):
    """Ошибка провайдера. kind: timeout | unavailable | quota | billing | config | bad_response."""

    def __init__(self, provider: str, kind: str, message: str = "") -> None:
        super().__init__(f"{provider}: {kind} {message}".strip())
        self.provider = provider
        self.kind = kind

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate_json(self, system: str, prompt: str) -> str: ...


def kind_for_status(status: int | None) -> str:
    if status == 402:
        return "billing"  # нет средств на балансе: повтор не поможет
    if status == 429:
        return "quota"
    if status == 408:
        return "timeout"
    if status is None or status >= 500:
        return "unavailable"
    return "config"  # 400, 401, 403, 404: неверный ключ, модель или регион


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.gemini_model
        self._api_key = settings.gemini_api_key
        self._timeout = settings.llm_timeout_s
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate_json(self, system: str, prompt: str) -> str:
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=AnalysisResult,
                        temperature=0.4,
                    ),
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderError(self.name, "timeout") from exc
        except genai_errors.APIError as exc:
            status = getattr(exc, "code", None)
            raise ProviderError(self.name, kind_for_status(status), f"HTTP {status}") from exc
        if not response.text:
            raise ValueError("empty response")
        return response.text


def extract_json(content: str) -> str:
    """Достаёт JSON-объект из ответа: убирает блоки рассуждений и markdown-обёртку."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    start, end = content.find("{"), content.rfind("}")
    return content[start : end + 1] if start != -1 and end > start else content.strip()


def example_for(model: type[BaseModel]) -> dict:
    """Пример заполненного объекта по Pydantic-модели: поля и типы без синтаксиса JSON Schema."""
    example = {}
    for name, field in model.model_fields.items():
        tp = field.annotation
        if get_origin(tp) is list:
            (item,) = get_args(tp)
            is_model = isinstance(item, type) and issubclass(item, BaseModel)
            example[name] = [example_for(item) if is_model else "строка"]
        elif isinstance(tp, type) and issubclass(tp, BaseModel):
            example[name] = example_for(tp)
        else:
            example[name] = 0 if tp is int else "строка"
    return example


def with_schema(prompt: str) -> str:
    """Для провайдеров без нативной JSON-схемы: формат ответа показывается примером в промпте.

    Пример вместо JSON Schema: часть моделей (например, GigaChat) копирует структуру схемы
    с $defs и properties вместо того, чтобы заполнить поля.
    """
    example = json.dumps(example_for(AnalysisResult), ensure_ascii=False, indent=1)
    return (
        f"{prompt}\n\nОтвет: ТОЛЬКО один JSON-объект без пояснений и без markdown-обёртки, "
        "ровно с такими полями (значения ниже показывают только типы, заполни их по результатам анализа). "
        "Не добавляй ключи $defs, properties или type. Все оценки — целые числа от 0 до 100, "
        f"в bullet_improvements минимум 4 элемента.\n{example}"
    )


def chat_content(resp: httpx.Response) -> str:
    """Текст ответа из формата chat/completions (OpenAI-совместимого)."""
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("unexpected chat/completions response shape") from exc
    if not content:
        raise ValueError("empty response")
    return extract_json(content)


class MimoProvider:
    """Xiaomi MiMo через OpenAI-совместимый /chat/completions.

    Нативной JSON-схемы у MiMo нет (только режим json_object), поэтому схема передаётся
    в промпте, а ответ проверяется Pydantic.
    """

    name = "mimo"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.model = settings.mimo_model
        self._base_url = settings.mimo_base_url.rstrip("/")
        self._api_key = settings.mimo_api_key
        self._timeout = settings.llm_timeout_s
        self._transport = transport

    async def generate_json(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": with_schema(prompt)}],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "api-key": self._api_key}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(f"{self._base_url}/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, "timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, "unavailable", type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise ProviderError(self.name, kind_for_status(resp.status_code), f"HTTP {resp.status_code}")
        return chat_content(resp)


def gigachat_ssl_context(ca_bundle: str) -> ssl.SSLContext:
    """Стандартные корневые сертификаты + сертификат НУЦ Минцифры, которым подписаны серверы GigaChat."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    if ca_bundle:
        ctx.load_verify_locations(cafile=ca_bundle)
    return ctx


class GigaChatProvider:
    """GigaChat (Сбер): OAuth-токен на 30 минут, затем chat/completions.

    Токен кешируется и обновляется заранее. Нативной JSON-схемы нет, схема передаётся в промпте.
    """

    name = "gigachat"
    TOKEN_MARGIN_S = 60

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.model = settings.gigachat_model
        self._auth_key = settings.gigachat_auth_key
        self._scope = settings.gigachat_scope
        self._auth_url = settings.gigachat_auth_url
        self._base_url = settings.gigachat_base_url.rstrip("/")
        self._ca_bundle = settings.gigachat_ca_bundle
        self._timeout = settings.llm_timeout_s
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
        try:
            verify = gigachat_ssl_context(self._ca_bundle)
        except (OSError, ssl.SSLError) as exc:
            raise ProviderError(self.name, "config", "не удалось загрузить GIGACHAT_CA_BUNDLE") from exc
        return httpx.AsyncClient(timeout=self._timeout, verify=verify)

    def _connect_error(self, exc: Exception) -> ProviderError:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            return ProviderError(self.name, "config", "нет сертификата НУЦ Минцифры (GIGACHAT_CA_BUNDLE)")
        return ProviderError(self.name, "unavailable", type(exc).__name__)

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        async with self._lock:
            if self._token and time.time() < self._token_expires_at - self.TOKEN_MARGIN_S:
                return self._token
            headers = {
                "Authorization": f"Basic {self._auth_key}",
                "RqUID": str(uuid.uuid4()),
                "Accept": "application/json",
            }
            resp = await client.post(self._auth_url, data={"scope": self._scope}, headers=headers)
            if resp.status_code >= 400:
                raise ProviderError(self.name, kind_for_status(resp.status_code), f"OAuth HTTP {resp.status_code}")
            try:
                body = resp.json()
                token, expires_at = body["access_token"], float(body["expires_at"])
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderError(self.name, "unavailable", "неожиданный ответ OAuth") from exc
            if expires_at > 1e12:  # миллисекунды
                expires_at /= 1000
            self._token, self._token_expires_at = token, expires_at
            return token

    async def generate_json(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": with_schema(prompt)}],
            "temperature": 0.4,
        }
        try:
            async with self._client() as client:
                token = await self._get_token(client)
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, "timeout") from exc
        except httpx.HTTPError as exc:
            raise self._connect_error(exc) from exc
        if resp.status_code == 401:
            # Токен отозван или истёк раньше срока: следующая попытка получит новый
            self._token = None
            raise ProviderError(self.name, "unavailable", "токен истёк")
        if resp.status_code >= 400:
            raise ProviderError(self.name, kind_for_status(resp.status_code), f"HTTP {resp.status_code}")
        return chat_content(resp)


def build_providers(settings: Settings) -> list[LLMProvider]:
    factories = {"mimo": MimoProvider, "gemini": GeminiProvider, "gigachat": GigaChatProvider}
    return [factories[name](settings) for name in settings.provider_order()]
