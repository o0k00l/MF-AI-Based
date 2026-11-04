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
    monkeypatch.setattr(ai_engine, "_http_json", lambda *args: payload)
    monkeypatch.setattr(ai_engine, "_write_model_cache", lambda *args: None)
    assert ai_engine._discover_openai_models("Requesty", "https://example.test/models", "key") == [
        "vendor/actually-available"
    ]


def test_requesty_discovery_rejects_unknown_pricing(monkeypatch):
    payload = {"data": [{"id": "vendor/unknown-price"}]}
    monkeypatch.setattr(ai_engine, "_read_model_cache", lambda *args: None)
    monkeypatch.setattr(ai_engine, "_http_json", lambda *args: payload)
    with pytest.raises(ai_engine.ProviderError, match="no eligible free"):
        ai_engine._discover_openai_models("Requesty", "https://example.test/models", "key")


def test_openrouter_discovery_uses_only_catalogue_free_models(monkeypatch):
    payload = {"data": [
        {"id": "vendor/free:free", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "vendor/paid", "pricing": {"prompt": "0.01", "completion": "0.02"}},
    ]}
    monkeypatch.setattr(ai_engine, "_read_model_cache", lambda *args: None)
    monkeypatch.setattr(ai_engine, "_http_json", lambda *args: payload)
    monkeypatch.setattr(ai_engine, "_write_model_cache", lambda *args: None)
    assert ai_engine._discover_openai_models("OpenRouter", "https://example.test/models", "key") == [
        "vendor/free:free"
    ]


def test_model_cache_is_key_scoped(monkeypatch, tmp_path):
    cache = tmp_path / "models.json"
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", cache)
    ai_engine._write_model_cache("openrouter", "first-key", ["vendor/model"])
    assert ai_engine._read_model_cache("openrouter", "first-key") == ["vendor/model"]
    assert ai_engine._read_model_cache("openrouter", "second-key") is None


def test_openai_request_omits_optional_generation_parameters(monkeypatch):
    calls = []
    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="READY"))])
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=Completions())
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai_engine, "discover_openrouter_free_models", lambda key: ["vendor/model"])
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=Client))
    assert ai_engine._call_openrouter("test") == "READY"
    assert calls == [{"model": "vendor/model", "messages": [{"role": "user", "content": "test"}]}]


def test_gemini_uses_discovered_model_and_no_seed(monkeypatch):
    calls = []
    class Models:
        def list(self):
            return [SimpleNamespace(name="models/gemini-test", supported_actions=["generateContent"])]
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text="READY")
    class Client:
        def __init__(self, **kwargs):
            self.models = Models()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(genai=SimpleNamespace(Client=Client)))
    assert ai_engine._call_gemini("test") == "READY"
    assert calls == [{"model": "gemini-test", "contents": "test", "config": None}]


def test_provider_http_error_preserves_status_without_body():
    error = ai_engine.ProviderError("OpenRouter", "request failed", status_code=401)
    assert error.status_code == 401
    assert "secret" not in str(error).lower()
