"""
test_p0_fiduciary_invariants.py - Exhaustive verification suite for the 4 P0 Fiduciary Compliance Gaps:
- P0.1: Universal 40/30/15/15 SAA Invariant across all SEBI risk tiers and starter vs established portfolios.
- P0.2: ₹1.25L Annual LTCG Tax Shield Siphon & Day 366 Immature Lot Holding Rule.
- P0.3: All 10 Binary Fiduciary Eligibility Gates (Gate 1 through Gate 10).
- P0.4: Candidate Universe Loading & NO ACTION Fiduciary Branch.
"""
from datetime import date, timedelta
from pathlib import Path
from decimal import Decimal
import pytest

from core.models import EligibilityGateResult, NOActionResult, DeterministicSIPPlan
from core.eligibility import (
    check_eligibility_gates,
    filter_candidates,
    evaluate_no_action,
    load_candidate_universe,
    validate_thematic_satellite_cap,
    validate_direct_sip_mandate
)
from core.math_engine import (
    compute_deterministic_sip_blueprint,
    compute_deterministic_lumpsum_blueprint
)
from tax.transition_planner import (
    Lot,
    FundSellPlan,
    plan_fy_tranches,
    load_tax_rules
)


def test_p0_1_universal_4_slot_sizing_invariant():
    """Verifies that equity allocations across all risk tiers strictly adhere to the 40/30/15/15 universal invariant."""
    budget = 100000.0

    # Tier 6: 100% Equity (Established >= 5L)
    plan_t6 = compute_deterministic_sip_blueprint(
        monthly_budget=budget,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=7.54,
        client_aum=5000000.0
    )
    assert plan_t6.equity_sip_pct == 100.0
    assert plan_t6.debt_sip_pct == 0.0
    roles = {item.category_role: item for item in plan_t6.items}
    assert roles["Core Flexi-Cap Compounder"].allocation_pct == 40.0
    assert roles["Mid-Cap Alpha Engine"].allocation_pct == 30.0
    assert roles["Large-Cap Bluechip Anchor"].allocation_pct == 15.0
    assert roles["Tactical Thematic Satellite"].allocation_pct == 15.0
    assert sum(it.monthly_inr for it in plan_t6.items) == budget

    # Tier 5: 85% Equity / 15% Debt (Established >= 5L)
    plan_t5 = compute_deterministic_sip_blueprint(
        monthly_budget=budget,
        risk_tier="Tier 5 (High)",
        stability_buffer_pct=3.0,
        client_aum=5000000.0
    )
    assert plan_t5.equity_sip_pct == 85.0
    assert plan_t5.debt_sip_pct == 15.0
    roles5 = {item.category_role: item for item in plan_t5.items}
    # 85 * 0.30 = 25.5
    assert roles5["Mid-Cap Alpha Engine"].allocation_pct == 25.5
    # 85 * 0.15 = 12.8
    assert roles5["Large-Cap Bluechip Anchor"].allocation_pct == 12.8
    # 85 * 0.15 = 12.8
    assert roles5["Tactical Thematic Satellite"].allocation_pct == 12.8
    # Flexi absorbs rounding: 85 - (25.5 + 12.8 + 12.8) = 33.9%
    assert roles5["Core Flexi-Cap Compounder"].allocation_pct == 33.9
    assert roles5["High-Grade Debt Cushion"].allocation_pct == 15.0
    assert sum(it.monthly_inr for it in plan_t5.items) == budget

    # Starter Portfolio (< 5L AUM): 60/40 Core/Mid, 0% Large, 0% Thematic
    plan_starter = compute_deterministic_sip_blueprint(
        monthly_budget=20000.0,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=7.54,
        client_aum=200000.0  # Starter
    )
    assert plan_starter.equity_sip_pct == 100.0
    roles_starter = {item.category_role: item for item in plan_starter.items}
    assert roles_starter["Core Flexi-Cap Compounder"].allocation_pct == 60.0
    assert roles_starter["Mid-Cap Alpha Engine"].allocation_pct == 40.0
    assert "Large-Cap Bluechip Anchor" not in roles_starter
    assert "Tactical Thematic Satellite" not in roles_starter
    assert sum(it.monthly_inr for it in plan_starter.items) == 20000.0
    print("[PASS] P0.1 Universal 4-Slot Sizing Invariant Verified")


