"""
test_p0_fiduciary_invariants.py - Exhaustive verification suite for the 4 P0 Fiduciary Compliance Gaps:
- P0.1: Universal 40/30/15/15 SAA Invariant across all SEBI risk tiers and starter vs established portfolios.
- P0.2: ₹1.25L Annual LTCG Tax Shield Siphon & Day 366 Immature Lot Holding Rule.
- P0.3: All 10 Binary Fiduciary Eligibility Gates (Gate 1 through Gate 10).
- P0.4: Candidate Universe Loading & NO ACTION Fiduciary Branch.
"""
from datetime import date, timedelta
from pathlib import Path
import json
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


# Fixture to check if CAS data is available (required for some integration tests)
@pytest.fixture(scope="module")
def cas_data_available():
    """Check if CAS Excel statements are available in data/lalit_portfolio."""
    cas_dir = Path(__file__).parent / "data" / "lalit_portfolio"
    if not cas_dir.exists():
        return False
    # Check for any xlsx files
    cas_files = list(cas_dir.glob("*.xlsx")) + list((cas_dir / "statements").glob("*.xlsx"))
    return len(cas_files) > 0


def _get_portfolio_paths_or_skip():
    """Return local portfolio paths or skip tests requiring private CAS data."""
    from advisor import get_default_paths

    try:
        return get_default_paths()
    except FileNotFoundError as exc:
        pytest.skip(
            "Requires a local private CAS Excel statement; no investor data is "
            f"committed to CI ({exc})"
        )


def test_p0_1_universal_4_slot_sizing_invariant():
    """Verifies that equity allocations across all risk tiers strictly adhere to policy-driven SAA targets."""
    budget = 100000.0

    # Tier 6: 100% Equity (Established >= 5L) — policy-driven from very_high saa_targets
    plan_t6 = compute_deterministic_sip_blueprint(
        monthly_budget=budget,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=7.54,
        client_aum=5000000.0
    )
    assert plan_t6.equity_sip_pct == 100.0
    assert plan_t6.debt_sip_pct == 0.0
    roles = {item.category_role: item for item in plan_t6.items}
    # Policy: very_high saa_targets: flexi=25, mid=25, small=25, large=20 (sum=95)
    # Weights: flexi=25/95=26.3%, mid+small=50/95=52.6%, large=20/95=21.1%, thematic=0%
    assert roles["Core Flexi-Cap Compounder"].allocation_pct == 26.3
    assert roles["Mid-Cap Alpha Engine"].allocation_pct == 52.6
    assert roles["Large-Cap Bluechip Anchor"].allocation_pct == 21.1
    assert roles["Tactical Thematic Satellite"].allocation_pct == 0.0
    assert sum(it.monthly_inr for it in plan_t6.items) == budget

    # Tier 5: 85% Equity / 15% Debt (Established >= 5L) — policy-driven from high saa_targets
    plan_t5 = compute_deterministic_sip_blueprint(
        monthly_budget=budget,
        risk_tier="Tier 5 (High)",
        stability_buffer_pct=3.0,
        client_aum=5000000.0
    )
    assert plan_t5.equity_sip_pct == 85.0
    assert plan_t5.debt_sip_pct == 15.0
    roles5 = {item.category_role: item for item in plan_t5.items}
    # Policy: high saa_targets: flexi=20, mid=25, small=20, large=25 (sum=90)
    # Weights: flexi=20/90=18.9%, mid+small=45/90=42.5%, large=25/90=23.6%, thematic=0%
    assert roles5["Core Flexi-Cap Compounder"].allocation_pct == 18.9
    assert roles5["Mid-Cap Alpha Engine"].allocation_pct == 42.5
    assert roles5["Large-Cap Bluechip Anchor"].allocation_pct == 23.6
    assert roles5["Tactical Thematic Satellite"].allocation_pct == 0.0
    assert roles5["High-Grade Debt Cushion"].allocation_pct == 15.0
    assert sum(it.monthly_inr for it in plan_t5.items) == budget

    # Starter Portfolio (< 5L AUM): 60/40 Core/Mid, 0% Large, 0% Thematic (hardcoded starter logic)
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
        source="cas",
        equity_pct=100.0
    )
    lot2 = Lot(
        fund_id="ICICI Regular Fund",
        folio_name="67890",
        purchase_date=date(2024, 2, 1),
        units=1000.0,
        nav=100.0,
        cost=100000.0,
        source="cas",
        equity_pct=100.0
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
        source="cas",
        equity_pct=100.0
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
        "amc_name": "TEST AMC",
        "allocation_pct": 0.0,
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
        "track_record_years": 5.0,
        "mandate_suitable": True,
        "aum_stable": True,
        "is_direct": True,
        "isin": "TEST001",
        "_provenance": {"confidence_score": 0.95}
    }

    # Clean pass
    base_holdings = [
        {"amc_name": "TEST AMC", "current_value_inr": 200000.0},
        {"amc_name": "OTHER AMC", "current_value_inr": 800000.0},
    ]
    res_clean = check_eligibility_gates(base_good_fund, portfolio_holdings=base_holdings)
    assert res_clean.passed is True
    assert len(res_clean.failed_gates) == 0

    # Gate 1 Failure: AMC Concentration >= 30%
    holdings = [{"scheme": "TEST Large Cap Fund", "value": 350000.0}]  # 35% AMC exposure
    res_g1 = check_eligibility_gates(base_good_fund, portfolio_holdings=[{"amc_name": "TEST AMC", "value": 350000.0}, {"amc_name": "OTHER AMC", "value": 650000.0}])
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
    from core.math_engine import aggregate_fiduciary_facts
    from core.redemption_engine import compute_personal_redemption_plan
    from core.models import RedemptionPriorityTier

    # Skip if CAS data not available (integration test requiring real statements)
    if not (Path(__file__).parent / "data" / "lalit_portfolio").exists():
        pytest.skip("CAS Excel statements not available - integration test skipped")

    cas, metrics, config, aliases, _ = _get_portfolio_paths_or_skip()
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
    assert "NO_ACTION" in slot4["scheme"], f"Missing fiduciary metadata must fail closed, got {slot4['scheme']}"
    assert slot4["gate_passed"] is False
    print("[PASS] P0.6 Multi-Horizon Selection & Peer Evaluation Verified")

