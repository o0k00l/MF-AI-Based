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
    monkeypatch.setenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", "true")
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
    monkeypatch.setenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", "true")
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


def test_external_narrative_redacts_all_portfolio_identifiers_and_numeric_facts(monkeypatch):
    from types import SimpleNamespace
    from core import prompt_advisor

    facts = SimpleNamespace(
        client_name="CANARY INVESTOR NAME",
        holdings=[
            SimpleNamespace(
                fund_name="CANARY SCHEME NAME",
                scheme_name="CANARY SCHEME NAME",
                folio="CANARY-FOLIO-7788",
                fund_id="CANARY-FUND-ID",
                scheme_id="CANARY-SCHEME-ID",
                isin="INF000CANARY01",
                account_id="CANARY-ACCOUNT-ID",
            )
        ],
        thematic_exposures=[
            SimpleNamespace(
                theme_name="CANARY THEME",
                key_underlying_holdings=["CANARY STOCK"],
            )
        ],
        deterministic_sip_plan=SimpleNamespace(
            items=[SimpleNamespace(scheme_name="CANARY SIP DESTINATION")]
        ),
        deterministic_lumpsum_plan=SimpleNamespace(
            tranches=[SimpleNamespace(scheme_name="CANARY LUMPSUM DESTINATION")]
        ),
    )

    identifiers = prompt_advisor._sensitive_identifiers_from_facts(facts)
    expected = {
        "CANARY INVESTOR NAME",
        "CANARY SCHEME NAME",
        "CANARY-FOLIO-7788",
        "CANARY-FUND-ID",
        "CANARY-SCHEME-ID",
        "INF000CANARY01",
        "CANARY-ACCOUNT-ID",
        "CANARY THEME",
        "CANARY STOCK",
        "CANARY SIP DESTINATION",
        "CANARY LUMPSUM DESTINATION",
    }
    assert expected.issubset(set(identifiers))

    captured = {}
    monkeypatch.setattr(
        prompt_advisor,
        "_engine_call_llm",
        lambda prompt, **kwargs: captured.update({"prompt": prompt, "kwargs": kwargs}) or "generic narrative",
    )
    prompt_advisor._call_llm_with_retry(
        "Investor CANARY INVESTOR NAME owns CANARY SCHEME NAME, "
        "folio CANARY-FOLIO-7788, ISIN INF000CANARY01 and CANARY STOCK. "
        "Portfolio value INR 1,234,567.89, return 14.75%, age 42, horizon 2031.",
        external_processing_consent=True,
        client_name="CANARY INVESTOR NAME",
        sensitive_identifiers=identifiers,
    )

    outbound = captured["prompt"]
    for canary in expected:
        assert canary not in outbound
    for numeric_detail in ("1,234,567.89", "14.75", "42", "2031"):
        assert numeric_detail not in outbound
    assert "[REDACTED_NUMERIC_DETAIL]" in outbound
    assert captured["kwargs"]["use_cache"] is False


def test_numeric_redaction_covers_percentages_and_unlabelled_values():
    from core.prompt_advisor import sanitize_prompt_for_privacy

    sanitized = sanitize_prompt_for_privacy(
        "Return 18.25%, age 37, horizon 2034, NAV 125.60 and units 900."
    )

    for value in ("18.25", "37", "2034", "125.60", "900"):
        assert value not in sanitized
    assert sanitized.count("[REDACTED_NUMERIC_DETAIL]") == 5



def test_external_ai_requires_provider_policy_approval_even_with_investor_consent(monkeypatch):
    called = []
    monkeypatch.delenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", raising=False)
    monkeypatch.setattr(ai_engine, "_call_openrouter", lambda *a, **k: called.append("openrouter") or "must not run")
    monkeypatch.setattr(ai_engine, "_call_requesty", lambda *a, **k: called.append("requesty") or "must not run")

    with pytest.raises(ai_engine.ProviderError, match="provider data-use and retention review"):
        ai_engine.call_llm("synthetic minimized prompt", external_processing_consent=True)
    assert called == []


def test_provider_policy_approval_requires_explicit_true_value(monkeypatch):
    for value in ("", "false", "1 ", "approved", "yes-no"):
        monkeypatch.setenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", value)
        assert ai_engine.external_processing_policy_approved() is (value.strip().lower() in {"1", "true", "yes"})



def test_legacy_plaintext_narrative_cache_is_removed(tmp_path):
    legacy_cache = tmp_path / "cache" / "narrative_cache.json"
    legacy_cache.parent.mkdir(parents=True)
    legacy_cache.write_text('{"sample":"CANARY"}', encoding="utf-8")

    assert ai_engine._purge_legacy_narrative_cache(legacy_cache) is True
    assert not legacy_cache.exists()


def test_provider_call_fails_closed_if_legacy_narrative_cache_cannot_be_removed(monkeypatch):
    monkeypatch.setenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", "true")
    monkeypatch.setattr(ai_engine, "_purge_legacy_narrative_cache", lambda path=None: False)
    monkeypatch.setattr(ai_engine, "_call_openrouter", lambda *a, **k: pytest.fail("provider must not run"))
    monkeypatch.setattr(ai_engine, "_call_requesty", lambda *a, **k: pytest.fail("provider must not run"))

    with pytest.raises(ai_engine.ProviderError, match="legacy plaintext narrative cache"):
        ai_engine.call_llm("synthetic minimized prompt", external_processing_consent=True)



def test_legacy_cache_purge_refuses_to_follow_cache_directory_symlink(tmp_path, monkeypatch):
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    legacy = outside / "narrative_cache.json"
    legacy.write_text('{"sample":"CANARY"}', encoding="utf-8")
    linked_cache_dir = project_root / "cache"
    linked_cache_dir.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(ai_engine, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        ai_engine, "LEGACY_NARRATIVE_CACHE_FILE",
        linked_cache_dir / "narrative_cache.json",
    )

    assert ai_engine._purge_legacy_narrative_cache() is False
    assert legacy.exists()



def test_direct_provider_adapter_requires_both_privacy_gates(monkeypatch):
    monkeypatch.setenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", "true")
    with pytest.raises(ai_engine.ProviderError, match="explicit investor consent"):
        ai_engine._call_openai_compatible(
            "OpenRouter", ai_engine.OPENROUTER_BASE_URL, "synthetic prompt",
            external_processing_consent=False,
        )

    monkeypatch.delenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED")
    with pytest.raises(ai_engine.ProviderError, match="provider privacy approval"):
        ai_engine._call_openai_compatible(
            "OpenRouter", ai_engine.OPENROUTER_BASE_URL, "synthetic prompt",
            external_processing_consent=True,
        )



def test_online_scheme_query_cache_is_memory_only_and_legacy_file_is_purged(tmp_path, monkeypatch):
    import services.ai_fund_classifier as classifier

    monkeypatch.setenv("MF_ENGINE_DATA_DIR", str(tmp_path))
    legacy = tmp_path / "online_fund_lookthrough.json"
    legacy.write_text('{"Synthetic Public Scheme": {"category": "Equity"}}', encoding="utf-8")

    assert classifier._external_lookthrough_cache_file() is None
    assert classifier._purge_legacy_online_lookthrough_cache() is True
    assert not legacy.exists()
