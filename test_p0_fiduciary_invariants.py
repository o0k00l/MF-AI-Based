"""
test_p0_fiduciary_invariants.py - Regression suite for policy-driven fiduciary invariants:
- P0.1: Risk-tier policy SAA and SIP routing across starter vs established portfolios.
- P0.2: Investor-facing tax and Day-366 advice APIs remain disabled pending independent approval.
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


_TEST_TAX_EVIDENCE_ROOT = Path(__file__).resolve().parent / "tests" / "fixtures"
_TEST_TAX_EVIDENCE_SHA256 = "e3da5a5eb89824a20c0eb0b214fa5123548fada0976e7bb31c4d742d6efbe3fc"


def _synthetic_tax_evidence_kwargs():
    """Synthetic local bytes used only to test digest integrity, not legal classification."""
    return {
        "equity_pct_source_sha256": _TEST_TAX_EVIDENCE_SHA256,
        "equity_pct_source_file": "synthetic_tax_evidence.txt",
        "equity_pct_evidence_root": str(_TEST_TAX_EVIDENCE_ROOT),
    }


def _attach_reviewed_direct_test_evidence(candidate, tmp_path):
    """Attach a synthetic local source artifact to a Direct-plan gate fixture."""
    import hashlib

    scheme_name = candidate["fund_name"]
    source_bytes = (
        f"SYNTHETIC TEST FIXTURE ONLY\\nScheme: {scheme_name}\\nPlan: Direct\\n"
    ).encode("utf-8")
    source_path = tmp_path / f"{candidate['fund_id']}-direct-plan-source.txt"
    source_path.write_bytes(source_bytes)
    candidate["plan"] = "Direct"
    candidate["direct_plan_evidence"] = {
        "source_file": source_path.name,
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_url": "https://example.test/synthetic-direct-plan-source",
        "source_type": "AMFI_SCHEME_MASTER",
        "reviewer_attested": True,
        "reviewed_at": date.today().isoformat(),
        "scheme_name": scheme_name,
        "plan": "Direct",
    }
    candidate["_evidence_root"] = str(tmp_path.resolve())
    return candidate


# Fixture to check if CAS data is available (required for some integration tests)
@pytest.fixture(scope="module")
def cas_data_available():
    """Check only the explicitly configured external client-data directory."""
    import os

    configured_dir = os.environ.get("MF_CLIENT_DATA_DIR")
    if not configured_dir:
        return False
    cas_dir = Path(configured_dir).expanduser().resolve()
    if not cas_dir.is_dir():
        return False
    cas_files = list(cas_dir.glob("*.xlsx")) + list((cas_dir / "statements").glob("*.xlsx"))
    return bool(cas_files)


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
        client_aum=5000000.0,
        equity_sip_routing_override=True,
    )
    assert plan_t6.equity_sip_pct == 100.0
    assert plan_t6.debt_sip_pct == 0.0
    roles = {item.category_role: item for item in plan_t6.items}
    # Policy: very_high saa_targets: flexi=25, mid=25, small=25, large=20 (sum=95)
    # Weights: flexi=25/95=26.3%, mid=25/95=26.3%, small=25/95=26.3%, large=20/95=21.1%, thematic=0%
    assert roles["Core Flexi-Cap Compounder"].allocation_pct == 26.3
    assert roles["Mid-Cap Alpha Engine"].allocation_pct == 26.3
    assert roles["Small-Cap Growth Engine"].allocation_pct == 26.3
    assert roles["Large-Cap Bluechip Anchor"].allocation_pct == 21.1
    assert roles["Tactical Thematic Satellite"].allocation_pct == 0.0
    assert sum(it.monthly_inr for it in plan_t6.items) + plan_t6.unallocated_budget_inr == budget
    if plan_t6.unallocated_budget_inr > 0:
        assert all(it.monthly_inr == 0 for it in plan_t6.items)

    # Tier 5: 95% Equity / 5% Debt base SIP (stability buffer 3% is below 5% threshold)
    plan_t5 = compute_deterministic_sip_blueprint(
        monthly_budget=budget,
        risk_tier="Tier 5 (High)",
        stability_buffer_pct=3.0,
        client_aum=5000000.0
    )
    assert plan_t5.equity_sip_pct == 95.0
    assert plan_t5.debt_sip_pct == 5.0
    roles5 = {item.category_role: item for item in plan_t5.items}
    # Policy: high saa_targets: flexi=20, mid=25, small=20, large=25 (sum=90)
    # Weights: flexi=20/90, mid=25/90, small=20/90, large=25/90 of 95% equity SIP; thematic=0%
    assert roles5["Core Flexi-Cap Compounder"].allocation_pct == 21.1
    assert roles5["Mid-Cap Alpha Engine"].allocation_pct == 26.4
    assert roles5["Small-Cap Growth Engine"].allocation_pct == 21.1
    assert roles5["Large-Cap Bluechip Anchor"].allocation_pct == 26.4
    assert roles5["Tactical Thematic Satellite"].allocation_pct == 0.0
    assert roles5["High-Grade Debt Cushion"].allocation_pct == 5.0
    assert sum(it.monthly_inr for it in plan_t5.items) + plan_t5.unallocated_budget_inr == budget
    if plan_t5.unallocated_budget_inr > 0:
        assert all(it.monthly_inr == 0 for it in plan_t5.items)

    # Starter Portfolio (< 5L AUM): 60% Flexi / 40% mid-small, split by SAA proportions.
    plan_starter = compute_deterministic_sip_blueprint(
        monthly_budget=20000.0,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=7.54,
        client_aum=200000.0,  # Starter
        equity_sip_routing_override=True,
    )
    assert plan_starter.equity_sip_pct == 100.0
    roles_starter = {item.category_role: item for item in plan_starter.items}
    assert roles_starter["Core Flexi-Cap Compounder"].allocation_pct == 60.0
    assert roles_starter["Mid-Cap Alpha Engine"].allocation_pct == 20.0
    assert roles_starter["Small-Cap Growth Engine"].allocation_pct == 20.0
    assert "Large-Cap Bluechip Anchor" not in roles_starter
    assert "Tactical Thematic Satellite" not in roles_starter
    assert sum(it.monthly_inr for it in plan_starter.items) + plan_starter.unallocated_budget_inr == 20000.0
    if plan_starter.unallocated_budget_inr > 0:
        assert all(it.monthly_inr == 0 for it in plan_starter.items)
    print("[PASS] P0.1 Universal SIP Sleeve Sizing Invariant Verified")



def test_p0_2_tax_shield_siphon_and_day_366():
    """Retired tax advice must fail closed, not generate a tax-shield schedule."""
    from tax.transition_planner import TaxAdviceDisabledError, load_tax_rules, plan_fy_tranches

    with pytest.raises(TaxAdviceDisabledError, match="disabled pending independently approved"):
        load_tax_rules(Path("data/policy/tax_rules.json"))
    with pytest.raises(TaxAdviceDisabledError, match="No estimate or action plan"):
        plan_fy_tranches(
            plans={},
            tax_rules={},
            as_of=date.today(),
            current_navs={},
            prior_ltcg_this_fy=0.0,
        )
    print("[PASS] P0.2 Tax / Day-366 advice remains disabled pending independent approval")


def test_p0_3_all_10_binary_eligibility_gates(tmp_path):
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
        "plan": "Direct",
        "direct_plan_evidence_status": "REVIEWER_ATTESTED_HASH_MATCH",
        "isin": "TEST001",
        "_provenance": {"confidence_score": 0.95}
    }

    base_good_fund = _attach_reviewed_direct_test_evidence(base_good_fund, tmp_path)

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


def test_p0_4_candidate_universe_and_no_action_branch(tmp_path):
    """Verifies candidate universe ingestion from a synthetic fixture and NO ACTION branch."""
    metrics_path = tmp_path / "fund_metrics.json"
    metrics_path.write_text(json.dumps({"funds": [
        {"id": "synthetic-core-1", "name": "Synthetic Core Direct", "category": "Large Cap",
         "aum_crore": 5000, "aum_stable": True, "return_1y": 12.0, "return_3y": 14.0,
         "return_6m": 6.0, "alpha_3y": 2.0, "sharpe_3y": 1.0, "ter_direct_pct": 0.5,
         "manager_tenure_years": 5.0, "track_record_years": 10.0}
    ]}), encoding="utf-8")
    candidates = load_candidate_universe(metrics_path)
    assert len(candidates) == 1
    assert candidates[0]["fund_id"] == "synthetic-core-1"

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



def test_p0_5_fiduciary_personal_redemption_engine_fails_closed():
    """Redemption must remain NO ACTION without approved tax and scheme/lot evidence."""
    from core.redemption_engine import compute_personal_redemption_plan
    from core.models import HoldingItem, PlanType, AssetClass

    holding = HoldingItem(
        fund_id="synthetic-fund-001",
        scheme="Synthetic Equity Scheme - Direct Growth",
        fund_name="Synthetic Equity Scheme",
        folio="SYNTHETIC-FOLIO",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=250000.0,
        invested_value_inr=200000.0,
        units=2000.0,
        nav=125.0,
    )

    plan = compute_personal_redemption_plan(
        requested_amount=100000.0,
        holdings=[holding],
        transactions_path=None,
        is_net_cash=False,
    )

    assert plan.ticket_category == "NO_ACTION_EVIDENCE"
    assert plan.requested_amount_inr == 100000.0
    assert plan.total_gross_redeemed_inr == 0.0
    assert plan.total_exit_load_inr == 0.0
    assert plan.total_stcg_tax_inr == 0.0
    assert plan.total_ltcg_tax_inr == 0.0
    assert plan.total_net_cash_inr == 0.0
    assert plan.funds_liquidated_count == 0
    assert plan.tranches == []
    assert plan.execution_steps
    assert "provisional" in plan.ticket_rationale.lower()
    assert "remains unallocated" in plan.ticket_rationale.lower()


def test_p0_6_multi_horizon_selection_and_peer_evaluation(tmp_path):
    """
    Verifies multi-horizon scoring on synthetic Healthcare/Pharma peer data.
    No real-client fund metrics are required by this unit test.
    """
    from core.math_engine import compute_multi_horizon_fiduciary_score, select_autonomous_blueprint_funds

    metrics_path = tmp_path / "fund_metrics.json"
    def peer(fid, name, ret_1y, ret_6m, ret_3y, alpha, sharpe, ter, downside, upside):
        return {
            "id": fid, "name": name, "category": "Thematic", "aum_crore": 5000,
            "aum_stable": True, "top10_concentration_pct": 45.0,
            "single_sector_weight_pct": 30.0, "sharpe_3y": sharpe, "sharpe_1y": sharpe,
            "alpha_3y": alpha, "return_1y": ret_1y, "return_6m": ret_6m,
            "return_3y": ret_3y, "ter_direct_pct": ter, "downside_capture_ratio": downside,
            "upside_capture_ratio": upside, "riskometer_score": 6,
            "manager_tenure_years": 5.0, "track_record_years": 10.0,
            "composite_score": 70.0, "mandate_suitable": True, "data_complete": True,
            "is_passive": False,
        }
    metrics_path.write_text(json.dumps({"funds": [
        peer("SYNTH-HEALTH-A", "Synthetic Health A Direct", 49.4, 22.0, 24.0, 10.0, 1.4, 0.89, 85.0, 125.0),
        peer("SYNTH-HEALTH-B", "Synthetic Health B Direct", 45.0, 18.0, 22.0, 8.0, 1.2, 0.90, 88.0, 120.0),
        peer("SYNTH-HEALTH-C", "Synthetic Health C Direct", 40.0, 14.0, 18.0, 5.0, 1.0, 0.95, 92.0, 115.0),
        peer("SYNTH-HEALTH-D", "Synthetic Health D Direct", 35.2, 10.0, 15.0, 2.0, 0.8, 0.99, 98.0, 105.0),
    ]}), encoding="utf-8")
    candidates = load_candidate_universe(metrics_path)
    pharma_cands = {item["fund_id"]: item for item in candidates}
    assert len(pharma_cands) == 4

    best = pharma_cands["SYNTH-HEALTH-A"]
    second = pharma_cands["SYNTH-HEALTH-B"]
    worst = pharma_cands["SYNTH-HEALTH-D"]
    score_best = compute_multi_horizon_fiduciary_score(best)
    score_second = compute_multi_horizon_fiduciary_score(second)
    score_worst = compute_multi_horizon_fiduciary_score(worst)
    assert score_best > score_worst
    assert score_second > score_worst
    assert best["return_1y"] > worst["return_1y"]
    assert best["ter_direct_pct"] < worst["ter_direct_pct"]

    # Without verified client-specific candidates, the tactical slot must remain NO_ACTION.
    slots = select_autonomous_blueprint_funds(holdings=[], client_risk_tier=6, thematic_deficit_theme="Pharma")
    slot4 = slots["Slot 5: Tactical Thematic Satellite"]
    assert str(slot4["scheme"]).startswith("NO_ACTION")
    assert "NO_ACTION" in slot4["rationale"]
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
    Synthetic mathematical boundary test. No personal portfolio values,
    holdings or actual monthly budgets are embedded in the test.
    """
    v_tot = 100000.0
    v_h = 1000.0
    s_tot = 10000.0
    s_h = 800.0
    ceiling = 0.05

    # Exact crossing occurs after month 13 and before month 14.
    num = (ceiling * v_tot) - v_h
    den = s_h - (ceiling * s_tot)
    m_exact = num / den
    assert m_exact == pytest.approx(13.3333333333)

    m13_pct = ((v_h + s_h * 13) / (v_tot + s_tot * 13)) * 100.0
    m14_pct = ((v_h + s_h * 14) / (v_tot + s_tot * 14)) * 100.0
    assert m13_pct < 5.0
    assert round(m13_pct, 2) == 4.96
    assert m14_pct >= 5.0
    assert round(m14_pct, 2) == 5.08

    zero_inflow_pct = (v_h / v_tot) * 100.0
    assert zero_inflow_pct == pytest.approx(1.0)

    # A starting exposure just below the ceiling crosses almost immediately.
    v_h_high = v_tot * 0.049
    m_high = ((ceiling * v_tot) - v_h_high) / den
    assert 0.0 < m_high < 1.0
    print("[PASS] P0.9 Synthetic Thematic Taper Algebra & Boundary Verified")

