import pytest

from core import ai_engine


def test_external_ai_is_blocked_without_explicit_per_request_consent(monkeypatch):
    called = []
    monkeypatch.setattr(ai_engine, "_call_openrouter", lambda *a, **k: called.append("openrouter") or "unsafe")
    monkeypatch.setattr(ai_engine, "_call_requesty", lambda *a, **k: called.append("requesty") or "unsafe")
    monkeypatch.setenv("GEMINI_API_KEY", "configured-but-prohibited")

    with pytest.raises(ai_engine.ProviderError, match="explicit investor consent"):
        ai_engine.call_llm("client financial details", use_cache=True)

    assert called == []


def test_explicit_consent_allows_only_free_provider_and_never_persists_narrative(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", None)
    monkeypatch.setattr(ai_engine, "_call_openrouter", lambda *a, **k: "approved narrative")
    monkeypatch.setattr(ai_engine, "_call_requesty", lambda *a, **k: pytest.fail("fallback should not run"))
    monkeypatch.setattr(ai_engine, "NARRATIVE_CACHE_FILE", tmp_path / "narrative.json")

    result = ai_engine.call_llm(
        "minimized and consented portfolio facts",
        use_cache=True,
        external_processing_consent=True,
    )

    assert result == "approved narrative"
    assert not (tmp_path / "narrative.json").exists()


def test_model_catalogue_cache_is_disabled_without_external_cache_directory(monkeypatch):
    monkeypatch.delenv("MF_AI_CACHE_DIR", raising=False)
    assert ai_engine._external_model_cache_file() is None


def test_model_catalogue_cache_rejects_repository_local_directory(monkeypatch):
    monkeypatch.setenv("MF_AI_CACHE_DIR", str(ai_engine.PROJECT_ROOT / "cache"))
    assert ai_engine._external_model_cache_file() is None


def test_gemini_remains_disabled_even_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "configured-but-prohibited")
    with pytest.raises(ai_engine.ProviderError, match="disabled by FREE_ONLY"):
        ai_engine._call_gemini("prompt")


def test_prompt_advisor_requires_consent_for_external_narrative(monkeypatch):
    from core import prompt_advisor

    called = []
    monkeypatch.setattr(prompt_advisor, "_engine_call_llm", lambda *a, **k: called.append(k) or "draft")

    with pytest.raises(ai_engine.ProviderError, match="explicit investor consent"):
        prompt_advisor._call_llm_with_retry("portfolio facts")
    assert called == []

    result = prompt_advisor._call_llm_with_retry(
        "minimized portfolio facts",
        external_processing_consent=True,
    )
    assert result == "draft"
    assert called[0]["external_processing_consent"] is True
    assert called[0]["use_cache"] is False


def test_prompt_advisor_never_sends_client_name_or_folio_to_external_model(monkeypatch):
    from core import prompt_advisor
    from core.models import (
        FeeBleedAnalysis,
        FiduciaryFactsPayload,
        HoldingItem,
        MandateExecutionState,
        PlanType,
        AssetClass,
    )

    captured = {}
    monkeypatch.setattr(
        prompt_advisor,
        "_engine_call_llm",
        lambda prompt, **kwargs: captured.update({"prompt": prompt, "kwargs": kwargs}) or "draft",
    )
    holding = HoldingItem(
        fund_id="scheme-id",
        scheme="Confidential Scheme",
        fund_name="Confidential Scheme",
        folio="CLIENT-FOLIO-SECRET",
        is_direct=False,
        plan=PlanType.REGULAR,
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=100.0,
        nav=1000.0,
    )
    facts = FiduciaryFactsPayload.model_construct(
        client_name="CLIENT-NAME-SECRET",
        client_age=None,
        horizon_years=10,
        risk_tier_name=None,
        total_portfolio_value_inr=100000.0,
        total_invested_value_inr=90000.0,
        total_unrealized_gain_inr=10000.0,
        holdings_count=1,
        fee_bleed=FeeBleedAnalysis(regular_funds_count=1),
        overlap_matrix=[],
        weighted_overlap=[],
        saa_drift=None,
        cash_plan=None,
        monthly_sip_budget_inr=0.0,
        holdings=[holding],
        mandate_state=MandateExecutionState.HOLD_PENDING_TRI_VALIDATION,
        is_execution_authorized=False,
    )

    prompt_advisor.generate_switch_and_consolidation_plan(
        facts,
        external_processing_consent=True,
    )
    assert "CLIENT-NAME-SECRET" not in captured["prompt"]
    assert "CLIENT-FOLIO-SECRET" not in captured["prompt"]
    assert captured["kwargs"]["use_cache"] is False


def test_free_provider_failure_is_controlled_and_never_falls_back_to_gemini(monkeypatch):
    attempted = []
    monkeypatch.setenv("GEMINI_API_KEY", "configured-but-prohibited")
    monkeypatch.setattr(
        ai_engine, "_call_openrouter",
        lambda *a, **k: attempted.append("openrouter") or (_ for _ in ()).throw(
            ai_engine.ProviderError("OpenRouter", "offline")
        ),
    )
    monkeypatch.setattr(
        ai_engine, "_call_requesty",
        lambda *a, **k: attempted.append("requesty") or (_ for _ in ()).throw(
            ai_engine.ProviderError("Requesty", "offline")
        ),
    )
    monkeypatch.setattr(
        ai_engine, "_call_gemini",
        lambda *a, **k: attempted.append("gemini") or "SHOULD_NEVER_RUN",
    )

    with pytest.raises(ai_engine.ProviderError, match="All eligible free narrative providers are unavailable"):
        ai_engine.call_llm(
            "synthetic portfolio test",
            external_processing_consent=True,
        )
    assert attempted == ["openrouter", "requesty"]