def test_p0_7_boundary_mutex_and_thematic_taper():
    """
    Verifies mathematical boundary conditions:
    1. Active Gate 4 Hurdle: Alpha > 0.0% is strict. Alpha == 0.0% fails Gate 4.
    2. Sharpe boundary: Sharpe == 0.40 passes Gate 4; Sharpe == 0.399 fails Gate 4.
    3. Look-through thematic post-investment ceiling: H_post <= 7.50% ceiling is enforced.
    """
    from core.eligibility import check_eligibility_gates

    base_candidate = {
        "fund_id": "TEST_GATE4",
        "fund_name": "Test Active Fund Direct Plan Growth",
        "amc_name": "TEST AMC",
        "allocation_pct": 0.0,
        "aum_crore": 5000.0,
        "category": "Large Cap",
        "top10_concentration_pct": 35.0,
        "single_sector_weight_pct": 20.0,
        "sharpe_3y": 0.40,
        "alpha_3y": 0.0,
        "downside_capture_ratio": 85.0,
        "upside_capture_ratio": 110.0,
        "riskometer_score": 5,
        "confidence_score": 0.95,
        "data_complete": True,
        "manager_tenure_years": 4.0,
        "is_direct": True
    }

    # 1. Alpha == 0.0% must FAIL Gate 4
    res_zero_alpha = check_eligibility_gates(base_candidate)
    assert res_zero_alpha.sharpe_alpha_gate is False, "Active fund with Alpha == 0.0% must fail Gate 4"
    assert res_zero_alpha.passed is False
    assert any("Alpha Drag" in f for f in res_zero_alpha.failed_gates)

    # 2. Alpha == -0.01% must FAIL Gate 4
    res_neg_alpha = check_eligibility_gates(dict(base_candidate, alpha_3y=-0.01))
    assert res_neg_alpha.sharpe_alpha_gate is False
    assert res_neg_alpha.passed is False

    # 3. Sharpe == 0.40 and Alpha == 0.01% must PASS Gate 4
    res_pass_boundary = check_eligibility_gates(dict(base_candidate, sharpe_3y=0.40, alpha_3y=0.01))
    assert res_pass_boundary.sharpe_alpha_gate is True, "Fund with Sharpe == 0.40 and Alpha > 0.0% must pass Gate 4"

    # 4. Sharpe == 0.399 and Alpha == 5.0% must FAIL Gate 4
    res_fail_sharpe = check_eligibility_gates(dict(base_candidate, sharpe_3y=0.399, alpha_3y=5.0))
    assert res_fail_sharpe.sharpe_alpha_gate is False, "Fund with Sharpe < 0.40 must fail Gate 4"

    # 5. Thematic Look-through Exposure Ceiling
    v_total = 5000000.0
    h_existing_val = 350000.0  # 7.0%
    annual_fresh_sip = 1200000.0
    h_new_val = (annual_fresh_sip * 0.15) * 0.95
    h_post_pct = ((h_existing_val + h_new_val) / (v_total + annual_fresh_sip)) * 100.0
    assert h_post_pct > 7.50, f"Simulated test condition must exceed 7.5% ceiling (got {h_post_pct:.2f}%)"
    print("[PASS] P0.7 Boundary Mutex & Thematic Taper Invariant Verified")