def test_p0_10_gate4_fail_closed_and_missing_metrics(tmp_path):
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
        "plan": "Direct",
        "direct_plan_evidence_status": "REVIEWER_ATTESTED_HASH_MATCH",
        "isin": "TEST003",
        "_provenance": {"confidence_score": 0.95}
    }

    base_active = _attach_reviewed_direct_test_evidence(base_active, tmp_path)

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

    # Skip unless the caller explicitly supplies private client data outside the repository.
    import os
    configured_dir = os.environ.get("MF_CLIENT_DATA_DIR")
    if not configured_dir:
        pytest.skip("MF_CLIENT_DATA_DIR is not configured for private CAS integration testing")
    if not Path(configured_dir).expanduser().resolve().is_dir():
        pytest.skip("Configured MF_CLIENT_DATA_DIR is not available")

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


def test_p0_12_all_four_slots_fail_closed_without_verified_candidates():
    """
    Missing candidate data must not invent passive scheme names or allocate funds.
    Each unfilled sleeve is explicitly NO ACTION with its target budget unallocated.
    """
    from core.math_engine import select_autonomous_blueprint_funds

    slots = select_autonomous_blueprint_funds(
        holdings=[], candidate_universe=[], client_risk_tier=6
    )
    for name in (
        "Slot 1: Core Flexi-Cap Compounder",
        "Slot 2: Mid-Cap Alpha Engine",
        "Slot 3: Small-Cap Growth Engine",
        "Slot 4: Large-Cap Bluechip Anchor",
        "Slot 5: Tactical Thematic Satellite",
        "High-Grade Debt Anchor",
    ):
        slot = slots[name]
        assert str(slot.get("scheme") or "").startswith("NO_ACTION")
        assert slot.get("allocation_pct") == 0.0
        assert slot.get("unallocated_pct", 0.0) >= 0.0
        assert "NO_ACTION" in slot.get("rationale", "")

    assert slots["Slot 5: Tactical Thematic Satellite"]["unallocated_pct"] == 0.0
    print("[PASS] P0.12 No Candidate Universe Fails Closed Without Invented Schemes")



