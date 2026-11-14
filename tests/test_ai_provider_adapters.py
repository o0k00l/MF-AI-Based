from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core import ai_engine


def test_requesty_discovery_does_not_inject_primary_model(monkeypatch):
    payload = {"data": [
        {"id": "vendor/actually-available", "input_price": "0", "output_price": "0"},
    ]}
    monkeypatch.setattr(ai_engine, "_read_model_cache", lambda *args: None)
    monkeypatch.setattr(ai_engine, "_http_json", lambda *args, **kwargs: payload)
    monkeypatch.setattr(ai_engine, "_write_model_cache", lambda *args, **kwargs: None)
    assert ai_engine._discover_openai_models("Requesty", "https://example.test/models", "key") == [
        "vendor/actually-available"
    ]


@pytest.mark.parametrize("value", [None, False, True, "", "unknown", "NaN", "Infinity"])
def test_zero_price_requires_explicit_numeric_zero(value):
    assert ai_engine._is_zero_price(value) is False


@pytest.mark.parametrize("value", [0, 0.0, "0", "0.000000"])
def test_zero_price_accepts_explicit_numeric_zero(value):
    assert ai_engine._is_zero_price(value) is True


def test_requesty_discovery_rejects_unknown_pricing(monkeypatch):
    payload = {"data": [{"id": "vendor/unknown-price"}]}
    monkeypatch.setattr(ai_engine, "_read_model_cache", lambda *args: None)
    monkeypatch.setattr(ai_engine, "_http_json", lambda *args, **kwargs: payload)
    with pytest.raises(ai_engine.ProviderError, match="no eligible free"):
        ai_engine._discover_openai_models("Requesty", "https://example.test/models", "key")


def test_openrouter_discovery_uses_only_catalogue_free_models(monkeypatch):
    payload = {"data": [
        {"id": "vendor/free:free", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "vendor/free-label-but-unknown:free", "pricing": {}},
        {"id": "vendor/free-label-but-paid:free", "pricing": {"prompt": "0.01", "completion": "0"}},
        {"id": "vendor/paid", "pricing": {"prompt": "0.01", "completion": "0.02"}},
    ]}
    monkeypatch.setattr(ai_engine, "_read_model_cache", lambda *args: None)
    monkeypatch.setattr(ai_engine, "_http_json", lambda *args, **kwargs: payload)
    monkeypatch.setattr(ai_engine, "_write_model_cache", lambda *args, **kwargs: None)
    assert ai_engine._discover_openai_models("OpenRouter", "https://example.test/models", "key") == [
        "vendor/free:free"
    ]


def test_model_cache_is_key_scoped(monkeypatch, tmp_path):
    cache = tmp_path / "models.json"
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", cache)
    # Write model cache with proper pricing_evidence (required by new _read_model_cache)
    ai_engine._write_model_cache(
        "openrouter", "first-key", ["vendor/model"],
        pricing_evidence={"vendor/model": {"prompt": "0", "completion": "0"}}
    )
    assert ai_engine._read_model_cache("openrouter", "first-key") == ["vendor/model"]
    assert ai_engine._read_model_cache("openrouter", "second-key") is None


def test_openai_request_omits_optional_generation_parameters(monkeypatch):
    monkeypatch.setattr(ai_engine, "external_processing_policy_approved", lambda: True)
    calls = []
    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="READY"))])
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=Completions())
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai_engine, "discover_openrouter_free_models", lambda key, force_refresh=False: ["vendor/model"])
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=Client))
    assert ai_engine._call_openrouter("test", external_processing_consent=True) == "READY"
    assert calls == [{"model": "vendor/model", "messages": [{"role": "user", "content": "test"}]}]


def test_gemini_fails_closed_when_zero_cost_pricing_is_unverifiable():
    with pytest.raises(ai_engine.ProviderError, match="FREE_ONLY"):
        ai_engine._call_gemini("test")


def test_narrative_provider_chain_excludes_gemini(monkeypatch):
    monkeypatch.setattr(ai_engine, "external_processing_policy_approved", lambda: True)
    attempted = []
    def unavailable(prompt, system_prompt="", external_processing_consent=False):
        attempted.append("openrouter")
        raise ai_engine.ProviderError("OpenRouter", "unavailable")
    def requesty(prompt, system_prompt="", external_processing_consent=False):
        attempted.append("requesty")
        return "READY"
    monkeypatch.setattr(ai_engine, "_call_openrouter", unavailable)
    monkeypatch.setattr(ai_engine, "_call_requesty", requesty)
    monkeypatch.setattr(ai_engine, "_get_narrative_cache", lambda: {})
    assert ai_engine.call_llm("test", use_cache=False, external_processing_consent=True) == "READY"
    assert attempted == ["openrouter", "requesty"]


def test_provider_http_error_preserves_status_without_body(monkeypatch):
    monkeypatch.setattr(ai_engine, "external_processing_policy_approved", lambda: True)
    error = ai_engine.ProviderError("OpenRouter", "request failed", status_code=401)
    assert error.status_code == 401
    assert "secret" not in str(error).lower()


@pytest.mark.parametrize("status,expected", [
    (400, False),
    (401, False),
    (402, False),
    (403, False),
    (429, False),
    (404, True),
    (408, True),
    (409, True),
    (500, True),
    (503, True),
    (None, False),
])
def test_retry_policy_is_failure_aware(status, expected):
    error = ai_engine.ProviderError("test", "provider request failed", status_code=status)
    assert ai_engine._should_try_next_model(error) is expected


def test_retry_policy_allows_network_failures_without_http_status():
    error = ai_engine.ProviderError("test", "provider request failed (APIConnectionError)")
    assert ai_engine._should_try_next_model(error) is True


