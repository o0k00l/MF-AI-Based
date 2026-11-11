"""Unit tests verifying all 6 expanded AI capabilities across fiduciary services.

Covers:
1. SIP Blueprint: Completion alerts and optimal tranche timing.
2. Risk Profiler: AI behavioral risk tier prediction from CAS data.
3. Fiduciary Report: Concentration risk alerts and statutory compliance narratives.
4. Tax Optimization: Section 112A annual tax harvesting, headroom, and loss set-off.
5. Goal-Based Planning: Inflation benchmarks, scenario stress-testing, and gap mitigation.
6. Fund Matching & Peer Attribution: Style box breakdown and peer TER fee alpha.
"""
from __future__ import annotations

import pytest
from decimal import Decimal

from services.cgs_parser import evaluate_tax_harvesting_strategy
from services.risk_profiler import predict_risk_tier_from_portfolio, SebiRiskTier
from services.goal_planner import evaluate_goal_scenarios_with_ai
from services.ai_fund_classifier import evaluate_portfolio_concentration_risks, evaluate_portfolio_peer_attribution
from services.fiduciary_engine import generate_fiduciary_sip_blueprint


def test_tax_harvesting_strategy_evaluation():
    cgs_data = {
        "summary": {
            "ltcg_inr": 25000.0,
            "stcg_inr": -15000.0,
            "total_outflows": 200000.0,
            "total_cost": 190000.0,
        }
    }
    portfolio = [
        {
            "scheme": "Flexi Cap Fund Direct Growth",
            "current_value": 300000.0,
            "invested_value": 200000.0,
            "category": "Equity",
            "plan_type": "Direct",
        },
        {
            "scheme": "Regular Equity Fund",
            "current_value": 150000.0,
            "invested_value": 110000.0,
            "category": "Equity",
            "plan_type": "Regular",
        },
    ]

    res = evaluate_tax_harvesting_strategy(cgs_data, portfolio, use_live_ai=False)
    assert res["status"] == "ANALYZED"
    assert res["annual_exemption_limit_inr"] == 125000.0
    assert res["realized_ltcg_inr"] == 25000.0
    assert res["remaining_headroom_inr"] == 100000.0
    assert res["unrealized_equity_gain_inr"] == 140000.0
    assert res["harvestable_amount_inr"] == 100000.0
    assert res["potential_tax_saving_inr"] == 12500.0
    assert any("Short-Term Capital Loss" in ins for ins in res["loss_setoff_insights"])
    assert any("Zero-Tax Regular to Direct Conversion" in rec for rec in res["rebalancing_recommendations"])
    assert "Section 112A" in res["ai_tax_narrative"]


def test_predict_risk_tier_from_portfolio():
    aggressive_portfolio = [
        {"scheme": "Large Cap Index Direct", "current_value": 200000.0, "eq": 100.0, "debt": 0.0, "category": "Large Cap"},
        {"scheme": "Mid Cap Alpha Direct", "current_value": 400000.0, "eq": 95.0, "debt": 5.0, "category": "Mid Cap"},
        {"scheme": "Small Cap Growth Direct", "current_value": 300000.0, "eq": 95.0, "debt": 5.0, "category": "Small Cap"},
        {"scheme": "Liquid Fund Direct", "current_value": 100000.0, "eq": 0.0, "debt": 100.0, "category": "Debt"},
    ]
    pred = predict_risk_tier_from_portfolio(aggressive_portfolio, use_live_ai=False)
    assert pred["status"] == "PREDICTED"
    assert pred["predicted_tier"] in (SebiRiskTier.TIER_5_HIGH, SebiRiskTier.TIER_6_VERY_HIGH)
    assert pred["portfolio_equity_pct"] > 80.0
    assert pred["portfolio_mid_small_pct"] >= 65.0
    assert pred["confidence_score_pct"] >= 80.0
    assert "revealed investment behavior" in pred["ai_behavioral_rationale"].lower()