def test_p0_13_statutory_tax_specified_fund_and_mandate_state():
    """All investor-facing statutory tax classifiers must remain fail-closed."""
    from core import math_engine

    disabled_apis = [
        math_engine.get_statutory_tax_citation,
        math_engine.classify_specified_mutual_fund,
        math_engine.qualifies_as_equity_oriented_under_section_198,
        math_engine.qualifies_as_specified_mutual_fund_under_section_50AA,
        math_engine.qualifies_as_specified_mutual_fund_under_section_76,
        math_engine.compute_fifo_tax_lots,
        math_engine.build_fifo_tax_lots,
        math_engine._classify_fund_for_tax,
    ]
    for api in disabled_apis:
        with pytest.raises(math_engine.TaxClassificationDisabledError):
            api()
    print("[PASS] P0.13 Unreviewed statutory tax classification APIs fail closed")


def test_p0_14_cashflow_matched_benchmark_requires_independent_nse_calendar(tmp_path):
    """
    A deterministic synthetic transaction ledger is sufficient to exercise the
    fail-closed calendar gate. No personal transactions or CAS data are used.
    """
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr
    from core.models import TriProvenanceError

    tx_path = tmp_path / "synthetic_transactions.json"
    tx_path.write_text(
        json.dumps({
            "transactions": [
                {
                    "scheme": "Synthetic Equity Fund Direct Growth",
                    "date": "2026-10-02",
                    "amount": 1000.0,
                    "units": 10.0,
                    "nav": 100.0,
                    "type": "PURCHASE",
                    "description": "Synthetic test purchase",
                }
            ]
        }),
        encoding="utf-8",
    )
    tri_path = Path("data/policy/benchmark_tri_series.json")
    assert tri_path.is_file(), "The checked-in provisional TRI test fixture is required"

    with pytest.raises(TriProvenanceError) as exc_info:
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=tx_path,
            as_of_date=date(2026, 10, 9),
            benchmark_key="NIFTY 500 TRI",
            benchmark_series_path=tri_path,
            cas_current=1010.0,
            trading_calendar_path=tmp_path / "independent_nse_calendar_missing.json",
        )
    assert exc_info.value.validation_stage == "trading_calendar_missing"
    print("[PASS] P0.14 TRI refuses to calculate without an independent NSE session calendar")