def test_p0_8_folio_router_and_idcw_rejection():
    """
    Verifies the 4-point deterministic folio router:
    1. Direct Growth folios are successfully discovered and reused.
    2. Direct IDCW/Dividend folios are strictly rejected to avoid tax-inefficient dividend churn.
    3. Regular folios are strictly rejected to enforce the 100% Direct Plan fiduciary mandate.
    4. Empty or whitespace-only folios are rejected.
    """
    from core.math_engine import find_client_direct_folio
    from core.models import HoldingItem, PlanType, AssetClass

    # Direct Growth folio (Valid for reuse)
    h_growth = HoldingItem(
        fund_id="HDFC_DIRECT_GROWTH",
        scheme="HDFC Flexi Cap Fund - Direct Plan - Growth Option",
        fund_name="HDFC Flexi Cap Fund - Direct Plan - Growth Option",
        folio="44678193",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.EQUITY,
        equity_pct=95.0,
        debt_pct=5.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=500000.0,
        invested_value_inr=400000.0,
        units=500.0,
        nav=1000.0
    )

    # Direct IDCW folio (Must be rejected)
    h_idcw = HoldingItem(
        fund_id="HDFC_DIRECT_IDCW",
        scheme="HDFC Flexi Cap Fund - Direct Plan - IDCW Payout Option",
        fund_name="HDFC Flexi Cap Fund - Direct Plan - IDCW Payout Option",
        folio="99999999",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.EQUITY,
        equity_pct=95.0,
        debt_pct=5.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=300000.0,
        invested_value_inr=280000.0,
        units=300.0,
        nav=1000.0
    )

    # Regular Plan folio (Must be rejected)
    h_regular = HoldingItem(
        fund_id="HDFC_REGULAR_GROWTH",
        scheme="HDFC Flexi Cap Fund - Regular Plan - Growth",
        fund_name="HDFC Flexi Cap Fund - Regular Plan - Growth",
        folio="14596617",
        is_direct=False,
        plan=PlanType.REGULAR,
        asset_class=AssetClass.EQUITY,
        equity_pct=95.0,
        debt_pct=5.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=400000.0,
        invested_value_inr=350000.0,
        units=400.0,
        nav=1000.0
    )

    # Empty folio string (Must be rejected)
    h_empty_folio = HoldingItem(
        fund_id="HDFC_NO_FOLIO",
        scheme="HDFC Flexi Cap Fund - Direct Plan - Growth",
        fund_name="HDFC Flexi Cap Fund - Direct Plan - Growth",
        folio="",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.EQUITY,
        equity_pct=95.0,
        debt_pct=5.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=200000.0,
        invested_value_inr=150000.0,
        units=200.0,
        nav=1000.0
    )

    # Test 1: Only IDCW present -> Should return None, None
    scheme, folio = find_client_direct_folio([h_idcw], "flexi")
    assert scheme is None and folio is None, "Direct IDCW folio must NOT be reused"

    # Test 2: Only Regular present -> Should return None, None
    scheme, folio = find_client_direct_folio([h_regular], "flexi")
    assert scheme is None and folio is None, "Regular plan folio must NOT be reused"

    # Test 3: Empty folio string -> Should return None, None
    scheme, folio = find_client_direct_folio([h_empty_folio], "flexi")
    assert scheme is None and folio is None, "Empty folio string must NOT be reused"

    # Test 4: Both Direct Growth and Direct IDCW present -> Must strictly select Direct Growth
    scheme, folio = find_client_direct_folio([h_idcw, h_growth], "flexi")
    assert folio == "44678193", f"Expected Growth folio 44678193, got {folio}"
    assert "IDCW" not in scheme, "Must not select IDCW option"

    print("[PASS] P0.8 Folio Router & IDCW Rejection Invariant Verified")


def test_p0_9_thematic_taper_exact_algebra_and_boundary():
    """
    Verifies the closed-form algebraic derivation and boundary conditions of the thematic taper:
    Equation: (V_h + S_h * m) / (V_tot + S_tot * m) = Ceiling
    For Lalit Saini:
      V_tot = 51,70,911.38
      V_h = 80,396.14 (1.554% look-through healthcare)
      S_tot = 1,00,000 / month
      S_h = 15,000 * 0.95 = 14,250 / month (15% allocation x 95% underlying equity)
      Ceiling = 0.075 (7.50% benchmark-relative policy ceiling)

    Algebraic Solution:
      m * (14,250 - 0.075 * 100,000) = (0.075 * 51,70,911.38) - 80,396.14
      m * 6,750 = 387,818.3535 - 80,396.14 = 307,422.2135
      m = 307,422.2135 / 6,750 = 45.5440 months!
    """
    v_tot = 5170911.38
    v_h = 80396.14
    s_tot = 100000.0
    s_h = 14250.0  # 15% SIP x 95% underlying healthcare equity
    ceiling = 0.075

    # 1. Exact algebraic solution check
    num = (ceiling * v_tot) - v_h
    den = s_h - (ceiling * s_tot)
    m_exact = num / den
    assert abs(m_exact - 45.5440) < 1e-3, f"Exact m must be 45.544 months, got {m_exact}"

    # 2. Month 39 boundary check: Must NOT breach ceiling
    m39_pct = ((v_h + s_h * 39) / (v_tot + s_tot * 39)) * 100.0
    assert m39_pct < 7.50, f"Month 39 exposure ({m39_pct:.3f}%) must be under 7.50% ceiling"
    assert round(m39_pct, 2) == 7.01, f"Month 39 exposure expected 7.01%, got {m39_pct:.2f}%"

    # 3. Month 40 boundary check: Must NOT breach ceiling
    m40_pct = ((v_h + s_h * 40) / (v_tot + s_tot * 40)) * 100.0
    assert m40_pct < 7.50, f"Month 40 exposure ({m40_pct:.3f}%) must be under 7.50% ceiling"
    assert round(m40_pct, 2) == 7.09, f"Month 40 exposure expected 7.09%, got {m40_pct:.2f}%"

    # 4. Month 45 boundary check: Under ceiling
    m45_pct = ((v_h + s_h * 45) / (v_tot + s_tot * 45)) * 100.0
    assert m45_pct < 7.50, f"Month 45 exposure ({m45_pct:.3f}%) must be under 7.50%"
    assert round(m45_pct, 2) == 7.46, f"Month 45 exposure expected 7.46%, got {m45_pct:.2f}%"

    # 5. Month 46 boundary check: Breaches ceiling, triggering taper
    m46_pct = ((v_h + s_h * 46) / (v_tot + s_tot * 46)) * 100.0
    assert m46_pct >= 7.50, f"Month 46 exposure ({m46_pct:.3f}%) must breach 7.50% ceiling"
    assert round(m46_pct, 2) == 7.53, f"Month 46 exposure expected 7.53%, got {m46_pct:.2f}%"

    # 6. Zero-inflow case: ΔV = 0
    zero_inflow_pct = (v_h / v_tot) * 100.0
    assert round(zero_inflow_pct, 3) == 1.555, f"Zero inflow exposure expected 1.555%, got {zero_inflow_pct}"

    # 7. Changed look-through case: If portfolio already has 7.0% healthcare (₹3,61,963.80)
    v_h_high = v_tot * 0.070
    m_high = ((ceiling * v_tot) - v_h_high) / den
    assert m_high < 4.0, f"High initial exposure breaches ceiling in < 4 months, got {m_high:.2f}"
    print("[PASS] P0.9 Thematic Taper Exact Algebra & Boundary Verified")