def test_openai_does_not_try_other_models_after_quota_failure(monkeypatch):
    monkeypatch.setattr(ai_engine, "external_processing_policy_approved", lambda: True)
    attempted = []

    class Completions:
        def create(self, **kwargs):
            attempted.append(kwargs["model"])
            raise ai_engine.ProviderError("OpenRouter", "quota exhausted", status_code=429)

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        ai_engine, "discover_openrouter_free_models",
        lambda key, force_refresh=False: ["vendor/model-a", "vendor/model-b", "vendor/model-c"],
    )
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=Client))
    with pytest.raises(ai_engine.ProviderError) as caught:
        ai_engine._call_openrouter("test", external_processing_consent=True)
    assert caught.value.status_code == 429
    assert attempted == ["vendor/model-a"]



@pytest.mark.parametrize("exc,expected_status,expected_code", [
    (SimpleNamespace(code=400, status="INVALID_ARGUMENT"), 400, "INVALID_ARGUMENT"),
    (SimpleNamespace(status_code=403, reason="PERMISSION_DENIED"), 403, "PERMISSION_DENIED"),
    (SimpleNamespace(code=429, status="RESOURCE_EXHAUSTED"), 429, "RESOURCE_EXHAUSTED"),
    (SimpleNamespace(code="INVALID_ARGUMENT", status=""), None, "INVALID_ARGUMENT"),
])
def test_google_exception_diagnostics_are_structured_and_safe(exc, expected_status, expected_code):
    assert ai_engine._exception_http_status(exc) == expected_status
    assert ai_engine._safe_exception_code(exc) == expected_code


def test_google_exception_diagnostics_do_not_expose_free_form_message():
    exc = SimpleNamespace(code=400, status="INVALID_ARGUMENT", message="secret prompt and API key")
    assert ai_engine._safe_exception_code(exc) == "INVALID_ARGUMENT"
    assert "secret" not in (ai_engine._safe_exception_code(exc) or "")


def test_generation_blocks_model_when_live_zero_price_evidence_changes(monkeypatch):
    monkeypatch.setattr(ai_engine, "external_processing_policy_approved", lambda: True)
    attempted = []

    class Completions:
        def create(self, **kwargs):
            attempted.append(kwargs["model"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="READY"))])

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    def discovery(key, force_refresh=False):
        return ["vendor/model"] if not force_refresh else []
    monkeypatch.setattr(ai_engine, "discover_openrouter_free_models", discovery)
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=Client))

    with pytest.raises(ai_engine.ProviderError, match="no longer verified as zero-priced"):
        ai_engine._call_openrouter("test", external_processing_consent=True)
    assert attempted == []


def test_force_refresh_bypasses_stale_cache_even_when_cache_is_readable(monkeypatch):
    fetched = []
    monkeypatch.setattr(
        ai_engine, "_read_model_cache",
        lambda *args: ["vendor/stale-paid-model"],
    )
    monkeypatch.setattr(
        ai_engine, "_http_json",
        lambda *args, **kwargs: fetched.append(args) or {
            "data": [{"id": "vendor/current-free", "input_price": "0", "output_price": "0"}]
        },
    )
    monkeypatch.setattr(ai_engine, "_write_model_cache", lambda *args, **kwargs: None)

    result = ai_engine._discover_openai_models(
        "Requesty", "https://example.test/models", "key", force_refresh=True
    )

    assert result == ["vendor/current-free"]
    assert len(fetched) == 1


def test_gemini_key_never_activates_fallback_when_all_free_providers_fail(monkeypatch):
    monkeypatch.setattr(ai_engine, "external_processing_policy_approved", lambda: True)
    attempted = []
    monkeypatch.setenv("GEMINI_API_KEY", "configured-but-prohibited")
    monkeypatch.setattr(
        ai_engine, "_call_openrouter",
        lambda *args, **kwargs: (_ for _ in ()).throw(ai_engine.ProviderError("OpenRouter", "offline")),
    )
    monkeypatch.setattr(
        ai_engine, "_call_requesty",
        lambda *args, **kwargs: (_ for _ in ()).throw(ai_engine.ProviderError("Requesty", "offline")),
    )
    monkeypatch.setattr(
        ai_engine, "_call_gemini",
        lambda *args, **kwargs: attempted.append("gemini") or "SHOULD_NOT_RUN",
    )
    with pytest.raises(ai_engine.ProviderError, match="All eligible free narrative providers are unavailable"):
        ai_engine.call_llm(
            "test", external_processing_consent=True,
        )
    assert attempted == []



def test_provider_adapter_blocks_direct_call_without_investor_consent(monkeypatch):
    monkeypatch.setattr(ai_engine, "external_processing_policy_approved", lambda: True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        ai_engine, "discover_openrouter_free_models",
        lambda *args, **kwargs: pytest.fail("model discovery must not run"),
    )
    with pytest.raises(ai_engine.ProviderError, match="explicit investor consent"):
        ai_engine._call_openrouter("private prompt")



def test_openai_exception_does_not_preserve_free_form_provider_code():
    error = ai_engine._openai_exception(
        "OpenRouter",
        SimpleNamespace(status_code=400, code="private prompt fragment"),
        "vendor/model",
    )
    assert error.status_code == 400
    assert error.code is None
    assert "private prompt" not in str(error)



def test_openai_exception_discards_pan_shaped_provider_code():
    error = ai_engine._openai_exception(
        "OpenRouter",
        SimpleNamespace(status_code=400, code="ABCDE1234F"),
        "vendor/model",
    )
    assert error.status_code == 400
    assert error.code is None
