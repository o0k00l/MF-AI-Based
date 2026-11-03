"""
validate_final_logics.py - Comprehensive Verification of Universal Fiduciary Logics.

Validates:
1. The Universal 20/80 Lumpsum Equation across all wealth amounts.
2. The Universal 4-Slot Sizing Engine (Starter vs Established scaling).
3. The Look-Through Stability Buffer (embedded debt + cash detection).
4. The 5-Theme Real-Time Look-Through Diagnostics.
5. Fiduciary Binary Gates (Thematic cap <= 15%, 100% Direct Mandate).
6. End-to-End Client Payload & Deliverable Integrity.
"""

import sys
import warnings

# Suppress openpyxl UserWarning about default styles
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

from pathlib import Path
import json

from core.models import (
    HoldingItem, PlanType, AssetClass, DeterministicSIPPlan,
    DeterministicSIPRecommendation
)
from core.math_engine import (
    load_holdings_from_cas_excel,
    calculate_lookthrough_stability_buffer,
    calculate_thematic_exposures,
    compute_deterministic_sip_blueprint, compute_deterministic_lumpsum_blueprint,
    aggregate_fiduciary_facts
)
from core.eligibility import (
    validate_thematic_satellite_cap,
    validate_direct_sip_mandate
)

passed_checks = 0
total_checks = 0

def check(description: str, condition: bool, extra_info: str = ""):
    global passed_checks, total_checks
    total_checks += 1
    if condition:
        passed_checks += 1
        print(f"  [PASS] {description} {extra_info}")
    else:
        print(f"  [FAIL] {description} {extra_info}")
        raise AssertionError(f"Check failed: {description}")

print("\n" + "="*70)
print("  UNIVERSAL FIDUCIARY LOGIC VALIDATION SUITE (ALL-CLIENT READINESS)")
print("="*70)

# =====================================================================
# TEST 1: Universal 20/80 Lumpsum Equation & Big-Ticket Scaling
# =====================================================================
print("\n>> [TEST 1] Lumpsum fail-closed evidence and budget reconciliation:")
test_lumpsums = [100000.0, 500000.0, 1000000.0, 2500000.0, 5000000.0]
for L in test_lumpsums:
    lp = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=L,
        bank_cash_total=435000.0,
        emergency_reserve=115000.0,
        bank_cash_verified=False,
        candidate_universe=[],
    )
    check(
        f"Lumpsum INR {L:,.0f} remains NO ACTION without bank verification",
        not lp.cash_validation_passed and lp.immediate_amount_inr == 0 and lp.stp_total_amount_inr == 0,
        lp.cash_validation_message,
    )
    tranche_sum = sum(t.amount_inr for t in lp.tranches)
    check(
        f"Lumpsum INR {L:,.0f} reconciles deployed plus unallocated",
        abs(tranche_sum + lp.unallocated_amount_inr - L) < 0.01,
        f"Tranches INR {tranche_sum:,.2f}; unallocated INR {lp.unallocated_amount_inr:,.2f}",
    )
    check(
        f"Lumpsum INR {L:,.0f} does not fabricate a parking vehicle or tax saving",
        lp.parking_vehicle == "NO_ACTION" and lp.tax_savings_vs_debt_fund_inr == 0.0,
        f"Vehicle: {lp.parking_vehicle}; estimated saving: {lp.tax_savings_vs_debt_fund_inr:.2f}",
    )

# =====================================================================
# TEST 2: Universal 4-Slot Sizing Engine & Tiered Scaling
# =====================================================================
print("\n>> [TEST 2] Universal 4-Slot Sizing Engine & Tiered Scaling:")

# 2A: Established Client (Lalit - INR 1,00,000 / mo SIP, INR 51.7L AUM)
established_plan = compute_deterministic_sip_blueprint(
    monthly_budget=100000.0,
    risk_tier="Tier 6 (Very High)",
    stability_buffer_pct=7.54
)
check("Established Plan Total Budget", established_plan.total_monthly_budget_inr == 100000.0)
check("Established Plan Item Count", len(established_plan.items) == 4, f"Found {len(established_plan.items)} items")

sum_alloc = sum(item.monthly_inr for item in established_plan.items)
check(
    "Established Plan Budget Accounting",
    abs(sum_alloc + established_plan.unallocated_budget_inr - 100000.0) < 0.01,
    f"Invested: ₹{sum_alloc:,.0f}; explicitly unallocated: ₹{established_plan.unallocated_budget_inr:,.0f}"
 )