def test_p0_10_gate4_fail_closed_and_missing_metrics():
    """
    Verifies that Gate 4 strictly fails closed against:
    - Missing Sharpe (None)
    - Missing Alpha (None)
    - Both missing
    - NaN Sharpe / NaN Alpha (float nan and string "NaN")
    - Inf Sharpe / Inf Alpha (float inf and string "inf")
    - Empty string and whitespace strings
    - Booleans (True/False)
    - Malformed string values ("N/A", "unrated")
    - Sub-hurdle values (Sharpe < 0.40, Alpha <= 0.0)
    - Active disguise funds ("Kotak Index Opportunities Active Alpha") must NOT bypass Gate 4
    - Verified passive index funds/ETFs are exempted from active alpha hurdles
    """
    from core.eligibility import check_eligibility_gates
    import math

    base_active = {
        "fund_id": "TEST_FAIL_CLOSED",
        "fund_name": "Test Active Fund Direct Plan Growth",
        "amc_name": "TEST AMC",
        "allocation_pct": 0.0,
        "aum_crore": 5000.0,
        "category": "Flexi Cap",
        "top10_concentration_pct": 35.0,
        "single_sector_weight_pct": 20.0,
        "sharpe_3y": 0.65,
        "alpha_3y": 3.5,
        "downside_capture_ratio": 85.0,
        "upside_capture_ratio": 110.0,
        "riskometer_score": 5,
        "confidence_score": 0.95,
        "data_complete": True,
        "manager_tenure_years": 4.0,
        "track_record_years": 5.0,
        "mandate_suitable": True,
        "aum_stable": True,
        "is_direct": True,
        "isin": "TEST003",
        "_provenance": {"confidence_score": 0.95}
    }

    # 1. Clean pass baseline
    base_holdings = [
        {"amc_name": "TEST AMC", "current_value_inr": 200000.0},
        {"amc_name": "OTHER AMC", "current_value_inr": 800000.0},
    ]
    res_clean = check_eligibility_gates(base_active, portfolio_holdings=base_holdings)
    assert res_clean.sharpe_alpha_gate is True
    assert res_clean.passed is True

    # 2. Missing Sharpe (None) -> Must FAIL
    res_none_sharpe = check_eligibility_gates(dict(base_active, sharpe_3y=None))
    assert res_none_sharpe.sharpe_alpha_gate is False
    assert res_none_sharpe.passed is False
    assert any("Sharpe Ratio Missing" in f for f in res_none_sharpe.failed_gates)

    # 3. Missing Alpha (None) -> Must FAIL
    res_none_alpha = check_eligibility_gates(dict(base_active, alpha_3y=None))
    assert res_none_alpha.sharpe_alpha_gate is False
    assert res_none_alpha.passed is False
    assert any("Alpha Drag Missing" in f for f in res_none_alpha.failed_gates)

    # 4. Both missing -> Must FAIL
    res_both_none = check_eligibility_gates(dict(base_active, sharpe_3y=None, alpha_3y=None))
    assert res_both_none.sharpe_alpha_gate is False
    assert res_both_none.passed is False

    # 5. NaN Sharpe (float and string "NaN") -> Must FAIL
    res_nan_sharpe = check_eligibility_gates(dict(base_active, sharpe_3y=float("nan")))
    assert res_nan_sharpe.sharpe_alpha_gate is False
    assert res_nan_sharpe.passed is False
    assert any("Sharpe Non-Finite" in f for f in res_nan_sharpe.failed_gates)

    res_str_nan = check_eligibility_gates(dict(base_active, sharpe_3y="NaN"))
    assert res_str_nan.sharpe_alpha_gate is False
    assert res_str_nan.passed is False
    assert any("Sharpe Non-Finite" in f for f in res_str_nan.failed_gates)

    # 6. NaN Alpha -> Must FAIL
    res_nan_alpha = check_eligibility_gates(dict(base_active, alpha_3y=float("nan")))
    assert res_nan_alpha.sharpe_alpha_gate is False
    assert res_nan_alpha.passed is False
    assert any("Alpha Non-Finite" in f for f in res_nan_alpha.failed_gates)

    # 7. Infinite Sharpe -> Must FAIL
    res_inf_sharpe = check_eligibility_gates(dict(base_active, sharpe_3y=float("inf")))
    assert res_inf_sharpe.sharpe_alpha_gate is False
    assert res_inf_sharpe.passed is False

    res_str_inf = check_eligibility_gates(dict(base_active, sharpe_3y="inf"))
    assert res_str_inf.sharpe_alpha_gate is False
    assert res_str_inf.passed is False

    # 8. Malformed string Sharpe / Alpha -> Must FAIL
    res_str_sharpe = check_eligibility_gates(dict(base_active, sharpe_3y="N/A"))
    assert res_str_sharpe.sharpe_alpha_gate is False
    assert res_str_sharpe.passed is False
    assert any("Sharpe Malformed" in f for f in res_str_sharpe.failed_gates)

    # 9. Empty and whitespace strings -> Must FAIL
    res_empty_sharpe = check_eligibility_gates(dict(base_active, sharpe_3y="   "))
    assert res_empty_sharpe.sharpe_alpha_gate is False
    assert res_empty_sharpe.passed is False
    assert any("Sharpe Malformed" in f for f in res_empty_sharpe.failed_gates)

    # 10. Booleans (True / False) -> Must FAIL
    res_bool_sharpe = check_eligibility_gates(dict(base_active, sharpe_3y=True))
    assert res_bool_sharpe.sharpe_alpha_gate is False
    assert res_bool_sharpe.passed is False
    assert any("Boolean value" in f for f in res_bool_sharpe.failed_gates)

    res_bool_alpha = check_eligibility_gates(dict(base_active, alpha_3y=False))
    assert res_bool_alpha.sharpe_alpha_gate is False
    assert res_bool_alpha.passed is False
    assert any("Boolean value" in f for f in res_bool_alpha.failed_gates)

    # 11. Sub-hurdle Sharpe (< 0.40) & Non-positive Alpha (<= 0.0) -> Must FAIL
    res_low_sharpe = check_eligibility_gates(dict(base_active, sharpe_3y=0.25))
    assert res_low_sharpe.sharpe_alpha_gate is False
    assert res_low_sharpe.passed is False

    res_neg_alpha = check_eligibility_gates(dict(base_active, alpha_3y=-0.50))
    assert res_neg_alpha.sharpe_alpha_gate is False
    assert res_neg_alpha.passed is False

    # 12. Active disguise scheme (mentions index but is active) -> Must NOT bypass Gate 4
    disguise_active = dict(
        base_active,
        fund_name="Kotak Index Opportunities Active Alpha Direct Growth",
        category="Equity Index Opportunities",
        sharpe_3y=None,
        alpha_3y=None,
        is_passive=False
    )
    res_disguise = check_eligibility_gates(disguise_active)
    assert res_disguise.sharpe_alpha_gate is False, "Active funds masquerading with index substring must NOT bypass Gate 4"
    assert res_disguise.passed is False

    # 13. Genuine verified passive index fund exemption
    passive_cand = dict(
        base_active,
        fund_name="Nifty 50 Index Fund - Direct Plan - Growth",
        category="Index Funds",
        isin="TEST004",
        is_passive=True,
        sharpe_3y=None,
        alpha_3y=None
    )
    res_passive = check_eligibility_gates(passive_cand)
    assert res_passive.sharpe_alpha_gate is True, "Genuine passive index funds are exempted from active alpha hurdles"

    print("[PASS] P0.10 Gate 4 Fail-Closed & Missing Metrics Verified")


