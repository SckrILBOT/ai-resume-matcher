import json

import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.schemas.analysis import Tone
from app.services.llm_providers import ProviderError, extract_json
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
    assert result.result.overall_match_score == 70 and p.calls == 2


async def test_fallback_to_second_provider():
    down = FakeProvider("yandex", [ProviderError("yandex", "unavailable")] * 2)
    backup = FakeProvider("gemini", [VALID])
    result = await service(down, backup).analyze("cv", "job", Tone.CONCISE)
    # с запасным провайдером повтора нет: сразу переход
    assert result.provider == "gemini" and result.fallback is True
    assert result.result.overall_match_score == 70 and down.calls == 1 and backup.calls == 1


async def test_last_provider_still_retries():
    first = FakeProvider("gemini", [ProviderError("gemini", "unavailable")])
    last = FakeProvider("gigachat", [ProviderError("gigachat", "unavailable"), VALID])
    await service(first, last).analyze("cv", "job", Tone.CONCISE)
    assert first.calls == 1 and last.calls == 2


async def test_config_error_skips_retry_and_falls_back():
    bad_key = FakeProvider("yandex", [ProviderError("yandex", "config")])
    backup = FakeProvider("gemini", [VALID])
    await service(bad_key, backup).analyze("cv", "job", Tone.CONCISE)
    assert bad_key.calls == 1


async def test_billing_error_falls_back_without_retry():
    broke = FakeProvider("yandex", [ProviderError("yandex", "billing")])
    backup = FakeProvider("gemini", [VALID])
    await service(broke, backup).analyze("cv", "job", Tone.CONCISE)
    assert broke.calls == 1 and backup.calls == 1


async def test_invalid_json_then_valid():
    p = FakeProvider("yandex", ["not json", VALID])
    assert (await service(p).analyze("cv", "job", Tone.CONCISE)).result.overall_match_score == 70


async def test_all_fail_quota_error():
    a = FakeProvider("yandex", [ProviderError("yandex", "quota")] * 2)
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
        ({"gigachat_auth_key": "k"}, ["gigachat"]),
        ({"gemini_api_key": "g", "gigachat_auth_key": "k"}, ["gemini", "gigachat"]),
        ({"gemini_api_key": "g", "gigachat_auth_key": "k", "llm_provider": "gemini"}, ["gemini"]),
        ({}, []),
    ],
)
def test_provider_order(env, expected):
    assert Settings(_env_file=None, **env).provider_order() == expected


def test_extract_json_strips_fences_and_thinking():
    raw = "<think>план {x}</think>\n```json\n{\"a\": 1}\n```"
    assert json.loads(extract_json(raw)) == {"a": 1}


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


def test_model_labels_and_roles():
    from app.config import model_label
    assert model_label("gemini-3.8-flash") == "Gemini 3.8 Flash"
    assert model_label("GigaChat-2-Max") == "GigaChat 2 Max"
    assert model_label("yandexgpt-5.1/latest") == "YandexGPT 5.1"
    info = Settings(_env_file=None, gemini_api_key="g", gigachat_auth_key="k").models_info()
    assert [(m["label"], m["role"], m["vendor"]) for m in info] == [
        ("Gemini 3.8 Flash", "по умолчанию", "Google"),
        ("GigaChat 2 Max", "резервная", "Сбер"),
    ]


# ---------- YandexGPT ----------
from app.services.llm_providers import YandexProvider  # noqa: E402


def yandex(handler, **over):
    s = Settings(_env_file=None, yandex_api_key="ykey", yandex_folder_id="b1gfolder", **over)
    return YandexProvider(s, transport=httpx.MockTransport(handler))