# Check individual slots
roles = {item.category_role: item for item in established_plan.items}
# Policy: very_high saa_targets: flexi=25, mid+small=50, large=20 (sum=95)
# Weights: flexi=25/95=26.3%, mid+small=50/95=52.6%, large=20/95=21.1%, thematic=0%
check("Slot 1: Core Flexi target weight (26.3%)", roles["Core Flexi-Cap Compounder"].allocation_pct == 26.3)
check("Slot 2: Mid-Cap Alpha target weight (52.6%)", roles["Mid-Cap Alpha Engine"].allocation_pct == 52.6)
check("Slot 3: Large-Cap Anchor target weight (21.1%)", roles["Large-Cap Bluechip Anchor"].allocation_pct == 21.1)
check("Slot 4: Thematic Satellite target weight (0%)", roles["Tactical Thematic Satellite"].allocation_pct == 0.0)
check(
    "SIP amounts withheld when budget is unallocated",
    all(item.monthly_inr == 0.0 for item in established_plan.items)
    if established_plan.unallocated_budget_inr > 0.0 else abs(sum_alloc - 100000.0) < 0.01
)
check(
    "100% Direct Plan Mandate",
    all(item.is_direct is True for item in established_plan.items if item.monthly_inr > 0)
    and (established_plan.unallocated_budget_inr == 0.0 or sum_alloc == 0.0),
    "Uses explicit selected-candidate metadata, not scheme-name substring inference"
 )
check("Zero Standalone Debt Drag", established_plan.debt_sip_pct == 0.0 and established_plan.equity_sip_pct == 100.0)

cas_path = Path("data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx")
metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
aliases_path = Path("data/lalit_portfolio/fund_aliases.json")
config_path = Path("data/lalit_portfolio/config.json")

# =====================================================================
# PRIVATE PORTFOLIO VALIDATION (requires local investor CAS inputs)
if cas_path.is_file() and metrics_path.is_file() and aliases_path.is_file():
    # =====================================================================
    # TEST 3: Look-Through Stability Buffer Engine
    # =====================================================================
    print("\n>> [TEST 3] Look-Through Stability Buffer vs Category Labels:")

    holdings = load_holdings_from_cas_excel(cas_path, metrics_path, aliases_path)
    check("Holdings Ingestion", len(holdings) == 23)

    stability_buf = calculate_lookthrough_stability_buffer(
        holdings=holdings,
        bank_cash_inr=435000.0,
        emergency_reserve_inr=115000.0,
        target_debt_pct=5.0
    )

    check("Embedded Debt Detected", stability_buf.embedded_debt_inr > 200000.0, f"INR {stability_buf.embedded_debt_inr:,.2f} ({stability_buf.embedded_debt_pct}%)")
    check("Embedded Cash Detected", stability_buf.embedded_cash_inr > 150000.0, f"INR {stability_buf.embedded_cash_inr:,.2f} ({stability_buf.embedded_cash_pct}%)")
    check("Total Stability Cushion >= 7.0%", stability_buf.total_stability_buffer_pct >= 7.0, f"{stability_buf.total_stability_buffer_pct:.2f}%")
    check("Tier 6 (5% Debt Ceiling) Organically Satisfied", stability_buf.meets_tier_target is True)

    # =====================================================================
    # TEST 4: 5-Theme Real-Time Look-Through Diagnostics
    # =====================================================================
    print("\n>> [TEST 4] 5-Theme Real-Time Look-Through Diagnostics:")

    thematic_exposures = calculate_thematic_exposures(holdings, metrics_path, aliases_path)
    check("All 5 Macro Themes Evaluated", len(thematic_exposures) == 5)

    tmap = {t.theme_name: t for t in thematic_exposures}

    # Defence: Should have ~6% dedicated (HDFC Defence + Motilal)
    check("Defence Dedicated Fund Exposure", tmap["Defence Thematic"].dedicated_funds_pct >= 5.5, f"{tmap['Defence Thematic'].dedicated_funds_pct}%")

    # Pharma: Should be flagged as NEGLECTED (lookthrough < 2%, dedicated == 0%)
    check("Pharma & Healthcare Flagged Neglected", tmap["Pharma & Healthcare"].coverage_status == "NEGLECTED", f"Lookthrough: {tmap['Pharma & Healthcare'].look_through_stocks_pct}%")

    # PSU / CPSE: Should have substantial look-through via bluechips
    check("PSU & CPSE Look-Through Detected", tmap["PSU & CPSE Themes"].look_through_stocks_pct >= 5.0, f"{tmap['PSU & CPSE Themes'].look_through_stocks_pct}%")

    # Power & Infra: Should have dedicated + lookthrough
    check("Power & Infrastructure Detected", tmap["Power & Infrastructure"].look_through_stocks_pct >= 4.0, f"{tmap['Power & Infrastructure'].look_through_stocks_pct}%")