def test_goal_scenarios_and_gap_mitigation():
    goals = [
        {
            "id": "retirement",
            "name": "Retirement Corpus",
            "cost_today": 15000000.0,
            "horizon": 20,
            "future_target": 48000000.0,
            "required_sip": 35000.0,
        },
        {
            "id": "education",
            "name": "Child Higher Education",
            "cost_today": 3000000.0,
            "horizon": 12,
            "future_target": 7500000.0,
            "required_sip": 20000.0,
        },
    ]
    res = evaluate_goal_scenarios_with_ai(goals, total_budget_inr=40000.0, use_live_ai=False)
    assert res["status"] == "ANALYZED"
    assert res["total_required_sip_inr"] == 55000.0
    assert res["monthly_gap_inr"] == 15000.0
    assert len(res["scenarios"]) == 3
    assert any("Baseline" in sc["scenario_name"] for sc in res["scenarios"])
    assert any("High Inflation" in sc["scenario_name"] for sc in res["scenarios"])
    assert any("Step-Up Expansion" in p for p in res["mitigation_paths"])


def test_portfolio_concentration_risks():
    concentrated_funds = [
        {"scheme": "HDFC Single Massive Fund Direct", "current_value": 700000.0, "category": "Large Cap"},
        {"scheme": "HDFC Sectoral Tech Fund Direct", "current_value": 200000.0, "category": "Sectoral"},
        {"scheme": "HDFC Liquid Fund Direct", "current_value": 100000.0, "category": "Debt"},
    ]
    c_res = evaluate_portfolio_concentration_risks(concentrated_funds)
    assert c_res["status"] == "ANALYZED"
    assert c_res["concentration_score"] == "HIGH_CONCENTRATION"
    assert c_res["max_scheme_pct"] == 70.0
    assert c_res["thematic_pct"] == 20.0
    assert c_res["max_amc_pct"] == 100.0
    assert any(a["type"] == "SINGLE_SCHEME_CONCENTRATION" for a in c_res["alerts"])
    assert any(a["type"] == "THEMATIC_OVEREXPOSURE" for a in c_res["alerts"])
    assert any(a["type"] == "AMC_CONCENTRATION" for a in c_res["alerts"])


def test_portfolio_peer_attribution():
    funds = [
        {"scheme": "Nifty 50 Index Fund Direct", "current_value": 500000.0, "category": "Large Cap", "ter_direct": 0.20, "ter_regular": 1.20},
        {"scheme": "Mid Cap Fund Direct", "current_value": 300000.0, "category": "Mid Cap", "ter_direct": 0.65, "ter_regular": 1.75},
        {"scheme": "Liquid Fund Direct", "current_value": 200000.0, "category": "Debt", "ter_direct": 0.15, "ter_regular": 0.45},
    ]
    p_res = evaluate_portfolio_peer_attribution(funds)
    assert p_res["status"] == "ANALYZED"
    assert p_res["weighted_direct_ter"] < 0.40
    assert p_res["peer_alpha_spread"] > 0.50
    assert "core_index_pct" in p_res["style_breakdown"]


def test_sip_blueprint_alerts_and_timing():
    funds = [
        {"scheme": "Nifty 50 Index Fund Direct Growth", "current_value": 200000.0, "plan_type": "Direct", "source": "existing", "category": "Large Cap"},
    ]
    bp = generate_fiduciary_sip_blueprint(30000.0, funds=funds)
    assert bp["status"] == "DETERMINISTIC_SIP_READY"
    assert "optimal_tranche_timing" in bp
    assert bp["optimal_tranche_timing"]["recommended_cadence"] == "Bi-Weekly (Dual-Tranche)"
    assert bp["optimal_tranche_timing"]["biweekly_amount_inr"] == Decimal("15000.00")
    assert "portfolio_completion_alerts" in bp
    assert len(bp["portfolio_completion_alerts"]) > 0
    assert "fiduciary_routing_rationale" in bp



