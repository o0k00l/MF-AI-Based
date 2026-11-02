"""
Test the engine logic with sample/minimal data to demonstrate how it works.
Run: python test_sample_data.py
"""
import json
import tempfile
from pathlib import Path
from datetime import date

# Minimal sample CAS-like data
SAMPLE_HOLDINGS = [
    {
        "fund_id": "SAMPLE_FLEXI_001",
        "scheme": "Sample Flexi Cap Fund - Regular Plan - Growth",
        "fund_name": "Sample Flexi Cap Fund",
        "folio": "FOLIO001",
        "is_direct": False,
        "plan": "Regular",
        "asset_class": "Flexi_Cap",
        "equity_pct": 90.0,
        "debt_pct": 5.0,
        "hybrid_pct": 5.0,
        "international_pct": 0.0,
        "current_value_inr": 1000000.0,
        "invested_value_inr": 800000.0,
        "units": 50000.0,
        "nav": 20.0,
        "top_holdings": ["HDFC Bank", "ICICI Bank", "Infosys", "Reliance"],
        "expense_ratio_pct": 1.8,
    },
    {
        "fund_id": "SAMPLE_MIDCAP_001",
        "scheme": "Sample Midcap Fund - Direct Plan - Growth",
        "fund_name": "Sample Midcap Fund",
        "folio": "FOLIO002",
        "is_direct": True,
        "plan": "Direct",
        "asset_class": "Mid_Cap",
        "equity_pct": 95.0,
        "debt_pct": 3.0,
        "hybrid_pct": 2.0,
        "international_pct": 0.0,
        "current_value_inr": 500000.0,
        "invested_value_inr": 400000.0,
        "units": 20000.0,
        "nav": 25.0,
        "top_holdings": ["Trent", "Dixon", "Persistent", "Coforge"],
        "expense_ratio_pct": 0.8,
    },
    {
        "fund_id": "SAMPLE_DEBT_001",
        "scheme": "Sample Short Term Debt Fund - Regular Plan - Growth",
        "fund_name": "Sample Short Term Debt Fund",
        "folio": "FOLIO003",
        "is_direct": False,
        "plan": "Regular",
        "asset_class": "Debt",
        "equity_pct": 0.0,
        "debt_pct": 95.0,
        "hybrid_pct": 5.0,
        "international_pct": 0.0,
        "current_value_inr": 300000.0,
        "invested_value_inr": 290000.0,
        "units": 15000.0,
        "nav": 20.0,
        "top_holdings": ["Govt Bonds", "Corporate Bonds", "T-Bills"],
        "expense_ratio_pct": 0.6,
    },
]

SAMPLE_FUND_METRICS = {
    "funds": [
        {
            "id": "PARAG_PARIKH_FLEXI_DIRECT",
            "name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            "category": "Flexi Cap",
            "aum_crore": 50000.0,
            "expense_ratio_direct": 0.69,
            "expense_ratio_regular": 1.74,
            "sharpe_3y": 0.64,
            "alpha_3y": 3.83,
            "top10_concentration_pct": 35.0,
            "single_sector_weight_pct": 20.0,
            "riskometer_score": 6,
            "manager_tenure_years": 10.0,
            "composite_score": 85.0,
            "is_direct": True,
            "debt_pct": 12.0,
            "cash_pct": 5.0,
            "equity_pct": 83.0,
        },
        {
            "id": "HDFC_MIDCAP_DIRECT",
            "name": "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
            "category": "Mid Cap",
            "aum_crore": 45000.0,
            "expense_ratio_direct": 0.76,
            "expense_ratio_regular": 1.85,
            "sharpe_3y": 0.62,
            "alpha_3y": 2.44,
            "top10_concentration_pct": 37.0,
            "single_sector_weight_pct": 18.0,
            "riskometer_score": 6,
            "manager_tenure_years": 8.0,
            "composite_score": 82.0,
            "is_direct": True,
            "debt_pct": 2.0,
            "cash_pct": 3.0,
            "equity_pct": 95.0,
        },
        {
            "id": "HDFC_NIFTY50_INDEX_DIRECT",
            "name": "HDFC Nifty 50 Index Fund - Direct Plan - Growth",
            "category": "Index / ETF",
            "aum_crore": 30000.0,
            "expense_ratio_direct": 0.18,
            "expense_ratio_regular": 0.80,
            "sharpe_3y": 0.45,
            "alpha_3y": 0.1,
            "top10_concentration_pct": 55.0,
            "single_sector_weight_pct": 30.0,
            "riskometer_score": 6,
            "manager_tenure_years": 5.0,
            "composite_score": 75.0,
            "is_direct": True,
            "debt_pct": 0.0,
            "cash_pct": 0.5,
            "equity_pct": 99.5,
        },
        {
            "id": "NIPPON_PHARMA_DIRECT",
            "name": "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth",
            "category": "Thematic",
            "aum_crore": 8000.0,
            "expense_ratio_direct": 0.82,
            "expense_ratio_regular": 2.10,
            "sharpe_3y": 0.74,
            "alpha_3y": 4.82,
            "top10_concentration_pct": 45.0,
            "single_sector_weight_pct": 85.0,
            "riskometer_score": 6,
            "manager_tenure_years": 6.0,
            "composite_score": 78.0,
            "is_direct": True,
            "debt_pct": 0.0,
            "cash_pct": 2.0,
            "equity_pct": 98.0,
        },
    ]
}