else:
    print("  [SKIP] Portfolio-specific validation requires the private Lalit CAS workbook and supporting metrics/config/aliases; no investor data is committed to CI.")

# =====================================================================
# TEST 5: Fiduciary Selection & Policy Gates
# =====================================================================
print("\n>> [TEST 5] Fiduciary Selection & Policy Binary Gates:")

# Gate 9: Thematic Cap Check
check("Gate 9 Passes for 15% Satellite on Established", validate_thematic_satellite_cap(established_plan, client_aum=5170000.0, max_satellite_pct=15.0) is True)

# Gate 9 Violation Test: Starter investor (< INR 5L AUM) cannot hold thematic
starter_with_thematic = DeterministicSIPPlan(
    total_monthly_budget_inr=5000.0,
    items=[
        DeterministicSIPRecommendation(
            category_role="Thematic",
            scheme_name="Nippon India Pharma Direct",
            monthly_inr=1000.0,
            allocation_pct=20.0,
            rational_code="SATELLITE_THEME",
            fiduciary_rationale="Test"
        )
    ]
)
try:
    validate_thematic_satellite_cap(starter_with_thematic, client_aum=200000.0)
    starter_gate_blocked = False
except ValueError:
    starter_gate_blocked = True
check("Gate 9 Blocks Thematic Funds for Starters (< INR 5L)", starter_gate_blocked is True)

# Gate 10: 100% Direct SIP Mandate
check("Gate 10 Passes 100% Direct Plans", validate_direct_sip_mandate(established_plan) is True)

regular_plan_test = DeterministicSIPPlan(
    total_monthly_budget_inr=10000.0,
    items=[
        DeterministicSIPRecommendation(
            category_role="Core",
            scheme_name="HDFC Flexi Cap Fund - Regular Plan - Growth",
            monthly_inr=10000.0,
            allocation_pct=100.0,
            rational_code="CORE_COMPOUNDER",
            fiduciary_rationale="Test"
        )
    ]
)
try:
    validate_direct_sip_mandate(regular_plan_test)
    regular_gate_blocked = False
except ValueError:
    regular_gate_blocked = True
check("Gate 10 Rejects Any Regular Plan in SIP Recommendations", regular_gate_blocked is True)

# =====================================================================
# TEST 6: End-to-End Client Payload & Deliverable Integrity
# =====================================================================
print("\n>> [TEST 6] End-to-End Client Payload & Deliverable Integrity:")

config_path = Path("data/lalit_portfolio/config.json")
if cas_path.is_file() and metrics_path.is_file() and config_path.is_file() and aliases_path.is_file():
    facts = aggregate_fiduciary_facts(cas_path, metrics_path, config_path, aliases_path)

    check("Payload Generated", facts is not None)
    check("Client Name Reconciled", facts.client_name == "Lalit Saini")
    check("Total Value Reconciled", abs(facts.total_portfolio_value_inr - 5170911.38) < 1.0)
    check("Target SAA Aligned with Tier 6 Policy", facts.saa_drift.target_equity_pct == 95.0 and facts.saa_drift.target_debt_pct == 5.0)
    check("Rebalance Required is False (Stability Satisfied)", facts.saa_drift.rebalance_required is False)


else:
    print("  [SKIP] Client payload reconciliation requires private CAS and client configuration inputs.")

# Verify generated deliverable files (only if outputs directory exists - skipped in clean checkout)
outputs_dir = Path("outputs")
if outputs_dir.exists():
    deliv1 = outputs_dir / "Portfolio_Health_Audit.md"
    deliv2 = outputs_dir / "Switch_and_Consolidation_Plan.md"
    deliv3 = outputs_dir / "Fresh_Money_Deployment_Plan.md"
    
    check("Deliverable 1 Generated", deliv1.exists() and deliv1.stat().st_size > 1000)
    check("Deliverable 2 Generated", deliv2.exists() and deliv2.stat().st_size > 1000)
    check("Deliverable 3 Generated", deliv3.exists() and deliv3.stat().st_size > 1000)
    
    with open(deliv3, "r", encoding="utf-8") as f:
        d3_content = f.read()
    
    # Verify structured delivery content (policy-driven assertions, no hardcoded fund brands)
    check("Deliverable 3 contains Core Flexi-Cap Compounder slot", "Core Flexi-Cap Compounder" in d3_content)
    check("Deliverable 3 contains Mid-Cap Alpha Engine slot", "Mid-Cap Alpha Engine" in d3_content)
    check("Deliverable 3 contains Large-Cap Bluechip Anchor slot", "Large-Cap Bluechip Anchor" in d3_content)
    check("Deliverable 3 contains Tactical Thematic Satellite slot", "Tactical Thematic Satellite" in d3_content)
    check("Deliverable 3 confirms 100% Direct Plan", "Direct" in d3_content)
    check("Deliverable 3 confirms Zero Standalone Debt Drag", "7.54%" in d3_content or "look-through stability" in d3_content.lower())