def test_factor_attribution_and_exit_signals():
    from services.ai_fund_classifier import evaluate_factor_attribution

    funds = [
        {"scheme": "Nifty 50 Index Fund Direct", "canonical_scheme": "nifty 50 index", "current_value": 500000.0, "category": "Large Cap", "plan_type": "Direct"},
        {"scheme": "Nifty 50 Index Fund Regular", "canonical_scheme": "nifty 50 index", "current_value": 200000.0, "category": "Large Cap", "plan_type": "Regular", "annual_commission_bleed": 2000.0, "trail_commission_pct": 1.0},
        {"scheme": "Mid Cap Alpha Fund Direct", "canonical_scheme": "mid cap alpha", "current_value": 200000.0, "category": "Mid Cap", "plan_type": "Direct"},
        {"scheme": "Liquid Fund Direct", "canonical_scheme": "liquid fund", "current_value": 100000.0, "category": "Debt", "plan_type": "Direct"},
    ]
    res = evaluate_factor_attribution(funds)
    assert res["status"] == "ANALYZED"
    assert res["hhi_score"] > 0
    assert "quality_large_core_pct" in res["factor_tilts"]
    assert "momentum_alpha_pct" in res["factor_tilts"]
    assert len(res["exit_signals"]) > 0
    assert any(sig["action"] == "CONSOLIDATE_DUPLICATE_REGULAR" for sig in res["exit_signals"])


def test_monte_carlo_goal_simulation():
    from services.goal_planner import run_monte_carlo_goal_simulation

    sim = run_monte_carlo_goal_simulation(
        monthly_sip_inr=25000.0,
        target_corpus_inr=10000000.0,
        horizon_years=15,
        existing_corpus_inr=500000.0,
        equity_pct=75.0,
        num_trials=500,
        seed=42,
    )
    assert sim["status"] == "SIMULATED"
    assert sim["num_trials"] == 500
    assert sim["probability_of_success_pct"] > 60.0
    assert sim["p05_corpus_inr"] < sim["p50_corpus_inr"] < sim["p95_corpus_inr"]
    assert "statistical confidence" in sim["recommended_action"].lower()


def test_cas_document_integrity_audit():
    from services.cas_parser import audit_cas_document_integrity

    funds = [
        {"scheme": "Nifty 50 Index Direct", "current_value": 400000.0, "nav": 150.0},
        {"scheme": "Mid Cap Alpha Direct", "current_value": 300000.0, "nav": 210.0},
        {"scheme": "Redeemed Zero Balance Folio", "current_value": 0.0, "nav": 0.0},
    ]
    res = audit_cas_document_integrity(funds)
    assert res["status"] == "VERIFIED"
    assert res["total_folios"] == 3
    assert res["unique_schemes"] == 3
    assert res["zero_balance_folios"] == 1
    assert len(res["audit_hash"]) == 64
    assert any("zero-balance" in f.lower() for f in res["flags"])


def test_natural_language_fiduciary_query():
    from services.ai_fund_classifier import answer_fiduciary_query

    metrics = {
        "total_value": 1500000.0,
        "eq_pct": 82.0,
        "debt_pct": 18.0,
        "regular_value": 400000.0,
        "regular_pct": 26.7,
        "annual_bleed": 3600.0,
        "compounded_10y_drag": 68000.0,
        "dual_count": 1,
    }
    funds = [{"scheme": "Test Fund Direct"}]

    q_res = answer_fiduciary_query("What is my commission fee leakage?", metrics, funds, use_live_ai=False)
    assert "Statutory" in q_res["source"]
    assert "₹3,600" in q_res["response"]
    assert "₹68,000" in q_res["response"]

    q_tax = answer_fiduciary_query("How can I do tax harvesting?", metrics, funds, use_live_ai=False)
    assert "Section 112A" in q_tax["response"]
    assert "1.25 Lakhs" in q_tax["response"]


