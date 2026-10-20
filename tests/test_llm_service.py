import json

import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.schemas.analysis import Tone
from app.services.llm_providers import MimoProvider, ProviderError, extract_json
from app.services.llm_service import LLMService

VALID = json.dumps({
    "overall_match_score": 70,
    "category_scores": {"hard_skills_score": 60, "experience_score": 70, "ats_readability_score": 80},
    "executive_summary": "ok",
    "matched_keywords": ["Python"],
    "missing_keywords": ["Redis"],
    "bullet_improvements": [{"original_or_weak_point": "a", "improved_bullet": "b", "why_it_works": "c"}] * 3,
    "cover_letter": "Hi",
})


class FakeProvider:
    def __init__(self, name, outcomes):
        self.name, self.model = name, f"{name}-model"
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate_json(self, system, prompt):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


async def no_sleep(_):
    pass


def service(*providers, attempts=2):
    return LLMService(Settings(llm_attempts=attempts), providers=list(providers), sleep=no_sleep)


async def test_retry_after_transient_error():
    p = FakeProvider("gemini", [ProviderError("gemini", "unavailable"), VALID])
    result = await service(p).analyze("cv", "job", Tone.CONCISE)
    assert result.overall_match_score == 70 and p.calls == 2


async def test_fallback_to_second_provider():
    down = FakeProvider("mimo", [ProviderError("mimo", "unavailable")] * 2)
    backup = FakeProvider("gemini", [VALID])
    result = await service(down, backup).analyze("cv", "job", Tone.CONCISE)
    assert result.overall_match_score == 70 and down.calls == 2 and backup.calls == 1


async def test_config_error_skips_retry_and_falls_back():
    bad_key = FakeProvider("mimo", [ProviderError("mimo", "config")])
    backup = FakeProvider("gemini", [VALID])
    await service(bad_key, backup).analyze("cv", "job", Tone.CONCISE)
    assert bad_key.calls == 1


async def test_billing_error_falls_back_without_retry():
    broke = FakeProvider("mimo", [ProviderError("mimo", "billing")])
    backup = FakeProvider("gemini", [VALID])
    await service(broke, backup).analyze("cv", "job", Tone.CONCISE)
    assert broke.calls == 1 and backup.calls == 1


async def test_invalid_json_then_valid():
    p = FakeProvider("mimo", ["not json", VALID])
    assert (await service(p).analyze("cv", "job", Tone.CONCISE)).overall_match_score == 70


async def test_all_fail_quota_error():
    a = FakeProvider("mimo", [ProviderError("mimo", "quota")] * 2)
    b = FakeProvider("gemini", [ProviderError("gemini", "config")])
    with pytest.raises(AppError) as e:
        await service(a, b).analyze("cv", "job", Tone.CONCISE)
    assert e.value.code == "LLM_QUOTA"


async def test_no_providers():
    with pytest.raises(AppError) as e:
        await service().analyze("cv", "job", Tone.CONCISE)
    assert e.value.code == "LLM_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"gemini_api_key": "g"}, ["gemini"]),
        ({"mimo_api_key": "m"}, ["mimo"]),
        ({"gemini_api_key": "g", "mimo_api_key": "m"}, ["mimo", "gemini"]),
        ({"gemini_api_key": "g", "mimo_api_key": "m", "llm_provider": "gemini"}, ["gemini"]),
        ({}, []),
    ],
)
def test_provider_order(env, expected):
    assert Settings(_env_file=None, **env).provider_order() == expected


def test_extract_json_strips_fences_and_thinking():
    raw = "<think>план {x}</think>\n```json\n{\"a\": 1}\n```"
    assert json.loads(extract_json(raw)) == {"a": 1}


def mimo(handler):
    s = Settings(_env_file=None, mimo_api_key="secret", mimo_model="mimo-test")
    return MimoProvider(s, transport=httpx.MockTransport(handler))