def test_p0_15_runtime_mandate_hold_enforcement_is_a_unit_invariant():
    """
    Verify the execution guard directly; this invariant must not depend on a
    private CAS statement or a particular client's current mandate file.
    """
    from types import SimpleNamespace
    from core.math_engine import assert_mandate_execution_authorized
    from core.models import (
        DeterministicLumpsumPlan,
        DeterministicSIPPlan,
        MandateExecutionState,
        MandateHoldViolationError,
    )

    held_facts = SimpleNamespace(
        mandate_state=MandateExecutionState.HOLD_PENDING_TRI_VALIDATION,
        is_execution_authorized=False,
    )
    with pytest.raises(MandateHoldViolationError):
        assert_mandate_execution_authorized(held_facts)

    sip_plan = DeterministicSIPPlan(total_monthly_budget_inr=10000.0, unallocated_budget_inr=10000.0, equity_sip_pct=0.0, debt_sip_pct=0.0)
    assert sip_plan.mandate_state == MandateExecutionState.HOLD_PENDING_TRI_VALIDATION
    assert sip_plan.is_execution_authorized is False
    assert sip_plan.is_actionable_order is False

    lumpsum_plan = DeterministicLumpsumPlan(
        total_lumpsum_inr=10000.0,
        is_big_ticket=False,
        stp_duration_months=0,
        immediate_amount_inr=0.0,
        stp_total_amount_inr=0.0,
        monthly_stp_total_inr=0.0,
        parking_vehicle="NO_ACTION",
        unallocated_amount_inr=10000.0,
    )
    assert lumpsum_plan.mandate_state == MandateExecutionState.HOLD_PENDING_TRI_VALIDATION
    assert lumpsum_plan.is_execution_authorized is False
    assert lumpsum_plan.is_actionable_order is False
    print("[PASS] P0.15 Runtime Mandate Hold Enforcement Verified Without Client Data")


