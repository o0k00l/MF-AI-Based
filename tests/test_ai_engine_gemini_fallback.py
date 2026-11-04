"""Tests for the authorized Gemini provider fallback."""
import sys
import types

import pytest

from core import ai_engine


def test_gemini_requires_explicit_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ai_engine.ProviderError, match="GEMINI_API_KEY is not configured"):
        ai_engine._call_gemini("hello")


def test_gemini_discovers_supported_models_and_generates(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = []

    class Models:
        def list(self):
            return [
                types.SimpleNamespace(name="models/gemini-test", supported_actions=["generateContent"]),
                types.SimpleNamespace(name="models/text-embedding-test", supported_actions=["embedContent"]),
                types.SimpleNamespace(name="models/gemini-no-generation", supported_actions=["countTokens"]),
            ]

        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(text="  grounded narrative  ")

    class Client:
        def __init__(self, *, api_key):
            assert api_key == "test-key"
            self.models = Models()

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    google = types.ModuleType("google")
    google.__path__ = []
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)

    result = ai_engine._call_gemini("summarize", system_prompt="Use supplied data only")

    assert result == "grounded narrative"
    assert calls == [{
        "model": "gemini-test",
        "contents": "summarize",
        "config": {"system_instruction": "Use supplied data only"},
    }]


def test_gemini_is_last_provider_fallback(monkeypatch):
    attempted = []

    def fail(name):
        def _call(*args, **kwargs):
            attempted.append(name)
            raise ai_engine.ProviderError(name, "temporarily unavailable")
        return _call

    def gemini(*args, **kwargs):
        attempted.append("Gemini")
        return "fallback response"

    monkeypatch.setattr(ai_engine, "_call_openrouter", fail("OpenRouter"))
    monkeypatch.setattr(ai_engine, "_call_requesty", fail("Requesty"))
    monkeypatch.setattr(ai_engine, "_call_gemini", gemini)

    result = ai_engine.call_llm("prompt", use_cache=False)

    assert result == "fallback response"
    assert attempted == ["OpenRouter", "Requesty", "Gemini"]
