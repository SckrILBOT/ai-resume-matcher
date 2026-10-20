"""Провайдеры LLM: Gemini (google-genai) и Xiaomi MiMo (OpenAI-совместимый API).

Каждый провайдер возвращает текст JSON, а разбор и проверку схемы делает LLMService.
"""
import asyncio
import json
import logging
import re
from typing import Protocol

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

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
        schema = json.dumps(AnalysisResult.model_json_schema(), ensure_ascii=False)
        user = (
            f"{prompt}\n\nВерни ТОЛЬКО один JSON-объект без пояснений и без markdown-обёртки, "
            f"строго по этой JSON-схеме:\n{schema}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
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
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError("unexpected MiMo response shape") from exc
        if not content:
            raise ValueError("empty response")
        return extract_json(content)


def build_providers(settings: Settings) -> list[LLMProvider]:
    factories = {"mimo": MimoProvider, "gemini": GeminiProvider}
    return [factories[name](settings) for name in settings.provider_order()]