SAMPLE_CONFIG = {
    "client_name": "Test Client",
    "target_allocation": {
        "large_cap_pct": 20.0,
        "mid_cap_pct": 25.0,
        "small_cap_pct": 25.0,
        "flexi_multi_cap_pct": 25.0,
        "debt_liquid_pct": 5.0,
        "tolerance_band_pct": 5.0
    },
    "ips": {
        "client_name": "Test Client",
        "client_age": 35,
        "horizon_years": 10,
        "risk_tolerance": "very_high",
        "monthly_sip_budget": 100000.0,
        "lumpsum_budget": 200000.0,
        "marginal_tax_rate_pct": 30.0,
        "risk_tier": 6,
        "equity_sip_routing_override": True
    },
    "cash": {
        "bank_cash_total": 500000.0,
        "emergency_reserve": 150000.0,
        "deployable_surplus": 350000.0,
        "source": "Sample data"
    },
    "risk_tier": "Tier 6 (Very High)"
}

SAMPLE_ALIASES = {
    "Sample Flexi Cap Fund": "PARAG_PARIKH_FLEXI_DIRECT",
    "Sample Midcap Fund": "HDFC_MIDCAP_DIRECT",
    "Sample Short Term Debt Fund": "HDFC_NIFTY50_INDEX_DIRECT",
}


def create_sample_files(tmpdir):
    tmpdir = Path(tmpdir)
    (tmpdir / "fund_metrics.json").write_text(json.dumps(SAMPLE_FUND_METRICS, indent=2))
    return tmpdir / "fund_metrics.json"


def test_basic_analysis():
    print("=" * 70)
    print("TESTING ENGINE LOGIC WITH SAMPLE DATA")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = create_sample_files(tmpdir)

        from core.math_engine import (
            calculate_fee_bleed,
            calculate_weighted_lookthrough_overlap,
            calculate_lookthrough_stability_buffer,
            calculate_thematic_exposures,
            calculate_cash_deployment,
        )
        from core.models import HoldingItem

        holdings = [HoldingItem(**h) for h in SAMPLE_HOLDINGS]

        print("\n1. SAMPLE PORTFOLIO:")
        print(f"   Holdings: {len(holdings)}")
        print(f"   Total Value: {sum(h.current_value_inr for h in holdings):,.0f}")
        print(f"   Regular Funds: {sum(1 for h in holdings if not h.is_direct)}")
        print(f"   Direct Funds: {sum(1 for h in holdings if h.is_direct)}")

        # Test fee bleed
        print("\n2. FEE BLEED ANALYSIS:")
        fee_bleed = calculate_fee_bleed(holdings)
        print(f"   Annual Commission Leakage: {fee_bleed.annual_commission_leakage_inr:,.0f}")
        print(f"   10-Year Compounded Loss: {fee_bleed.ten_year_compounded_loss_inr:,.0f}")
        print(f"   Regular Funds: {fee_bleed.regular_funds_count}")

        # Test overlap
        print("\n3. OVERLAP ANALYSIS:")
        if len(holdings) >= 2:
            # Create a temp metrics file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(SAMPLE_FUND_METRICS, f)
                metrics_path = Path(f.name)
            try:
                overlap = calculate_weighted_lookthrough_overlap(holdings, metrics_path)
                print(f"   Pairwise overlaps calculated: {len(overlap)} pairs")
                for o in overlap[:3]:
                    print(f"     {o.fund_a} vs {o.fund_b}: {o.overlap_pct:.1f}% - {o.verdict}")
            finally:
                metrics_path.unlink()

        # Test stability buffer
        print("\n4. LOOK-THROUGH STABILITY BUFFER:")
        stability = calculate_lookthrough_stability_buffer(holdings)
        print(f"   Embedded Debt: {stability.embedded_debt_inr:,.0f} ({stability.embedded_debt_pct:.1f}%)")
        print(f"   Embedded Cash: {stability.embedded_cash_inr:,.0f} ({stability.embedded_cash_pct:.1f}%)")
        print(f"   Total Stability Buffer: {stability.total_stability_buffer_pct:.1f}%")

        # Test thematic exposures
        print("\n5. THEMATIC EXPOSURES:")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_FUND_METRICS, f)
            metrics_path = Path(f.name)
        try:
            thematics = calculate_thematic_exposures(holdings, metrics_path)
            for t in thematics:
                print(f"   {t.theme_name}: Dedicated {t.dedicated_funds_pct:.1f}% | Look-through {t.look_through_stocks_pct:.1f}% | {t.coverage_status}")
        finally:
            metrics_path.unlink()

        # Test cash deployment
        print("\n6. CASH DEPLOYMENT:")
        cash_plan = calculate_cash_deployment(
            bank_cash_inr=500000.0,
            emergency_buffer_inr=150000.0
        )
        print(f"   Total Cash: {cash_plan.total_cash_inr:,.0f}")
        print(f"   Emergency Reserve: {cash_plan.emergency_reserve_inr:,.0f}")
        print(f"   Deployable Surplus: {cash_plan.deployable_surplus_inr:,.0f}")
        print(f"   STP Monthly: {cash_plan.stp_monthly_amount_inr:,.0f} for {cash_plan.stp_duration_months} months")

        return holdings, stability