def test_segment_allocation_actuals_and_factsheet_lookthrough():
    from services.ai_fund_classifier import classify_fund_with_ai

    # 1. Nippon India Small Cap Fund (actual factsheet data from policy storage)
    nippon_res = classify_fund_with_ai("Nippon India Small Cap Fund - Direct Plan - Growth", use_live_ai=False)
    assert nippon_res["scheme_type"] == "Small Cap"
    assert nippon_res["category"] == "Equity"
    assert nippon_res["sc"] == 70.02
    assert nippon_res["lc"] == 14.31
    assert nippon_res["mc"] == 13.05
    assert "Factsheet" in nippon_res["source"]

    # 2. ICICI Prudential Bluechip Fund (actual factsheet large-cap look-through)
    icici_res = classify_fund_with_ai("ICICI Prudential Bluechip Fund Direct Growth", use_live_ai=False)
    assert icici_res["scheme_type"] == "Large Cap"
    assert icici_res["category"] == "Equity"
    assert icici_res["lc"] == 81.09
    assert icici_res["mc"] == 10.69
    assert icici_res["sc"] == 0.0
    assert "Factsheet" in icici_res["source"]

    # 3. SBI Contra Fund (actual factsheet contra look-through)
    sbi_res = classify_fund_with_ai("SBI Contra Fund - Direct Plan - Growth", use_live_ai=False)
    assert sbi_res["category"] == "Equity"
    assert sbi_res["lc"] == 46.12
    assert sbi_res["mc"] == 24.80
    assert sbi_res["sc"] == 20.58


def test_fast_ai_fiduciary_query_speed_and_segment_attribution():
    import time
    from services.ai_fund_classifier import answer_fiduciary_query

    metrics = {
        "total_value": 2000000.0,
        "eq_pct": 85.0,
        "debt_pct": 15.0,
        "regular_value": 0.0,
        "regular_pct": 0.0,
        "annual_bleed": 0.0,
        "compounded_10y_drag": 0.0,
        "dual_count": 0,
        "total_debt": 300000.0,
    }
    funds = [
        {"scheme": "Nippon India Small Cap Fund Direct", "current_value": 1000000.0, "lc": 14.31, "mc": 13.05, "sc": 70.02, "debt": 2.62},
        {"scheme": "ICICI Prudential Bluechip Direct", "current_value": 1000000.0, "lc": 81.09, "mc": 10.69, "sc": 0.0, "debt": 8.22},
    ]

    # Test segment allocation response
    q_seg = answer_fiduciary_query("What is my segment allocation across large, mid, and small cap?", metrics, funds, use_live_ai=False)
    assert "Market Cap Look-Through" in q_seg["response"]
    assert "Large Cap" in q_seg["response"]
    assert "Small Cap" in q_seg["response"]

    # Test query execution speed on repeat query (cached return in <10ms)
    t0 = time.perf_counter()
    q_repeat = answer_fiduciary_query("What is my segment allocation across large, mid, and small cap?", metrics, funds, use_live_ai=False)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.05, f"Cached query should be instantaneous, took {elapsed:.4f}s"
    assert q_repeat["response"] == q_seg["response"]