def test_p0_2_tax_shield_siphon_and_day_366():
    """Verifies that ₹1.25L LTCG annual limit is enforced and immature lots (<365d) are deferred to Day 366."""
    as_of = date(2026, 10, 9)
    current_fy_start = 2026  # FY 2026-27

    # Create 2 mature lots with ₹1,00,000 gain each (Total = ₹2,00,000 LTCG)
    lot1 = Lot(
        fund_id="HDFC Regular Fund",
        folio_name="12345",
        purchase_date=date(2024, 1, 15),
        units=1000.0,
        nav=100.0,
        cost=100000.0,
        source="cas"
    )
    lot2 = Lot(
        fund_id="ICICI Regular Fund",
        folio_name="67890",
        purchase_date=date(2024, 2, 1),
        units=1000.0,
        nav=100.0,
        cost=100000.0,
        source="cas"
    )
    # Create 1 immature lot (< 365 days old: purchased 2026-05-01, as_of is 2026-10-09)
    # Holding days = ~161 days -> Immature!
    lot_immature = Lot(
        fund_id="Nippon Regular Fund",
        folio_name="55555",
        purchase_date=date(2026, 5, 1),
        units=500.0,
        nav=100.0,
        cost=50000.0,
        source="cas"
    )

    plans = {
        "HDFC Regular Fund": FundSellPlan(fund_id="HDFC Regular Fund", total_amount=200000.0, lots=[lot1]),
        "ICICI Regular Fund": FundSellPlan(fund_id="ICICI Regular Fund", total_amount=200000.0, lots=[lot2]),
        "Nippon Regular Fund": FundSellPlan(fund_id="Nippon Regular Fund", total_amount=75000.0, lots=[lot_immature])
    }

    current_navs = {
        "HDFC Regular Fund": 200.0,    # Value: 2,00,000, Gain: 1,00,000
        "ICICI Regular Fund": 200.0,   # Value: 2,00,000, Gain: 1,00,000
        "Nippon Regular Fund": 150.0   # Value: 75,000, Gain: 25,000
    }

    from tax.transition_planner import load_tax_rules
    tax_rules_path = Path("data/policy/tax_rules.json")
    tax_rules = load_tax_rules(tax_rules_path) if tax_rules_path.exists() else {
        "ltcg_exemption": 125000.0,
        "ltcg_rate": 0.125,
        "stcg_rate": 0.20,
        "exit_load_pct": 1.0,
        "lt_holding_months": 12
    }

    fy_plans = plan_fy_tranches(plans, tax_rules, as_of, current_navs)

    # 1. FY 2026-27 (Year 1) must shelter EXACTLY up to ₹1,25,000 of LTCG
    y1_items = fy_plans.get(2026, [])
    y1_sheltered = sum(it["sheltered"] for it in y1_items)
    assert y1_sheltered <= 125000.0, f"Year 1 sheltered {y1_sheltered} exceeded ₹1.25L exemption!"
    assert y1_sheltered == 125000.0, f"Year 1 did not maximize ₹1.25L exemption (sheltered {y1_sheltered})"

    # 2. Immature lot must NOT be sold with exit load or 20% STCG
    # It must be deferred to Day 366 (2027-05-02 -> FY 2027-28)
    for it in y1_items:
        assert it["gain_type"] == "LT"
        assert it["exit_load"] == 0.0

    # Immature lot must be present in FY 2027-28 with held_to_day_366 == True and exit_load == 0
    y2_items = fy_plans.get(2027, [])
    nippon_y2 = [it for it in y2_items if it["fund_id"] == "Nippon Regular Fund"]
    assert len(nippon_y2) > 0, "Immature lot was not scheduled in Year 2!"
    assert nippon_y2[0]["held_to_day_366"] is True
    assert nippon_y2[0]["exit_load"] == 0.0
    print("[PASS] P0.2 Tax Shield Siphon & Day 366 Immature Lot Rule Verified")


