"""
Unit tests for investor PII minimization, prompt sanitization, and consent enforcement.
Addresses Issue #44: Prevent investor PII and portfolio details from entering shared narrative caches or external AI prompts without controls.
"""
from __future__ import annotations

import pytest
from core.prompt_advisor import (
    sanitize_prompt_for_privacy,
    _call_llm_with_retry,
    answer_interactive_query,
)
from core.ai_engine import ProviderError
from core.models import FiduciaryFactsPayload


def test_sanitize_prompt_for_privacy_redacts_all_pii():
    text = (
        "Investor John Doe with PAN ABCDE1234F and email john.doe@investor.com "
        "called from +91 9876543210 regarding Folio No: 12345/678 and Account #9988776655."
    )
    sanitized = sanitize_prompt_for_privacy(text, client_name="John Doe")
    assert "ABCDE1234F" not in sanitized
    assert "john.doe@investor.com" not in sanitized
    assert "9876543210" not in sanitized
    assert "12345/678" not in sanitized
    assert "9988776655" not in sanitized
    assert "John Doe" not in sanitized
    assert "[REDACTED_PAN]" in sanitized
    assert "[REDACTED_EMAIL]" in sanitized
    assert "[REDACTED_PHONE]" in sanitized
    assert "[REDACTED_FOLIO]" in sanitized
    assert "the supplied investor portfolio" in sanitized


def test_call_llm_blocks_without_consent():
    with pytest.raises(ProviderError, match="External AI processing is blocked"):
        _call_llm_with_retry("test prompt", external_processing_consent=False)


def test_call_llm_with_consent_sanitizes_prompt(monkeypatch):
    captured = {}

    def fake_engine_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "Sanitized narrative response"

    import core.prompt_advisor as pa
    monkeypatch.setattr(pa, "_engine_call_llm", fake_engine_call)

    prompt = "Client Ramesh Kumar holding PAN BKZPS1234K with Folio 55443322."
    res = _call_llm_with_retry(
        prompt,
        external_processing_consent=True,
        client_name="Ramesh Kumar",
    )

    assert "BKZPS1234K" not in captured["prompt"]
    assert "55443322" not in captured["prompt"]
    assert "Ramesh Kumar" not in captured["prompt"]
    assert "[REDACTED_PAN]" in captured["prompt"]
    assert "[REDACTED_FOLIO]" in captured["prompt"]
    assert "the supplied investor portfolio" in captured["prompt"]
    assert res == "Sanitized narrative response"