def test_compute_portfolio_segment_breakdown_and_exact_math():
    from services.ai_fund_classifier import compute_portfolio_segment_breakdown

    funds = [
        {
            "scheme": "Axis Small Cap Fund Direct Growth",
            "scheme_type": "Small Cap",
            "current_value": 500000.0,
            "lc": 6.31,
            "mc": 9.60,
            "sc": 74.41,
            "eq": 90.32,
            "debt": 9.68,
            "classification_source": "AMC Factsheet Look-Through",
        },
        {
            "scheme": "ICICI Prudential Bluechip Direct",
            "scheme_type": "Large Cap",
            "current_value": 500000.0,
            "lc": 81.09,
            "mc": 10.69,
            "sc": 0.0,
            "eq": 91.78,
            "debt": 8.22,
            "classification_source": "AMC Factsheet Look-Through",
        },
    ]

    res = compute_portfolio_segment_breakdown(funds)
    assert res["total_value"] == 1000000.0
    
    # Large Cap: 500k * 6.31% + 500k * 81.09% = 31550 + 405450 = 437000 (43.7%)
    expected_lc = 500000.0 * 0.0631 + 500000.0 * 0.8109
    assert abs(res["large_cap_value"] - expected_lc) < 1.0
    assert abs(res["large_cap_pct"] - 43.7) < 0.1

    # Small Cap: 500k * 74.41% = 372050 (37.2%)
    expected_sc = 500000.0 * 0.7441
    assert abs(res["small_cap_value"] - expected_sc) < 1.0
    assert abs(res["small_cap_pct"] - 37.2) < 0.1

    # Debt: 500k * 9.68% + 500k * 8.22% = 48400 + 41100 = 89500 (8.95%)
    expected_debt = 500000.0 * 0.0968 + 500000.0 * 0.0822
    assert abs(res["debt_value"] - expected_debt) < 1.0
    assert abs(res["debt_pct"] - 8.95) < 0.1

    # Mathematical consistency checks
    assert len(res["scheme_rows"]) == 2
    for r in res["scheme_rows"]:
        assert r["large_cap_inr"] + r["mid_cap_inr"] + r["small_cap_inr"] <= r["current_value"] + 1.0


def test_expanded_authentic_factsheet_coverage_and_hybrid_classification():
    from services.ai_fund_classifier import classify_fund_with_ai

    # 1. Axis Small Cap Fund
    axis = classify_fund_with_ai("Axis Small Cap Fund - Direct Plan - Growth", use_live_ai=False)
    assert axis["sc"] == 74.41
    assert axis["lc"] == 6.31
    assert "Factsheet" in axis["source"]

    # 2. Bandhan Small Cap Fund
    bandhan = classify_fund_with_ai("Bandhan Small Cap Fund", use_live_ai=False)
    assert bandhan["sc"] == 74.2
    assert bandhan["lc"] == 4.1
    assert "Factsheet" in bandhan["source"]

    # 3. Quant Active Fund (Multi Cap)
    quant_act = classify_fund_with_ai("Quant Active Fund Direct Growth", use_live_ai=False)
    assert quant_act["category"] == "Equity"
    assert quant_act["lc"] == 46.5
    assert quant_act["mc"] == 26.2
    assert quant_act["sc"] == 23.8

    # 4. ICICI Prudential Equity & Debt Fund (Hybrid, NOT pure debt)
    icici_ed = classify_fund_with_ai("ICICI Prudential Equity & Debt Fund Direct Growth", use_live_ai=False)
    assert icici_ed["category"] == "Hybrid"
    assert icici_ed["eq"] == 72.0
    assert icici_ed["debt"] == 28.0
    assert icici_ed["lc"] == 50.2

    # 5. SBI Liquid Fund (Pure debt)
    sbi_liq = classify_fund_with_ai("SBI Liquid Fund Direct Growth", use_live_ai=False)
    assert sbi_liq["category"] == "Debt"
    assert sbi_liq["debt"] == 100.0
    assert sbi_liq["eq"] == 0.0


def test_ui_utils_canonical_segment_delegation():
    from ui.utils import calculate_allocations

    funds = [
        {"scheme": "Fund 1", "current_value": 100000.0, "lc": 60.0, "mc": 30.0, "sc": 10.0, "eq": 100.0, "debt": 0.0},
        {"scheme": "Fund 2", "current_value": 100000.0, "lc": 0.0, "mc": 0.0, "sc": 0.0, "eq": 0.0, "debt": 100.0},
    ]

    allocs = calculate_allocations(funds)
    assert allocs["total_value"] == 200000.0
    assert allocs["equity_value"] == 100000.0
    assert allocs["debt_value"] == 100000.0
    assert allocs["large_cap_value"] == 60000.0
    assert allocs["mid_cap_value"] == 30000.0
    assert allocs["small_cap_value"] == 10000.0