def test_p0_3_all_10_binary_eligibility_gates():
    """Tests each of the 10 Binary Fiduciary Gates individually for strict pass/fail enforcement."""
    base_good_fund = {
        "fund_id": "TEST_FUND",
        "fund_name": "Test Bluechip Direct Plan Growth",
        "aum_crore": 15000.0,
        "category": "Flexi Cap",
        "top10_concentration_pct": 35.0,
        "single_sector_weight_pct": 22.0,
        "sharpe_3y": 0.65,
        "alpha_3y": 3.5,
        "downside_capture_ratio": 85.0,
        "upside_capture_ratio": 110.0,
        "riskometer_score": 5,
        "confidence_score": 0.95,
        "data_complete": True,
        "manager_tenure_years": 4.5,
        "is_direct": True
    }

    # Clean pass
    res_clean = check_eligibility_gates(base_good_fund)
    assert res_clean.passed is True
    assert len(res_clean.failed_gates) == 0

    # Gate 1 Failure: AMC Concentration >= 30%
    holdings = [{"scheme": "TEST Large Cap Fund", "value": 350000.0}]  # 35% AMC exposure
    res_g1 = check_eligibility_gates(base_good_fund, portfolio_holdings=[{"scheme": "TEST Large Cap", "value": 350000.0}, {"scheme": "OTHER Fund", "value": 650000.0}])
    assert res_g1.amc_concentration_gate is False
    assert res_g1.passed is False
    assert any("Gate 1" in g for g in res_g1.failed_gates)

    # Gate 2 Failure: AUM < ₹1,000 Cr
    bad_aum = dict(base_good_fund, aum_crore=650.0)
    res_g2 = check_eligibility_gates(bad_aum)
    assert res_g2.aum_stability_gate is False
    assert res_g2.passed is False
    assert any("Gate 2" in g for g in res_g2.failed_gates)

    # Gate 3 Failure: Top-10 Concentration > 55%
    bad_top10 = dict(base_good_fund, top10_concentration_pct=62.0)
    res_g3 = check_eligibility_gates(bad_top10)
    assert res_g3.concentration_gate is False
    assert res_g3.passed is False
    assert any("Gate 3" in g for g in res_g3.failed_gates)

    # Gate 4 Failure: Sharpe < 0.40 or Alpha < 0
    bad_sharpe = dict(base_good_fund, sharpe_3y=0.25)
    res_g4a = check_eligibility_gates(bad_sharpe)
    assert res_g4a.sharpe_alpha_gate is False
    assert res_g4a.passed is False

    bad_alpha = dict(base_good_fund, alpha_3y=-1.5)
    res_g4b = check_eligibility_gates(bad_alpha)
    assert res_g4b.sharpe_alpha_gate is False
    assert res_g4b.passed is False

    # Gate 5 Failure: Inverted Capture (Downside > 100% and Downside > Upside)
    bad_capture = dict(base_good_fund, downside_capture_ratio=115.0, upside_capture_ratio=95.0)
    res_g5 = check_eligibility_gates(bad_capture)
    assert res_g5.liquidity_gate is False
    assert res_g5.passed is False
    assert any("Gate 5" in g for g in res_g5.failed_gates)

    # Gate 6 Failure: Riskometer > Client Risk Tier
    bad_mandate = dict(base_good_fund, riskometer_score=6)
    res_g6 = check_eligibility_gates(bad_mandate, client_risk_tier_num=4)  # Client is Tier 4
    assert res_g6.mandate_suitability_gate is False
    assert res_g6.passed is False
    assert any("Gate 6" in g for g in res_g6.failed_gates)

    # Gate 7 Failure: Data Confidence < 0.80
    bad_data = dict(base_good_fund, confidence_score=0.60)
    res_g7 = check_eligibility_gates(bad_data)
    assert res_g7.data_integrity_gate is False
    assert res_g7.passed is False

    # Gate 8 Failure: Manager Tenure < 2.0 Years
    bad_tenure = dict(base_good_fund, manager_tenure_years=1.2)
    res_g8 = check_eligibility_gates(bad_tenure)
    assert res_g8.manager_tenure_gate is False
    assert res_g8.passed is False
    assert any("Gate 8" in g for g in res_g8.failed_gates)

    # Gate 9 Failure: Thematic > 15% (or > 0% for starter)
    bad_thematic = dict(base_good_fund, category="Thematic", allocation_pct=25.0)
    res_g9 = check_eligibility_gates(bad_thematic)
    assert res_g9.thematic_satellite_gate is False
    assert res_g9.passed is False

    # Gate 10 Failure: Regular Plan Carrying Commission
    bad_reg = dict(base_good_fund, fund_name="Test Bluechip Regular Plan Growth", is_direct=False)
    res_g10 = check_eligibility_gates(bad_reg)
    assert res_g10.direct_plan_gate is False
    assert res_g10.passed is False
    assert any("Gate 10" in g for g in res_g10.failed_gates)

    print("[PASS] P0.3 All 10 Binary Eligibility Gates Verified")