async def test_mimo_request_and_response():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + VALID + "\n```"}}]})

    text = await mimo(handler).generate_json("system", "prompt")
    assert json.loads(text)["overall_match_score"] == 70
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["auth"] == "Bearer secret"
    assert seen["body"]["model"] == "mimo-test"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "overall_match_score" in seen["body"]["messages"][1]["content"]  # схема в промпте


@pytest.mark.parametrize("status, kind", [(429, "quota"), (402, "billing"), (503, "unavailable"), (401, "config")])
async def test_mimo_error_mapping(status, kind):
    with pytest.raises(ProviderError) as e:
        await mimo(lambda r: httpx.Response(status, json={})).generate_json("s", "p")
    assert e.value.kind == kind


# ---------- GigaChat ----------
from app.services.llm_providers import GigaChatProvider  # noqa: E402


def gigachat(handler):
    s = Settings(_env_file=None, gigachat_auth_key="authkey", gigachat_model="GigaChat-test")
    return GigaChatProvider(s, transport=httpx.MockTransport(handler))


def oauth_ok(expires_at):
    return httpx.Response(200, json={"access_token": "tok-1", "expires_at": expires_at})


async def test_gigachat_token_cached_between_calls():
    import time
    calls = {"oauth": 0, "chat": 0}

    def handler(request):
        if "oauth" in str(request.url):
            calls["oauth"] += 1
            assert request.headers["authorization"] == "Basic authkey"
            assert request.headers["rquid"]
            assert b"scope=GIGACHAT_API_PERS" in request.content
            return oauth_ok(int((time.time() + 1800) * 1000))  # миллисекунды
        calls["chat"] += 1
        assert request.headers["authorization"] == "Bearer tok-1"
        assert json.loads(request.content)["model"] == "GigaChat-test"
        return httpx.Response(200, json={"choices": [{"message": {"content": VALID}}]})

    provider = gigachat(handler)
    for _ in range(2):
        assert json.loads(await provider.generate_json("s", "p"))["overall_match_score"] == 70
    assert calls == {"oauth": 1, "chat": 2}


async def test_gigachat_expired_token_refreshed():
    import time
    oauth_calls = 0

    def handler(request):
        nonlocal oauth_calls
        if "oauth" in str(request.url):
            oauth_calls += 1
            return oauth_ok(time.time() + 10)  # истекает раньше запаса в 60 секунд
        return httpx.Response(200, json={"choices": [{"message": {"content": VALID}}]})

    provider = gigachat(handler)
    await provider.generate_json("s", "p")
    await provider.generate_json("s", "p")
    assert oauth_calls == 2


async def test_gigachat_401_drops_token_and_is_retryable():
    def handler(request):
        if "oauth" in str(request.url):
            return oauth_ok(9_999_999_999)
        return httpx.Response(401, json={})

    provider = gigachat(handler)
    with pytest.raises(ProviderError) as e:
        await provider.generate_json("s", "p")
    assert e.value.retryable and provider._token is None


async def test_gigachat_bad_auth_key_is_config_error():
    provider = gigachat(lambda r: httpx.Response(401, json={}))
    with pytest.raises(ProviderError) as e:
        await provider.generate_json("s", "p")
    assert e.value.kind == "config"


def test_gigachat_missing_ca_bundle_is_config_error():
    s = Settings(_env_file=None, gigachat_auth_key="k", gigachat_ca_bundle="certs/nope.pem")
    with pytest.raises(ProviderError) as e:
        GigaChatProvider(s)._client()
    assert e.value.kind == "config"


def test_gigachat_in_provider_order():
    s = Settings(_env_file=None, gemini_api_key="g", gigachat_auth_key="k")
    assert s.provider_order() == ["gemini", "gigachat"]
    assert Settings(_env_file=None, gigachat_auth_key="k", llm_provider="gigachat").provider_order() == ["gigachat"]
