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



def test_interactive_fallback_withholds_untrusted_question_and_chat_history(monkeypatch):
    from types import SimpleNamespace
    import core.prompt_advisor as pa

    captured = {}
    monkeypatch.setattr(
        pa,
        "_engine_call_llm",
        lambda prompt, **kwargs: captured.update({"prompt": prompt}) or "Generic response",
    )
    facts = SimpleNamespace(
        client_name="Synthetic Investor",
        holdings=[],
        total_portfolio_value_inr=100000.0,
        total_invested_value_inr=90000.0,
        total_unrealized_gain_inr=10000.0,
        holdings_count=0,
        xirr_pct=0.12,
        benchmark_xirr_pct=0.10,
        alpha_pct=0.02,
        monthly_sip_budget_inr=10000.0,
        lumpsum_budget_inr=0.0,
        fee_bleed=SimpleNamespace(
            regular_funds_count=0, regular_portfolio_value_inr=0.0,
            annual_bleed_inr=0.0, ten_year_compounded_loss_inr=0.0, details=[],
        ),
        saa_drift=SimpleNamespace(
            current_equity_pct=70.0, current_debt_pct=30.0, current_cash_pct=0.0,
            target_equity_pct=70.0, target_debt_pct=30.0, rebalance_required=False,
        ),
        thematic_exposures=[], overlap_matrix=[], weighted_overlap=[],
        deterministic_sip_plan=None, deterministic_lumpsum_plan=None,
        stability_buffer=None,
    )
    question = "My name is John Doe and my PAN is ABCDE1234F. Explain this portfolio."
    history = [{"role": "user", "content": "Folio 987654321; account 123456789012"}]

    result = answer_interactive_query(
        facts, question, history, external_processing_consent=True,
    )

    assert result == "Generic response"
    assert question not in captured["prompt"]
    assert "John Doe" not in captured["prompt"]
    assert "ABCDE1234F" not in captured["prompt"]
    assert "987654321" not in captured["prompt"]
    assert "123456789012" not in captured["prompt"]
    assert "[WITHHELD" in captured["prompt"]
    assert "CONVERSATION HISTORY:\n\n" in captured["prompt"]