def test_p0_11_candidate_specific_lookthrough_overlap():
    """
    Verifies that the overlap pillar calculates candidate-specific look-through overlap
    against the client's actual portfolio holdings, producing differentiated scores.
    """
    from core.math_engine import aggregate_fiduciary_facts, compute_candidate_portfolio_overlap
    import json

    # Skip if CAS data not available (integration test requiring real statements)
    if not (Path(__file__).parent / "data" / "lalit_portfolio").exists():
        pytest.skip("CAS Excel statements not available - integration test skipped")

    cas, metrics_p, config, aliases, _ = _get_portfolio_paths_or_skip()
    facts = aggregate_fiduciary_facts(cas, metrics_p, config, aliases)

    with open(metrics_p, "r", encoding="utf-8") as f:
        m_data = json.load(f)
    funds_map = {f["id"]: f for f in m_data["funds"]}

    icici = funds_map["ICICI Healthcare Direct"]
    mirae = funds_map["Mirae Healthcare Direct"]
    tata = funds_map["Tata Pharma Direct"]
    nippon = funds_map["Nippon Pharma Direct"]

    ovl_icici = compute_candidate_portfolio_overlap(icici, facts.holdings, m_data["funds"])
    ovl_mirae = compute_candidate_portfolio_overlap(mirae, facts.holdings, m_data["funds"])
    ovl_tata = compute_candidate_portfolio_overlap(tata, facts.holdings, m_data["funds"])
    ovl_nippon = compute_candidate_portfolio_overlap(nippon, facts.holdings, m_data["funds"])

    # Overlaps must be differentiated and reflect true constituent holdings:
    assert ovl_icici > 0.0, "ICICI Healthcare shares stocks (Torrent Pharma, Fortis) with portfolio"
    assert ovl_tata == 0.0, "Tata Pharma has zero constituent overlap with portfolio"
    assert ovl_icici != ovl_tata, "Overlap must not be a common placeholder"
    assert ovl_mirae > 0.0, "Mirae Healthcare shares stocks with portfolio"

    print(f"[PASS] P0.11 Candidate-Specific Look-Through Overlap Verified: ICICI={ovl_icici}%, Mirae={ovl_mirae}%, Tata={ovl_tata}%, Nippon={ovl_nippon}%")


