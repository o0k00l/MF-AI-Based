"""
Tests for Issue #44: End-to-end prompt minimization and provider-path privacy audit.

Acceptance criteria:
- No client name, folio/account identifier, bank account, IFSC, Aadhaar, or unnecessary identifying detail is included in an outbound prompt.
- Outbound interactive query prompts exclude granular individual scheme valuations, invested amounts, and gains.
- External transmission is blocked across all services unless explicit per-request investor consent is granted.
- Without consent, all services fall back cleanly to local deterministic statutory synthesis without calling the LLM engine.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from types import SimpleNamespace

from core.prompt_advisor import (
    sanitize_prompt_for_privacy,
    answer_interactive_query,
    _call_llm_with_retry,
)
from core.models import PlanType
from services.ai_fund_classifier import (
    classify_fund_with_llm,
    batch_classify_funds_with_llm,
    generate_fiduciary_ai_narrative,
    answer_fiduciary_query,
)
from services.cgs_parser import evaluate_tax_harvesting_strategy
from services.goal_planner import evaluate_goal_scenarios_with_ai
from services.risk_profiler import predict_risk_tier_from_portfolio


def test_sanitize_prompt_for_privacy_redacts_comprehensive_pii():
    text = (
        "Client Rajesh Sharma with Aadhaar 1234 5678 9012, PAN ABCDE1234F, "
        "email rajesh.sharma@example.co.in, phone +91 9876543210, "
        "holding HDFC Bank Account 12345678901234 with IFSC HDFC0001234, "
        "under Folio #98765432/10."
    )
    sanitized = sanitize_prompt_for_privacy(text, client_name="Rajesh Sharma")

    assert "Rajesh Sharma" not in sanitized
    assert "1234 5678 9012" not in sanitized
    assert "ABCDE1234F" not in sanitized
    assert "rajesh.sharma@example.co.in" not in sanitized
    assert "9876543210" not in sanitized
    assert "12345678901234" not in sanitized
    assert "HDFC0001234" not in sanitized
    assert "98765432/10" not in sanitized

    assert "[REDACTED_AADHAAR]" in sanitized
    assert "[REDACTED_PAN]" in sanitized
    assert "[REDACTED_EMAIL]" in sanitized
    assert "[REDACTED_PHONE]" in sanitized
    assert "[REDACTED_ACCOUNT]" in sanitized
    assert "[REDACTED_IFSC]" in sanitized
    assert "[REDACTED_FOLIO]" in sanitized
    assert "the supplied investor portfolio" in sanitized


def test_interactive_query_prompt_minimization(monkeypatch):
    captured = {}

    def fake_engine_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "Fiduciary response"

    import core.prompt_advisor as pa
    monkeypatch.setattr(pa, "_engine_call_llm", fake_engine_call)

    holding1 = SimpleNamespace(
        fund_name="HDFC Top 100 Fund",
        plan=PlanType.DIRECT,
        current_value_inr=500000.0,
        invested_value_inr=350000.0,
    )
    holding2 = SimpleNamespace(
        fund_name="SBI Small Cap Fund",
        plan=PlanType.REGULAR,
        current_value_inr=500000.0,
        invested_value_inr=400000.0,
    )

    facts = SimpleNamespace(
        client_name="Vikram Seth",
        holdings=[holding1, holding2],
        holdings_count=2,
        total_portfolio_value_inr=1000000.0,
        total_invested_value_inr=750000.0,
        total_unrealized_gain_inr=250000.0,
        xirr_pct=0.145,
        benchmark_xirr_pct=0.120,
        alpha_pct=2.5,
        fee_bleed=SimpleNamespace(
            regular_funds_count=1,
            regular_portfolio_value_inr=500000.0,
            annual_bleed_inr=4500.0,
            ten_year_compounded_loss_inr=72000.0,
        ),
        saa_drift=SimpleNamespace(
            current_equity_pct=75.0,
            current_debt_pct=25.0,
            current_cash_pct=0.0,
            target_equity_pct=70.0,
            target_debt_pct=30.0,
        ),
        monthly_sip_budget_inr=25000.0,
        lumpsum_budget_inr=100000.0,
        stability_buffer=None,
    )

    response = answer_interactive_query(
        facts,
        "What is my asset allocation?",
        chat_history=[{
            "role": "user",
            "content": "Prior private note CANARY_HISTORY_42 and INR 987,654.32",
        }],
        external_processing_consent=True,
    )

    outbound_prompt = captured["prompt"]
    # Client name must be redacted
    assert "Vikram Seth" not in outbound_prompt
    # Exact scheme names and all rupee balances are removed before provider calls.
    assert "HDFC Top 100 Fund" not in outbound_prompt
    assert "SBI Small Cap Fund" not in outbound_prompt
    assert "INR 500,000" not in outbound_prompt
    assert "INR 350,000" not in outbound_prompt
    assert "INR +150,000" not in outbound_prompt
    assert "INR" not in outbound_prompt
    assert "[REDACTED_FINANCIAL_AMOUNT]" in outbound_prompt
    # Numeric portfolio facts, including percentages, remain local.
    assert "approx 50.0% allocation" not in outbound_prompt
    assert "[REDACTED_NUMERIC_DETAIL]" in outbound_prompt
    assert "CANARY_HISTORY_42" not in outbound_prompt
    assert "987,654.32" not in outbound_prompt


def test_classifier_llm_blocks_without_consent(monkeypatch):
    called = []
    import core.ai_engine as ai
    monkeypatch.setattr(ai, "call_llm", lambda *a, **k: called.append(k) or "output")

    # Single fund classification fails closed to None
    res = classify_fund_with_llm("Parag Parikh Flexi Cap Fund", external_processing_consent=False)
    assert res is None
    assert called == []

    # Batch fund classification fails closed to empty/unclassified
    batch_res = batch_classify_funds_with_llm(["HDFC Top 100", "SBI Small Cap"], external_processing_consent=False)
    assert batch_res == {}
    assert called == []


def test_services_fallback_to_statutory_synthesis_without_consent(monkeypatch):
    called = []
    import core.ai_engine as ai
    monkeypatch.setattr(ai, "call_llm", lambda *a, **k: called.append(k) or "llm_output")

    metrics = {
        "total_value": 1000000.0,
        "eq_pct": 70.0,
        "debt_pct": 30.0,
        "regular_value": 200000.0,
        "regular_pct": 20.0,
        "annual_bleed": 2000.0,
        "compounded_10y_drag": 35000.0,
    }
    funds = [{"scheme": "Fund A", "current_value": 1000000.0, "eq": 70.0, "debt": 30.0}]

    # 1. Narrative report
    narrative = generate_fiduciary_ai_narrative(metrics, funds, external_processing_consent=False)
    assert "Institutional Fiduciary Health Diagnostic" in narrative["content"]
    assert called == []

    # 2. Fiduciary natural language query
    qa = answer_fiduciary_query("How to reduce fee drag?", metrics, funds, external_processing_consent=False)
    assert "Statutory Fiduciary" in qa["source"]
    assert "trail commission" in qa["response"].lower() or "regular" in qa["response"].lower()
    assert called == []

    # 3. Capital gains tax harvesting
    cgs_data = {"summary": {"ltcg_inr": 25000.0, "stcg_inr": 10000.0}}
    tax = evaluate_tax_harvesting_strategy(cgs_data, funds, external_processing_consent=False)
    assert tax["status"] == "ANALYZED"
    assert "Section 112A" in tax["ai_tax_narrative"]
    assert called == []

    # 4. Goal planning stress testing
    goals = [{"name": "Retirement", "cost_today": 5000000.0, "horizon": 15, "required_sip": 20000.0}]
    target_saa = {"equity_pct": 70.0, "debt_pct": 30.0, "cash_pct": 0.0}
    goal_res = evaluate_goal_scenarios_with_ai(goals, 25000.0, target_saa=target_saa, external_processing_consent=False)
    assert goal_res["status"] == "ANALYZED"
    assert "active financial goals require" in goal_res["ai_scenario_narrative"].lower()
    assert called == []

    # 5. Risk tier prediction from portfolio
    risk_res = predict_risk_tier_from_portfolio(funds, external_processing_consent=False)
    assert risk_res["status"] == "PREDICTED"
    assert "revealed investment behavior aligns with" in risk_res["ai_behavioral_rationale"].lower()
    assert called == []

def test_privacy_sanitizer_redacts_rupee_amounts_and_exact_holding_identifiers():
    sanitized = sanitize_prompt_for_privacy(
        "Investor holds HDFC Top 100 Fund in folio FOLIO-88991 with INR 12,34,567.89.",
        sensitive_identifiers=["HDFC Top 100 Fund", "FOLIO-88991"],
    )
    assert "HDFC Top 100 Fund" not in sanitized
    assert "FOLIO-88991" not in sanitized
    assert "12,34,567.89" not in sanitized
    assert "[REDACTED_FINANCIAL_AMOUNT]" in sanitized



def test_live_fiduciary_narrative_minimizes_aggregated_financial_data(monkeypatch):
    from services.ai_fund_classifier import generate_fiduciary_ai_narrative
    import core.ai_engine as ai

    captured = []
    monkeypatch.setattr(
        ai,
        "call_llm",
        lambda prompt, **kwargs: captured.append((prompt, kwargs)) or "A minimized fiduciary narrative response with sufficient detail.",
    )
    metrics = {
        "client_name": "PRIVATE CLIENT NAME",
        "total_value": 9876543.21,
        "eq_pct": 70.0,
        "debt_pct": 30.0,
        "regular_value": 2500000.0,
        "regular_pct": 25.0,
        "annual_bleed": 12500.0,
        "compounded_10y_drag": 175000.0,
        "unique_strategies_count": 4,
        "dual_count": 1,
    }
    funds = [{"scheme": "PRIVATE SCHEME NAME", "folio": "PRIVATE-FOLIO-4455"}]

    result = generate_fiduciary_ai_narrative(
        metrics, funds, use_live_ai=True, external_processing_consent=True
    )

    assert result["source"] == "Live AI Model (Fiduciary Synthesis)"
    assert len(captured) == 1
    prompt, kwargs = captured[0]
    assert "PRIVATE CLIENT NAME" not in prompt
    assert "PRIVATE SCHEME NAME" not in prompt
    assert "PRIVATE-FOLIO-4455" not in prompt
    assert "9,876,543" not in prompt
    assert "INR" not in prompt
    assert "[REDACTED_FINANCIAL_AMOUNT]" in prompt
    assert kwargs["external_processing_consent"] is True
    assert kwargs["use_cache"] is False


def test_live_fiduciary_query_sanitizes_pii_and_never_uses_shared_answer_cache(monkeypatch):
    import core.ai_engine as ai
    from services.ai_fund_classifier import answer_fiduciary_query

    captured = []

    def fake_call_llm(prompt, **kwargs):
        captured.append((prompt, kwargs))
        return "This is a qualitative response based only on minimized supplied facts."

    monkeypatch.setattr(ai, "call_llm", fake_call_llm)
    metrics = {
        "client_name": "PRIVATE CLIENT NAME",
        "account_id": "PRIVATE-ACCOUNT-778899",
        "total_value": 9876543.21,
        "eq_pct": 70.0,
        "debt_pct": 30.0,
        "regular_value": 2500000.0,
        "regular_pct": 25.0,
        "annual_bleed": 12500.0,
        "compounded_10y_drag": 175000.0,
        "dual_count": 1,
    }
    funds = [{
        "scheme": "PRIVATE SCHEME NAME",
        "folio": "PRIVATE-FOLIO-4455",
    }]
    query = (
        "I am PRIVATE CLIENT NAME, PAN ABCDE1234F, email client@example.com, "
        "phone +91 9876543210, account 123456789012 and folio PRIVATE-FOLIO-4455. "
        "Why is my portfolio worth INR 9,876,543.21?"
    )

    kwargs = {
        "use_live_ai": True,
        "external_processing_consent": True,
    }
    first = answer_fiduciary_query(query, metrics, funds, **kwargs)
    second = answer_fiduciary_query(query, metrics, funds, **kwargs)

    assert first["source"] == "Live AI Assistant (Fiduciary Intelligence)"
    assert second["source"] == "Live AI Assistant (Fiduciary Intelligence)"
    assert len(captured) == 2  # investor-specific prompts/responses are never shared-cached
    for prompt, call_kwargs in captured:
        for secret in (
            "PRIVATE CLIENT NAME", "PRIVATE-ACCOUNT-778899", "PRIVATE SCHEME NAME",
            "PRIVATE-FOLIO-4455", "ABCDE1234F", "client@example.com",
            "9876543210", "123456789012",
        ):
            assert secret not in prompt
        assert "9,876,543.21" not in prompt
        assert "INR" not in prompt
        assert "[REDACTED_FINANCIAL_AMOUNT]" in prompt
        assert call_kwargs["external_processing_consent"] is True
        assert call_kwargs["use_cache"] is False


def test_external_scheme_factsheet_lookup_requires_explicit_consent(monkeypatch):
    from services.ai_fund_classifier import (
        _ONLINE_LOOKTHROUGH_CACHE,
        lookup_fund_segment_allocation_online,
    )

    _ONLINE_LOOKTHROUGH_CACHE.pop("Private Investor Scheme 44", None)
    _ONLINE_LOOKTHROUGH_CACHE.pop("Private Investor Scheme", None)
    calls = []

    def fake_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("synthetic network block")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert lookup_fund_segment_allocation_online("Private Investor Scheme 44") is None
    assert calls == []  # no scheme/holding disclosure to a search provider without consent

    monkeypatch.setattr("core.ai_engine.external_processing_policy_approved", lambda: True)
    assert lookup_fund_segment_allocation_online(
        "Private Investor Scheme 44",
        external_processing_consent=True,
    ) is None
    assert calls  # the explicit opt-in is the only path that may contact the external source


def test_cgs_goal_and_risk_ai_paths_minimize_prompts_before_external_calls(monkeypatch):
    import core.ai_engine as ai

    captured = []

    def fake_call_llm(prompt, **kwargs):
        captured.append((prompt, kwargs))
        return "A qualitative narrative based only on minimized portfolio context."

    monkeypatch.setattr(ai, "call_llm", fake_call_llm)

    portfolio = [{
        "scheme": "PRIVATE SCHEME NAME",
        "folio": "PRIVATE-FOLIO-7788",
        "current_value": 900000.0,
        "invested_value": 700000.0,
        "category": "Equity",
        "eq": 100.0,
        "debt": 0.0,
    }]
    cgs_data = {
        "client_name": "PRIVATE CLIENT NAME",
        "summary": {"ltcg_inr": 25000.0, "stcg_inr": 10000.0},
    }
    goals = [{
        "name": "PRIVATE GOAL NAME",
        "goal_name": "PRIVATE GOAL NAME",
        "cost_today": 5000000.0,
        "horizon": 15,
        "required_sip": 20000.0,
    }]
    target_saa = {"equity_pct": 70.0, "debt_pct": 30.0, "cash_pct": 0.0}

    evaluate_tax_harvesting_strategy(
        cgs_data, portfolio, use_live_ai=True, external_processing_consent=True
    )
    evaluate_goal_scenarios_with_ai(
        goals, 25000.0, portfolio=portfolio, target_saa=target_saa,
        use_live_ai=True, external_processing_consent=True,
    )
    predict_risk_tier_from_portfolio(
        portfolio, use_live_ai=True, external_processing_consent=True
    )

    assert len(captured) == 3
    for prompt, kwargs in captured:
        for secret in (
            "PRIVATE CLIENT NAME", "PRIVATE SCHEME NAME", "PRIVATE-FOLIO-7788",
            "PRIVATE GOAL NAME", "25000", "900000", "700000",
        ):
            assert secret not in prompt
        assert "INR" not in prompt
        assert "[REDACTED_FINANCIAL_AMOUNT]" in prompt
        assert kwargs["external_processing_consent"] is True
        assert kwargs["use_cache"] is False


def test_online_scheme_cache_is_never_persisted(tmp_path, monkeypatch):
    from services.ai_fund_classifier import _external_lookthrough_cache_file
    import services.ai_fund_classifier as classifier

    monkeypatch.delenv("MF_ENGINE_DATA_DIR", raising=False)
    assert _external_lookthrough_cache_file() is None

    project_cache = classifier.Path(__file__).resolve().parents[1] / "data" / "cache"
    monkeypatch.setenv("MF_ENGINE_DATA_DIR", str(project_cache))
    assert _external_lookthrough_cache_file() is None

    external_root = tmp_path / "engine-data"
    monkeypatch.setenv("MF_ENGINE_DATA_DIR", str(external_root))
    assert _external_lookthrough_cache_file() is None


def test_active_fund_enrichment_propagates_explicit_external_consent(monkeypatch):
    import services.ai_fund_classifier as classifier

    seen = {"batch": [], "lookup": [], "classify": []}
    monkeypatch.setattr(
        classifier,
        "batch_classify_funds_with_llm",
        lambda names, external_processing_consent=False: seen["batch"].append(external_processing_consent) or {},
    )
    monkeypatch.setattr(
        classifier,
        "lookup_fund_segment_allocation_online",
        lambda name, timeout_sec=5.0, external_processing_consent=False: seen["lookup"].append(external_processing_consent) or None,
    )

    def fake_classify(name, use_live_ai=False, external_processing_consent=False):
        seen["classify"].append(external_processing_consent)
        return {
            "category": "Equity", "scheme_type": "Equity", "asset_class": "Equity",
            "sub_category": "", "eq": None, "debt": None, "gold": None,
            "intl": None, "lc": None, "mc": None, "sc": None, "re": None,
            "other": None, "sector": None, "benchmark": None, "risk_rating": None,
            "source": "UNVERIFIED", "ai_rationale": "No verified facts.",
        }

    monkeypatch.setattr(classifier, "classify_fund_with_ai", fake_classify)
    classifier.enrich_funds_with_ai(
        [{"scheme": "Unknown Private Scheme"}],
        use_live_ai=True,
        external_processing_consent=True,
    )

    assert seen["batch"] == [True]
    assert seen["lookup"] == [True]
    assert seen["classify"] == [True]


def test_online_scheme_cache_rejects_symlink_into_repository(tmp_path, monkeypatch):
    from pathlib import Path
    from services.ai_fund_classifier import _external_lookthrough_cache_file

    repository_data = Path(__file__).resolve().parents[1] / "data"
    linked_root = tmp_path / "linked-engine-data"
    linked_root.symlink_to(repository_data, target_is_directory=True)
    monkeypatch.setenv("MF_ENGINE_DATA_DIR", str(linked_root))

    assert _external_lookthrough_cache_file() is None



def test_external_scheme_lookup_requires_provider_policy_approval(monkeypatch):
    from services.ai_fund_classifier import lookup_fund_segment_allocation_online

    monkeypatch.delenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", raising=False)
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert lookup_fund_segment_allocation_online(
        "Synthetic Public Scheme", external_processing_consent=True
    ) is None
    assert calls == []


def test_classifier_sends_only_minimum_scheme_lookup_context_and_disables_cache(monkeypatch):
    import json
    import core.ai_engine as ai
    import services.ai_fund_classifier as classifier

    classifier._AI_SCHEME_CACHE.clear()
    captured = []

    def fake_call_llm(prompt, **kwargs):
        captured.append((prompt, kwargs))
        return json.dumps({
            "canonical_name": "Synthetic Public Scheme",
            "category": "Equity", "scheme_type": "Flexi Cap",
            "sub_category": "Diversified equity",
            "eq": 95, "debt": 5, "gold": 0, "intl": 0,
            "lc": 50, "mc": 25, "sc": 20,
            "benchmark": "Synthetic TRI", "risk_rating": "Very High",
            "ai_rationale": "Synthetic test only",
        })

    monkeypatch.setattr(ai, "call_llm", fake_call_llm)
    result = classifier.classify_fund_with_llm(
        "Synthetic Public Scheme Direct Growth", external_processing_consent=True
    )

    assert result is not None
    assert len(captured) == 1
    prompt, kwargs = captured[0]
    assert "Synthetic Public Scheme" in prompt
    assert "Direct Growth" not in prompt
    assert "client_name" not in prompt.lower()
    assert "folio" not in prompt.lower()
    assert "account" not in prompt.lower()
    assert "portfolio value" not in prompt.lower()
    assert kwargs["use_cache"] is False
    assert kwargs["external_processing_consent"] is True



def test_nested_goal_transaction_and_security_identifiers_are_collected():
    from core.prompt_advisor import collect_sensitive_identifiers, sanitize_prompt_for_privacy

    records = {
        "goals": [{"name": "CANARY GOAL NAME", "description": "CANARY GOAL DESCRIPTION"}],
        "transactions": [{
            "transaction_description": "CANARY TRANSACTION DETAILS",
            "narration": "CANARY NARRATION",
        }],
        "holdings": [{
            "security_id": "CANARY SECURITY ID",
            "key_underlying_holdings": ["CANARY UNDERLYING STOCK"],
        }],
    }
    identifiers = collect_sensitive_identifiers(records)
    expected = (
        "CANARY GOAL NAME", "CANARY GOAL DESCRIPTION",
        "CANARY TRANSACTION DETAILS", "CANARY NARRATION",
        "CANARY SECURITY ID", "CANARY UNDERLYING STOCK",
    )
    assert set(expected).issubset(set(identifiers))
    outbound = sanitize_prompt_for_privacy(" ".join(expected), sensitive_identifiers=identifiers)
    for value in expected:
        assert value not in outbound



def test_batch_classifier_sends_canonical_names_without_plan_variants(monkeypatch):
    import json
    import core.ai_engine as ai
    import services.ai_fund_classifier as classifier

    classifier._AI_SCHEME_CACHE.clear()
    captured = []

    def fake_call_llm(prompt, **kwargs):
        captured.append((prompt, kwargs))
        return json.dumps([{
            "scheme": "Synthetic Public Scheme",
            "canonical_name": "Synthetic Public Scheme",
            "category": "Equity", "scheme_type": "Flexi Cap",
            "sub_category": "Diversified equity",
            "eq": 95, "debt": 5, "gold": 0, "intl": 0,
            "lc": 50, "mc": 25, "sc": 20,
            "benchmark": "Synthetic TRI", "risk_rating": "Very High",
            "ai_rationale": "Synthetic test only",
        }])

    monkeypatch.setattr(ai, "call_llm", fake_call_llm)
    original = "Synthetic Public Scheme Regular Growth"
    result = classifier.batch_classify_funds_with_llm(
        [original], external_processing_consent=True
    )

    assert original in result
    assert len(captured) == 1
    prompt, kwargs = captured[0]
    assert "Synthetic Public Scheme" in prompt
    assert "Regular Growth" not in prompt
    assert kwargs["use_cache"] is False
    assert kwargs["external_processing_consent"] is True



def test_sensitive_identifier_collection_covers_fee_and_overlap_records():
    from types import SimpleNamespace
    from core.prompt_advisor import _sensitive_identifiers_from_facts

    facts = SimpleNamespace(
        client_name="Synthetic Investor",
        holdings=[],
        fee_bleed=SimpleNamespace(details=[{"fund_name": "CANARY FEE SCHEME"}]),
        overlap_matrix=[SimpleNamespace(
            fund_a="CANARY OVERLAP FUND A",
            fund_b="CANARY OVERLAP FUND B",
            shared_stocks=["CANARY OVERLAP STOCK"],
        )],
        weighted_overlap=[SimpleNamespace(
            fund_a="CANARY WEIGHTED FUND A",
            fund_b="CANARY WEIGHTED FUND B",
            shared_stocks=["CANARY WEIGHTED STOCK"],
        )],
        thematic_exposures=[],
    )
    identifiers = _sensitive_identifiers_from_facts(facts)
    for value in (
        "CANARY FEE SCHEME", "CANARY OVERLAP FUND A", "CANARY OVERLAP FUND B",
        "CANARY OVERLAP STOCK", "CANARY WEIGHTED FUND A",
        "CANARY WEIGHTED FUND B", "CANARY WEIGHTED STOCK",
    ):
        assert value in identifiers


def test_interactive_ai_does_not_transmit_free_text_question(monkeypatch):
    import core.ai_engine as ai_engine
    import services.ai_fund_classifier as classifier

    captured = []
    monkeypatch.setenv("MF_EXTERNAL_PROCESSING_POLICY_APPROVED", "true")

    def fake_call_llm(prompt, **kwargs):
        captured.append(prompt)
        return "Synthetic generic narrative response long enough for the live result path."

    monkeypatch.setattr(ai_engine, "call_llm", fake_call_llm)
    result = classifier.answer_fiduciary_query(
        "My name is John Doe, PAN ABCDE1234F, folio 987654321; explain my situation.",
        {
            "total_value": 100000, "eq_pct": 70, "debt_pct": 30,
            "regular_value": 25000, "regular_pct": 25, "annual_bleed": 200,
            "compounded_10y_drag": 2000, "dual_count": 0,
        },
        [],
        use_live_ai=True,
        external_processing_consent=True,
    )

    assert result["source"] == "Live AI Assistant (Fiduciary Intelligence)"
    assert len(captured) == 1
    assert "John Doe" not in captured[0]
    assert "ABCDE1234F" not in captured[0]
    assert "987654321" not in captured[0]
    assert "[WITHHELD" in captured[0]



def test_numeric_folio_and_account_identifiers_are_collected_from_fact_objects():
    from types import SimpleNamespace
    from core.prompt_advisor import _sensitive_identifiers_from_facts

    facts = SimpleNamespace(
        client_name="Synthetic Investor",
        holdings=[SimpleNamespace(
            fund_name="Synthetic Scheme",
            folio_number=987654321,
            account_id=123456789012,
        )],
        fee_bleed=SimpleNamespace(details=[]),
        overlap_matrix=[],
        weighted_overlap=[],
        thematic_exposures=[],
    )
    identifiers = _sensitive_identifiers_from_facts(facts)
    assert "987654321" in identifiers
    assert "123456789012" in identifiers


def test_every_application_ai_callsite_explicitly_disables_cache_and_passes_consent():
    """New provider call sites must opt into the privacy contract explicitly."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source_roots = (root / "core", root / "services", root / "api", root / "ui")
    violations = []

    for source_root in source_roots:
        if not source_root.exists():
            continue
        for path in source_root.rglob("*.py"):
            if path == root / "core" / "ai_engine.py":
                # This is the enforcement boundary, not an application caller.
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as exc:
                violations.append(f"{path.relative_to(root)}: source cannot be audited ({type(exc).__name__})")
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else ""
                )
                if name not in {"call_llm", "_engine_call_llm"}:
                    continue

                keywords = {item.arg: item.value for item in node.keywords if item.arg}
                cache_value = keywords.get("use_cache")
                consent_value = keywords.get("external_processing_consent")
                cache_disabled = (
                    isinstance(cache_value, ast.Constant) and cache_value.value is False
                )
                if not cache_disabled or consent_value is None:
                    violations.append(
                        f"{path.relative_to(root)}:{node.lineno}: "
                        "provider call must pass external_processing_consent and use_cache=False"
                    )

    assert not violations, "AI privacy call-site contract violations:\\n" + "\\n".join(violations)