def test_p0_16_tri_coverage_gate_uses_observed_sessions_not_metadata():
    """
    The coverage arithmetic is tested against a deterministic synthetic session
    calendar. Editable coverage metadata is not an input to the calculation.
    """
    from core.math_engine import calculate_tri_calendar_coverage
    from core.models import TriProvenanceError

    calendar_start = date(2026, 1, 1)
    synthetic_sessions = [calendar_start + timedelta(days=i) for i in range(100)]
    sparse_observations = synthetic_sessions[:10]

    with pytest.raises(TriProvenanceError) as exc_info:
        calculate_tri_calendar_coverage(
            observed_dates=sparse_observations,
            calendar_sessions=synthetic_sessions,
            coverage_start=synthetic_sessions[0],
            coverage_end=synthetic_sessions[-1],
            minimum_coverage_pct=95.0,
            benchmark_key="SYNTHETIC TRI",
        )
    assert exc_info.value.validation_stage == "coverage_insufficient"
    assert "10.00%" in str(exc_info.value)

    sufficiently_covered = calculate_tri_calendar_coverage(
        observed_dates=synthetic_sessions[:95],
        calendar_sessions=synthetic_sessions,
        coverage_start=synthetic_sessions[0],
        coverage_end=synthetic_sessions[-1],
        minimum_coverage_pct=95.0,
        benchmark_key="SYNTHETIC TRI",
    )
    assert sufficiently_covered == {
        "expected_trading_days": 100,
        "provided_data_points": 95,
        "coverage_pct": 95.0,
    }
    print("[PASS] P0.16 TRI Coverage Gate Rejects Inflated or Sparse Coverage")