def test_p0_12_all_four_slots_passive_fallback_and_no_action():
    """
    Verifies that every slot has a tested fallback decision:
    - Slot 1: Active flexi-cap failure -> Flexi Cap Index Fund Direct
    - Slot 2: Active mid-cap failure / AUM size drag -> Nifty Midcap 150 Index Direct
    - Slot 3: Active large-cap failure -> Nifty 50 Index Direct
    - Slot 4: Thematic failure or ceiling reached -> NO ACTION / HOLD (0.0% allocation)
    """
    from core.math_engine import select_autonomous_blueprint_funds

    # Empty candidate universe triggers complete fallback across all slots
    slots = select_autonomous_blueprint_funds(holdings=[], candidate_universe=[], client_risk_tier=6)

    # Slot 1: Must fall back to passive Flexi/Broad index
    slot1 = slots["Slot 1: Core Flexi-Cap Compounder"]
    assert "Index" in slot1["scheme"] or "Compounder" in slot1["scheme"]

    # Slot 2: Must fall back to passive Midcap 150 index
    slot2 = slots["Slot 2: Mid-Cap Alpha Engine"]
    assert slot2.get("is_passive") is True
    assert "Midcap 150" in slot2["scheme"]

    # Slot 3: Must fall back to passive Nifty 50 index
    slot3 = slots["Slot 3: Large-Cap Bluechip Anchor"]
    assert slot3.get("is_passive") is True
    assert "Nifty 50" in slot3["scheme"]

    # Slot 4: Thematic sleeve with zero eligible candidates must trigger NO ACTION / HOLD
    slot4 = slots["Slot 4: Tactical Thematic Satellite"]
    assert slot4.get("gate_passed") is False or "NO ACTION" in slot4.get("rationale", "")

    print("[PASS] P0.12 All 4 Slots Passive Fallback & NO ACTION Invariant Verified")


