"""Regression tests for the binding free-only provider policy."""

import pytest

from core import ai_engine


def test_gemini_is_disabled_without_authoritative_zero_price_evidence():
    with pytest.raises(ai_engine.ProviderError, match="disabled by FREE_ONLY"):
        ai_engine._call_gemini("hello")


def test_narrative_provider_chain_never_attempts_gemini(monkeypatch):
    attempted = []

    def unavailable(name):
        def call(*args, **kwargs):
            attempted.append(name)
            raise ai_engine.ProviderError(name, "temporarily unavailable")
        return call

    monkeypatch.setattr(ai_engine, "_call_openrouter", unavailable("OpenRouter"))
    monkeypatch.setattr(ai_engine, "_call_requesty", unavailable("Requesty"))
    monkeypatch.setattr(ai_engine, "_call_gemini", unavailable("Gemini"))
    monkeypatch.setattr(ai_engine, "_get_narrative_cache", lambda: {})

    with pytest.raises(RuntimeError, match="All configured AI providers failed"):
        ai_engine.call_llm("prompt", use_cache=False)

    assert attempted == ["OpenRouter", "Requesty"]