def test_blueprints(holdings, stability):
    from core.math_engine import (
        compute_deterministic_sip_blueprint,
        compute_deterministic_lumpsum_blueprint,
    )

    # Test SIP Blueprint
    print("\n7. DETERMINISTIC SIP BLUEPRINT (Tier 6, 1L/month):")
    sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=100000.0,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=stability.total_stability_buffer_pct,
        holdings=holdings,
        client_aum=2000000.0
    )
    print(f"   Equity SIP: {sip_plan.equity_sip_pct:.1f}% | Debt SIP: {sip_plan.debt_sip_pct:.1f}%")
    for item in sip_plan.items:
        print(f"     {item.category_role}: {item.scheme_name} = {item.monthly_inr:,.0f} ({item.allocation_pct:.1f}%)")
    print(f"   Total: {sum(item.monthly_inr for item in sip_plan.items):,.0f}")

    # Test Lumpsum Blueprint
    print("\n8. DETERMINISTIC LUMPSUM BLUEPRINT (2L):")
    lump_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=200000.0,
        bank_cash_total=500000.0,
        emergency_reserve=150000.0,
        holdings=holdings,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=stability.total_stability_buffer_pct
    )
    for t in lump_plan.tranches:
        print(f"     {t.role}: {t.scheme_name} = {t.amount_inr:,.0f} ({t.allocation_pct:.1f}%)")
    print(f"   Total: {sum(t.amount_inr for t in lump_plan.tranches):,.0f}")


def test_eligibility():
    from core.eligibility import check_eligibility_gates, evaluate_no_action
    from core.models import HoldingItem

    holdings = [HoldingItem(**h) for h in SAMPLE_HOLDINGS]
    candidate = SAMPLE_FUND_METRICS["funds"][0]  # Parag Parikh

    # Test Eligibility Gates
    print("\n9. ELIGIBILITY GATES (on sample candidate):")
    result = check_eligibility_gates(candidate, portfolio_holdings=[
        {"scheme": h.scheme, "value": h.current_value_inr} for h in holdings
    ])
    print(f"   Fund: {candidate['name']}")
    print(f"   Passed: {result.passed}")
    print(f"   Failed Gates: {result.failed_gates or 'None'}")

    # Test NO ACTION
    print("\n10. NO ACTION BRANCH:")
    no_action = evaluate_no_action(
        current_portfolio=[{"scheme": h.scheme, "value": h.current_value_inr} for h in holdings],
        candidate_funds=[candidate],
        min_improvement_threshold=5.0
    )
    print(f"   Action: {no_action.action}")
    print(f"   Reason: {no_action.reason[:100]}...")


def test_engine_logic():
    holdings, stability = test_basic_analysis()
    test_blueprints(holdings, stability)
    test_eligibility()

    print("\n" + "=" * 70)
    print("ALL LOGIC TESTS COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    test_engine_logic()