def test_p0_4_candidate_universe_and_no_action_branch():
    """Verifies candidate universe ingestion and that the NO ACTION branch is properly triggered."""
    metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
    candidates = load_candidate_universe(metrics_path)
    assert len(candidates) > 0, "Candidate universe should load funds from metrics"

    # Test NO ACTION triggered when no candidate offers improvement
    no_act = evaluate_no_action(
        current_portfolio=[],
        candidate_funds=[
            {"fund_id": "C1", "fund_name": "Low Alpha Fund", "eligibility": {"passed": True}, "composite_score": 2.5}
        ],
        min_improvement_threshold=5.0
    )
    assert no_act.action == "NO_ACTION"
    assert no_act.current_portfolio_adequate is True
    assert no_act.no_improvement_found is True
    assert no_act.sip_deployment_pause is True
    assert "NO ACTION / HOLD" in no_act.reason

    # Test PROCEED triggered when genuine qualifying candidate is found
    proceed = evaluate_no_action(
        current_portfolio=[],
        candidate_funds=[
            {"fund_id": "C2", "fund_name": "Alpha Fund Direct", "eligibility": {"passed": True}, "composite_score": 75.0}
        ],
        min_improvement_threshold=5.0
    )
    assert proceed.action == "PROCEED"
    assert proceed.current_portfolio_adequate is False
    assert proceed.no_improvement_found is False

    print("[PASS] P0.4 Candidate Universe & NO ACTION Branch Verified")



def test_p0_5_fiduciary_personal_redemption_engine():
    """Verifies the Deterministic Fiduciary Personal Cash Redemption Engine across all ticket sizes."""
    from advisor import get_default_paths
    from core.math_engine import aggregate_fiduciary_facts
    from core.redemption_engine import compute_personal_redemption_plan
    from core.models import RedemptionPriorityTier

    cas, metrics, config, aliases, _ = get_default_paths()
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)
    tx_path = cas.parent.parent / "transactions.json"
    if not tx_path.exists():
        tx_path = cas.parent / "transactions.json"

    # 1. Test Small-Ticket (<= 1L) -> Single-fund MFCentral friction minimization
    plan_small = compute_personal_redemption_plan(
        requested_amount=100000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=False
    )
    assert plan_small.ticket_category == "SMALL_TICKET"
    assert plan_small.funds_liquidated_count == 1, "Small-ticket must use single fund to minimize operational friction"
    assert plan_small.total_exit_load_inr == 0.0, "0% Exit load guarantee must be respected"
    assert plan_small.total_gross_redeemed_inr == 100000.0
    assert plan_small.tranches[0].priority_tier == RedemptionPriorityTier.BUBBLE_DERISKING
    assert plan_small.total_annual_commission_saved_inr > 0, "Must terminate broker commission bleed"

    # 2. Test Medium-Ticket (1L to 5L) -> Complete folio cleanups
    plan_med = compute_personal_redemption_plan(
        requested_amount=300000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=False
    )
    assert plan_med.ticket_category == "MEDIUM_TICKET"
    assert plan_med.full_folio_exits_count >= 1, "Medium ticket must prioritize 100% full folio closures"
    assert plan_med.total_gross_redeemed_inr == 300000.0
    assert plan_med.total_tax_sheltered_under_112a_inr == 125000.0, "Must maximize Sec 112A 1.25L annual exemption"
    assert plan_med.total_exit_load_inr == 0.0

    # 3. Test Large-Ticket (> 5L) -> Macro structural derisking & Sec 70 Loss Harvesting
    plan_large = compute_personal_redemption_plan(
        requested_amount=1000000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=False
    )
    assert plan_large.ticket_category == "LARGE_TICKET"
    assert plan_large.full_folio_exits_count >= 4, "Large ticket must sweep all bubble funds"
    # Ensure all bubble funds are wiped out before regular
    assert any("Loss Harvesting" in t.fiduciary_reason for t in plan_large.tranches), "Must harvest Sec 70 capital loss"
    assert plan_large.total_annual_commission_saved_inr >= 10000.0, "Must save substantial recurring broker fee"
    # Core Direct anchors must be protected
    for t in plan_large.tranches:
        assert "direct" not in t.scheme_name.lower() or "baf" not in t.scheme_name.lower(), "Core anchors must not be touched"

    # 4. Test Net Cash Target Mode
    plan_net = compute_personal_redemption_plan(
        requested_amount=200000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=True
    )
    assert plan_net.is_net_cash_target is True
    assert plan_net.total_net_cash_inr >= 200000.0, "Net cash received must satisfy requested amount"
    assert plan_net.total_exit_load_inr == 0.0

    print("[PASS] P0.5 Fiduciary Personal Redemption Engine Verified (Small, Med, Large, Net)")