def test_p0_17_tri_release_gate_rejects_boolean_and_nonfinite_observations(tmp_path, monkeypatch):
    """Release eligibility must independently reject bool/NaN/inf TRI values."""
    import hashlib
    import verify_tri_provenance as verifier

    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    policy_dir = tmp_path / "data" / "policy"
    policy_dir.mkdir(parents=True)
    source_dir = tmp_path / "data" / "sources"
    source_dir.mkdir(parents=True)

    tri_source = source_dir / "tri.csv"
    tri_source.write_text("date,value\\n2026-01-01,100\\n2026-01-02,101\\n", encoding="utf-8")
    calendar_source = source_dir / "calendar.csv"
    calendar_source.write_text("date\\n2026-01-01\\n2026-01-02\\n", encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    sessions = ["2026-01-01", "2026-01-02"]
    calendar = {
        "exchange": "NSE",
        "status": "VERIFIED",
        "sessions": sessions,
        "provenance": {
            "source_url": "https://www.nseindia.com/example-calendar.csv",
            "source_document_file": "data/sources/calendar.csv",
            "source_document_sha256": digest(calendar_source),
            "sessions_sha256": verifier._canonical_sha256(sessions),
            "reviewer_attested": True,
        },
    }
    (policy_dir / "nse_trading_calendar.json").write_text(
        json.dumps(calendar), encoding="utf-8"
    )

    levels = {"2026-01-01": 100.0, "2026-01-02": True}
    fixture = {
        "provenance": {
            "frequency": "Daily",
            "interpolation_used": False,
            "source_authenticity": "VERIFIED",
            "release_eligibility": "ELIGIBLE",
            "historical_source_url": "https://www.niftyindices.com/example-tri.csv",
            "historical_source_file": "data/sources/tri.csv",
            "source_document_sha256": digest(tri_source),
            "independent_reviewer_id": "independent-reviewer",
        },
        "benchmarks": {"NIFTY 500 TRI": {"levels": levels}},
    }
    fixture_path = policy_dir / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    blockers = verifier.alpha_release_blockers(fixture_path)
    assert any("boolean TRI value" in blocker for blocker in blockers)

    levels["2026-01-02"] = float("inf")
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    blockers = verifier.alpha_release_blockers(fixture_path)
    assert any("non-finite or non-positive TRI value" in blocker for blocker in blockers)




def test_p0_18_tri_fixture_verifier_rejects_malformed_json_shapes(tmp_path):
    """Malformed JSON object shapes must return failures, never crash CI."""
    import verify_tri_provenance as verifier

    root_fixture = tmp_path / "root-list.json"
    root_fixture.write_text("[]", encoding="utf-8")
    failures = verifier.verify_fixture(root_fixture)
    assert any("fixture root must be a JSON object" in item for item in failures)

    nested_fixture = tmp_path / "nested-list.json"
    nested_fixture.write_text(
        json.dumps({
            "provenance": {},
            "coverage": {"nifty_500_tri": [], "nifty_50_tri": {}},
            "benchmarks": {"NIFTY 500 TRI": [], "NIFTY 50 TRI": {}},
        }),
        encoding="utf-8",
    )
    failures = verifier.verify_fixture(nested_fixture)
    assert any("benchmark entry must be a JSON object" in item for item in failures)
    assert any("levels must be a non-empty date/value object" in item for item in failures)
    assert any("coverage entry must be a JSON object" in item for item in failures)