async def test_yandex_request_and_response():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["folder"] = request.headers["x-folder-id"]
        seen["body"] = json.loads(request.content)
        fenced = "```json\n" + VALID + "\n```"
        reply = {"result": {"alternatives": [{"message": {"role": "assistant", "text": fenced}}]}}
        return httpx.Response(200, json=reply)

    text = await yandex(handler).generate_json("system", "prompt")
    assert json.loads(text)["overall_match_score"] == 70
    assert seen["auth"] == "Api-Key ykey" and seen["folder"] == "b1gfolder"
    body = seen["body"]
    assert body["modelUri"] == "gpt://b1gfolder/yandexgpt-5.1/latest"
    assert body["jsonObject"] is True and body["completionOptions"]["stream"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "overall_match_score" in body["messages"][1]["text"]


async def test_yandex_custom_model_uri():
    seen = {}

    def handler(request):
        seen["uri"] = json.loads(request.content)["modelUri"]
        return httpx.Response(200, json={"result": {"alternatives": [{"message": {"text": VALID}}]}})

    await yandex(handler, yandex_model="aliceai-llm").generate_json("s", "p")
    assert seen["uri"] == "gpt://b1gfolder/aliceai-llm"


@pytest.mark.parametrize("status, kind", [(429, "quota"), (503, "unavailable"), (401, "config"), (403, "config"), (400, "config")])
async def test_yandex_error_mapping(status, kind):
    with pytest.raises(ProviderError) as e:
        await yandex(lambda r: httpx.Response(status, json={})).generate_json("s", "p")
    assert e.value.kind == kind


def test_yandex_is_default_and_deepseek_is_optional():
    s = Settings(_env_file=None, gemini_api_key="g", yandex_api_key="y", yandex_folder_id="f", gigachat_auth_key="k")
    assert s.provider_order() == ["yandex", "gemini", "gigachat"]  # DeepSeek не входит в цепочку
    assert [(m["provider"], m["role"]) for m in s.models_info()] == [
        ("yandex", "по умолчанию"),
        ("gemini", "резервная"),
        ("gigachat", "резервная"),
        ("deepseek", "по выбору"),
    ]
    assert Settings(_env_file=None, gemini_api_key="g").optional_providers() == []


def test_yandex_needs_both_key_and_folder():
    assert Settings(_env_file=None, yandex_api_key="y").provider_order() == []
    assert Settings(_env_file=None, yandex_folder_id="f").provider_order() == []


def test_yandex_labels():
    from app.config import model_label
    assert model_label("yandexgpt-5.1/latest") == "YandexGPT 5.1"
    assert model_label("deepseek-v4.1-flash/latest") == "DeepSeek V4.1 Flash"
    assert model_label("yandexgpt-lite/latest") == "YandexGPT Lite"
    assert model_label("aliceai-llm") == "Alice AI LLM"


# ---------- Выбор модели пользователем ----------
from app.services.llm_providers import DeepSeekProvider  # noqa: E402


def selectable(*providers, optional=()):
    return LLMService(Settings(llm_attempts=2), providers=list(providers), optional=list(optional), sleep=no_sleep)


async def test_selected_model_goes_first_and_others_remain_fallback():
    default = FakeProvider("yandex", [VALID])
    deep = FakeProvider("deepseek", [VALID])
    svc = selectable(default, optional=[deep])
    answer = await svc.analyze("cv", "job", Tone.CONCISE, preferred="deepseek")
    assert answer.provider == "deepseek" and answer.fallback is False
    assert default.calls == 0


async def test_selected_model_failure_falls_back_to_default_chain():
    default = FakeProvider("yandex", [VALID])
    deep = FakeProvider("deepseek", [ProviderError("deepseek", "unavailable")])
    answer = await selectable(default, optional=[deep]).analyze("cv", "job", Tone.CONCISE, preferred="deepseek")
    assert answer.provider == "yandex" and answer.fallback is True


async def test_selecting_chain_provider_moves_it_first():
    a, b = FakeProvider("yandex", [VALID]), FakeProvider("gemini", [VALID])
    answer = await selectable(a, b).analyze("cv", "job", Tone.CONCISE, preferred="gemini")
    assert answer.provider == "gemini" and a.calls == 0


async def test_unknown_model_is_rejected():
    with pytest.raises(AppError) as e:
        await selectable(FakeProvider("yandex", [VALID])).analyze("cv", "job", Tone.CONCISE, preferred="gpt-9")
    assert e.value.code == "BAD_MODEL"


async def test_deepseek_uses_own_model_and_bigger_token_limit():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": {"alternatives": [{"message": {"text": VALID}}]}})

    s = Settings(_env_file=None, yandex_api_key="k", yandex_folder_id="b1gx")
    await DeepSeekProvider(s, transport=httpx.MockTransport(handler)).generate_json("s", "p")
    assert seen["body"]["modelUri"] == "gpt://b1gx/deepseek-v4.1-flash/latest"
    assert seen["body"]["completionOptions"]["maxTokens"] == "8000"