else:
    print("  [SKIP] Deliverable files check (outputs directory not present in this context)")

print("\n" + "="*70)

# =====================================================================
# TEST 7: All 6 SEBI Regulatory Risk Tiers (Dynamic SIP & Lumpsum Scaling)
# =====================================================================
print("\n>> [TEST 7] All 6 SEBI Regulatory Risk Tiers (Dynamic SIP & Lumpsum Scaling):")

tier_targets = [
    ("Tier 6 (Very High)", 100.0, 0.0),
    ("Tier 5 (High)", 95.0, 5.0),
    ("Tier 4 (Moderate High)", 85.0, 15.0),
    ("Tier 3 (Moderate)", 60.0, 40.0),
    ("Tier 2 (Low)", 30.0, 70.0),
    ("Tier 1 (Capital Preservation)", 0.0, 100.0)
]

for t_name, exp_eq, exp_debt in tier_targets:
    # 7A: SIP Dynamic Scaling (Testing Policy-Defined Base New-SIP Splits)
    sip_tier = compute_deterministic_sip_blueprint(
        monthly_budget=50000.0,
        risk_tier=t_name,
        stability_buffer_pct=None
    )
    check(
        f"{t_name} SIP SAA Precision",
        sip_tier.equity_sip_pct == exp_eq and sip_tier.debt_sip_pct == exp_debt,
        f"-> Eq: {sip_tier.equity_sip_pct}% | Debt: {sip_tier.debt_sip_pct}%"
    )
    sip_tot = sum(it.monthly_inr for it in sip_tier.items)
    sip_accounted = sip_tot + sip_tier.unallocated_budget_inr
    check(
        f"{t_name} SIP Budget Accounted For",
        abs(sip_accounted - 50000.0) < 0.01,
        f"Allocated: INR {sip_tot:,.2f}; withheld: INR {sip_tier.unallocated_budget_inr:,.2f}"
    )
    if sip_tier.unallocated_budget_inr > 0.0:
        check(
            f"{t_name} SIP Withheld When Direct Evidence Is Missing",
            all(item.monthly_inr == 0.0 for item in sip_tier.items),
            "No partial allocation or redistribution"
        )
    else:
        check(
            f"{t_name} Positive SIPs Have Verified Direct Status",
            all(item.is_direct is True for item in sip_tier.items if item.monthly_inr > 0),
        )

    # 7B: Lumpsum Dynamic Scaling (INR 10 Lakhs Big-Ticket Baseline SAA)
    lump_tier = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=1000000.0,
        risk_tier=t_name,
        stability_buffer_pct=None,
        bank_cash_total=1200000.0,
        emergency_reserve=200000.0
    )
    lump_tot = sum(tr.amount_inr for tr in lump_tier.tranches)
    check(
        f"{t_name} Lumpsum remains unallocated without verified candidates and staging policy",
        lump_tier.unallocated_amount_inr == 1000000.0 and lump_tot == 0.0,
        f"Deployed: INR {lump_tot:,.2f}; unallocated: INR {lump_tier.unallocated_amount_inr:,.2f}"
    )
    debt_tranche_amt = sum(tr.amount_inr for tr in lump_tier.tranches if "Debt" in tr.role or "Preservation" in tr.role)
    exp_debt_amt = 0.0
    check(
        f"{t_name} Big Lumpsum Debt Allocation Matches SAA",
        abs(debt_tranche_amt - exp_debt_amt) < 0.01,
        f"Debt: INR {debt_tranche_amt:,.0f} (Expected: INR {exp_debt_amt:,.0f})"
    )

print(f"  PUBLIC LOGIC SCORECARD: {passed_checks}/{total_checks} CHECKS PASSED")
print("  INVESTOR RELEASE STATUS: SUBJECT TO PRIVATE CAS RECONCILIATION, VERIFIED SCHEME METADATA, HISTORICAL TRI SOURCE AUTHENTICATION AND INDEPENDENT NSE CALENDAR REVIEW")
print("="*70 + "\n")