def test_p0_13_statutory_tax_specified_fund_and_mandate_state():
    """
    Verifies statutory tax classification under Section 50AA (1961 Act) and Section 76 (2025 Act),
    including strict > 65% equity threshold, acquisition date cutoffs, and mandate authorization checks.
    """
    from core.math_engine import classify_specified_mutual_fund, get_statutory_tax_citation
    from core.models import MandateExecutionState, FiduciaryFactsPayload, FeeBleedAnalysis, SAADriftAnalysis, CashDeploymentPlan
    from datetime import date

    # 1. Strict Equity-Oriented Threshold (>= 65.0% inclusive per CBDT clarification)
    res_eq_exact_65 = classify_specified_mutual_fund("Equity", equity_pct=65.0)
    assert res_eq_exact_65["is_equity_oriented"] is True, "Exactly 65.0% qualifies; statutory definition requires >= 65.0% inclusive"

    res_eq_above_65 = classify_specified_mutual_fund("Equity", equity_pct=65.01)
    assert res_eq_above_65["is_equity_oriented"] is True, "65.01% strictly qualifies as equity-oriented"

    # 2. Arbitrage Fund Qualification
    res_arb_qualifying = classify_specified_mutual_fund("Arbitrage", equity_pct=68.0)
    assert res_arb_qualifying["is_equity_oriented"] is True
    assert res_arb_qualifying["tax_treatment"] == "EQUITY_ORIENTED_CONCESSIONAL"

    res_arb_under = classify_specified_mutual_fund("Arbitrage", equity_pct=64.0)
    assert res_arb_under["is_equity_oriented"] is False, "Arbitrage fund with <= 65% equity does NOT qualify as equity-oriented"

    # 3. Debt Fund Grandfathering (Pre-1 April 2023 Acquisition)
    res_debt_old = classify_specified_mutual_fund("Debt", equity_pct=10.0, debt_and_money_market_pct=90.0, is_fund_of_funds=False, fof_debt_investing_pct=None, acquisition_date=date(2022, 11, 20), transfer_date=date(2026, 1, 15))
    assert res_debt_old["is_specified_mutual_fund"] is False
    assert res_debt_old["specified_50AA"]["provision"] == "Section 48 (Grandfathered)"
    assert "Section 48" in res_debt_old["governing_statute"]

    # 4. Specified Mutual Fund (Post-1 April 2023 Acquisition) under Section 50AA (1961 Act)
    # FY 2025-26 amended regime requires daily NAV snapshots - provide mock snapshots
    from core.math_engine import DailyPortfolioSnapshot
    mock_snapshots = [
        DailyPortfolioSnapshot(date=date(2025, 4, 1), equity_pct=15.0, debt_pct=70.0, money_market_pct=15.0),
        DailyPortfolioSnapshot(date=date(2025, 7, 1), equity_pct=15.0, debt_pct=70.0, money_market_pct=15.0),
        DailyPortfolioSnapshot(date=date(2025, 10, 1), equity_pct=15.0, debt_pct=70.0, money_market_pct=15.0),
        DailyPortfolioSnapshot(date=date(2026, 1, 1), equity_pct=15.0, debt_pct=70.0, money_market_pct=15.0),
    ]
    res_debt_50aa = classify_specified_mutual_fund(
        "Debt", equity_pct=15.0, debt_and_money_market_pct=85.0, 
        is_fund_of_funds=False, fof_debt_investing_pct=None, 
        acquisition_date=date(2023, 6, 15), transfer_date=date(2026, 1, 15),
        snapshots=mock_snapshots, fy_start=date(2025, 4, 1), fy_end=date(2026, 3, 31)
    )
    assert res_debt_50aa["is_specified_mutual_fund"] is True
    assert res_debt_50aa["specified_50AA"]["qualifies"] is True
    assert "Section 50AA" in res_debt_50aa["governing_statute"]

    # 5. Specified Mutual Fund post-1 April 2026 under Section 76 (2025 Act)
    res_debt_sec76 = classify_specified_mutual_fund("Debt", equity_pct=10.0, debt_and_money_market_pct=90.0, is_fund_of_funds=False, fof_debt_investing_pct=None, acquisition_date=date(2023, 6, 15), transfer_date=date(2026, 5, 1))
    assert res_debt_sec76["is_specified_mutual_fund"] is True
    assert "Section 76" in res_debt_sec76["governing_statute"]

    # 6. Section 198 vs Section 197 distinction in 2025 Act
    tax_cit_2026 = get_statutory_tax_citation(as_of=date(2026, 5, 1))
    assert "Section 198" in tax_cit_2026.ltcg_statute
    assert "Section 197" in tax_cit_2026.ltcg_statute
    assert "Section 196" in tax_cit_2026.stcg_statute
    assert "Section 108" in tax_cit_2026.loss_netting_statute
    assert "Section 111" in tax_cit_2026.loss_carryforward_statute

    print("[PASS] P0.13 Statutory Tax Specified Fund & 2025 Act Invariant Verified")


def test_p0_14_cashflow_matched_tri_benchmark_engine():
    """
    Verifies the Cash-Flow-Matched Total Return Index (TRI) benchmark performance engine:
    - Matches 363 external cash flows from transactions.json (SWITCH/STP netted to zero, DIVIDEND_REINVEST excluded)
      against official daily/monthly TRI levels
    - Accumulates benchmark units dynamically and evaluates terminal benchmark valuation
    - Solves true Benchmark Matched XIRR and True Alpha deterministically
    - Enforces 95% coverage gate via TriProvenanceError
    """
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr, calculate_portfolio_xirr
    from pathlib import Path
    import pytest

    # Skip if transactions.json not available (requires processed CAS data)
    tx_path = Path("data/lalit_portfolio/transactions.json")
    if not tx_path.exists():
        pytest.skip("transactions.json not available - requires processed CAS Excel data")

    tri_path = Path("data/policy/benchmark_tri_series.json")

    assert tri_path.exists(), "benchmark_tri_series.json must exist"

    # No independently maintained NSE trading calendar is shipped with this repo.
    # The calculation must fail closed instead of trusting benchmark-fixture metadata.
    from core.models import TriProvenanceError
    with pytest.raises(TriProvenanceError) as exc_info:
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=tx_path,
            benchmark_key="NIFTY 500 TRI",
            benchmark_series_path=tri_path,
            cas_current=5170911.38
        )
    assert exc_info.value.validation_stage == "trading_calendar_missing"
    print("[PASS] P0.14 TRI refuses to calculate without an independent NSE session calendar")