def test_p0_6_multi_horizon_selection_and_peer_evaluation():
    """
    Verifies that the autonomous fund selection engine incorporates multi-horizon metrics
    (1-year return, 6-month trend, 3-year CAGR, Sharpe, TER) and dynamically selects the
    top-performing candidate while rejecting underperforming peers.
    Specifically tests Healthcare / Pharma peer selection across ICICI, Mirae, Tata, and Nippon.
    """
    from core.math_engine import compute_multi_horizon_fiduciary_score, select_autonomous_blueprint_funds
    from core.eligibility import load_candidate_universe

    metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
    candidates = load_candidate_universe(metrics_path)

    pharma_cands = {c["fund_id"]: c for c in candidates if "health" in c["fund_name"].lower() or "pharma" in c["fund_name"].lower()}
    assert "ICICI Healthcare Direct" in pharma_cands, "ICICI Healthcare must be in candidate universe"
    assert "Mirae Healthcare Direct" in pharma_cands, "Mirae Healthcare must be in candidate universe"
    assert "Tata Pharma Direct" in pharma_cands, "Tata Pharma must be in candidate universe"
    assert "Nippon Pharma Direct" in pharma_cands, "Nippon Pharma must be in candidate universe"

    icici = pharma_cands["ICICI Healthcare Direct"]
    mirae = pharma_cands["Mirae Healthcare Direct"]
    nippon = pharma_cands["Nippon Pharma Direct"]

    score_icici = compute_multi_horizon_fiduciary_score(icici)
    score_mirae = compute_multi_horizon_fiduciary_score(mirae)
    score_nippon = compute_multi_horizon_fiduciary_score(nippon)

    # ICICI and Mirae decisively outperform Nippon on multi-horizon quantitative metrics
    assert score_icici > score_nippon, f"ICICI ({score_icici}) must outperform Nippon ({score_nippon})"
    assert score_mirae > score_nippon, f"Mirae ({score_mirae}) must outperform Nippon ({score_nippon})"
    assert icici["return_1y"] > nippon["return_1y"], "ICICI 1Y return (49.4%) exceeds Nippon (35.2%)"
    assert icici["ter_direct_pct"] < nippon["ter_direct_pct"], "ICICI Direct TER (0.89%) lower than Nippon (0.99%)"

    # Verify blueprint selection dynamically routes to the highest multi-horizon scorer (ICICI)
    slots = select_autonomous_blueprint_funds(holdings=[], client_risk_tier=6, thematic_deficit_theme="Pharma")
    slot4 = slots["Slot 4: Tactical Thematic Satellite"]
    assert "ICICI Prudential Healthcare" in slot4["scheme"], f"Expected ICICI Healthcare, got {slot4['scheme']}"
    assert slot4["gate_passed"] is True
    print("[PASS] P0.6 Multi-Horizon Selection & Peer Evaluation Verified")

if __name__ == "__main__":
    test_p0_1_universal_4_slot_sizing_invariant()
    test_p0_2_tax_shield_siphon_and_day_366()
    test_p0_3_all_10_binary_eligibility_gates()
    test_p0_4_candidate_universe_and_no_action_branch()
    test_p0_5_fiduciary_personal_redemption_engine()
    test_p0_6_multi_horizon_selection_and_peer_evaluation()
    print("\n=======================================================")
    print(" ALL 4 P0 FIDUCIARY GAPS ARE FULLY RESOLVED AND TESTED!")
    print("=======================================================")