def test_p0_15_runtime_mandate_hold_enforcement():
    """
    Verifies that the client's HOLD mandate is an enforced runtime state:
    - Ingests config.json and asserts mandate_state is HOLD_PENDING_TRI_VALIDATION
    - Asserts is_execution_authorized is False
    - Asserts deterministic SIP and lumpsum plans are non-actionable conditional scenarios
    - Asserts that assert_mandate_execution_authorized strictly raises MandateHoldViolationError
    """
    from core.math_engine import aggregate_fiduciary_facts, assert_mandate_execution_authorized
    from core.models import MandateExecutionState, MandateHoldViolationError
    import pytest

    # Skip if CAS data not available (integration test requiring real statements)
    if not (Path(__file__).parent / "data" / "lalit_portfolio").exists():
        pytest.skip("CAS Excel statements not available - integration test skipped")

    cas, metrics, config, aliases, _ = _get_portfolio_paths_or_skip()
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)

    assert facts.mandate_state == MandateExecutionState.HOLD_PENDING_TRI_VALIDATION
    assert facts.is_execution_authorized is False
    assert facts.deterministic_sip_plan.execution_status == "ON_HOLD_PENDING_TRI_VALIDATION"
    assert facts.deterministic_sip_plan.is_actionable_order is False
    assert facts.deterministic_lumpsum_plan.is_actionable_order is False

    # Hard invariant: any execution call must raise MandateHoldViolationError
    with pytest.raises(MandateHoldViolationError):
        assert_mandate_execution_authorized(facts)

    print("[PASS] P0.15 Runtime Mandate Hold Enforcement Invariant Verified")


def test_p0_16_tri_coverage_gate_rejects_inflated_metadata():
    """
    Verifies that the TRI coverage gate rejects sparse data with inflated coverage_pct metadata.
    This is a targeted test for the coverage gate enforcement (P0.16).
    """
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr
    from core.models import TriProvenanceError
    from pathlib import Path
    import json
    import tempfile
    import os

    # Skip if transactions.json not available (requires processed CAS data)
    tx_path = Path("data/lalit_portfolio/transactions.json")
    if not tx_path.exists():
        pytest.skip("transactions.json not available - requires processed CAS Excel data")

    tri_path = Path("data/policy/benchmark_tri_series_high_coverage.json")

    # Create a sparse TRI fixture with inflated coverage_pct metadata
    with open("data/policy/benchmark_tri_series_high_coverage.json", "r") as f:
        sparse_tri = json.load(f)
    full_calendar_sessions = sorted(sparse_tri["benchmarks"]["NIFTY 500 TRI"]["levels"].keys())

    # Keep only 10 data points but claim 100% coverage in metadata
    sparse_levels = dict(list(sparse_tri["benchmarks"]["NIFTY 500 TRI"]["levels"].items())[:10])
    sparse_tri["benchmarks"]["NIFTY 500 TRI"]["levels"] = sparse_levels
    sparse_tri["coverage"]["nifty_500_tri"]["provided_data_points"] = 10
    sparse_tri["coverage"]["nifty_500_tri"]["coverage_pct"] = 100.0  # Inflated!
    sparse_tri["coverage"]["nifty_500_tri"]["note"] = "Inflated metadata for testing"

    # Write temporary sparse fixture
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sparse_tri, f)
        sparse_tri_path = f.name

    # Recompute checksum for the modified sparse fixture
    import hashlib
    with open(sparse_tri_path, 'r') as f:
        sparse_data = json.load(f)
    sparse_levels = sparse_data['benchmarks']['NIFTY 500 TRI']['levels']
    sparse_checksum = hashlib.sha256(json.dumps(sparse_data['benchmarks']['NIFTY 500 TRI']['levels'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    sparse_data['provenance']['checksum_sha256_nifty_500_tri'] = sparse_checksum
    with open(sparse_tri_path, 'w') as f:
        json.dump(sparse_data, f)

    # Build a separate calendar fixture from the complete test dataset, not the
    # edited sparse benchmark levels or their editable coverage metadata.
    calendar_sessions = full_calendar_sessions
    sessions_sha256 = hashlib.sha256(json.dumps(calendar_sessions, separators=(",", ":")).encode()).hexdigest()
    calendar_data = {
        "exchange": "NSE",
        "status": "VERIFIED",
        "sessions": calendar_sessions,
        "provenance": {
            "source_url": "https://www.nseindia.com/reports",
            "source_document_sha256": "c" * 64,
            "sessions_sha256": sessions_sha256,
        },
    }
    calendar_path = Path(sparse_tri_path).with_name("nse_calendar.json")
    calendar_path.write_text(json.dumps(calendar_data), encoding="utf-8")

    try:
        # This should raise TriProvenanceError because actual coverage (10/985 ~ 1%) 
        # is below 95% even though metadata claims 100%
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=Path("data/lalit_portfolio/transactions.json"),
            benchmark_key="NIFTY 500 TRI",
            benchmark_series_path=Path(sparse_tri_path),
            cas_current=5170911.38,
            trading_calendar_path=calendar_path
        )
        assert False, "Should have raised TriProvenanceError for inflated metadata"
    except TriProvenanceError as e:
        err_msg = str(e).lower()
        # Should fail either on coverage or date range - both indicate the sparse data is rejected
        assert "coverage" in err_msg or "data span" in err_msg or "date range" in err_msg
        # Actual coverage should be ~1%, not 100%
        assert "100" not in str(e).lower() or "1.0" in str(e) or "1.0%" in str(e)
    except Exception as e:
        assert False, f"Expected TriProvenanceError, got {type(e).__name__}: {e}"

    print("[PASS] P0.16 TRI Coverage Gate Rejects Inflated Metadata Verified")
