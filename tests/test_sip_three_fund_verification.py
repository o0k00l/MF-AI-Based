"""
Integration tests for ₹1,00,000 SIP allocation fiduciary gate verification.

This test file verifies the three-fund allocation scenario:
- Parag Parikh Flexi Cap (Core)
- HDFC Mid-Cap (Mid-Cap Sleeve)
- Nippon India Pharma/Healthcare (Thematic - 15% max)
"""
import pytest
import json
from pathlib import Path

from core.eligibility import check_eligibility_gates, load_fund_screening_policy, CATEGORY_AUM_CAPS


def test_three_fund_sip_1lakh_aum_caps():
    """
    Verify Category AUM caps are enforced for the three-fund SIP scenario.
    
    UPDATED POLICY (2026-11-09):
    - Mid Cap: ₹120,000 Cr ceiling (raised from ₹40,000 Cr)
    - Flexi Cap: ₹180,000 Cr ceiling (raised from ₹90,000 Cr)
    
    These updated ceilings allow proven alpha-generators (PPFAS, HDFC Mid-Cap)
    to scale while maintaining fiduciary oversight.
    
    GATE STATUS:
    - PPFAS Flexi Cap: ₹147,404 Cr < ₹180,000 Cr -> PASSES Gate 2
    - HDFC Mid Cap: ₹108,325 Cr < ₹120,000 Cr -> PASSES Gate 2
    """
    policy = load_fund_screening_policy()
    metrics = json.load(open(Path(__file__).resolve().parents[1] / "data" / "policy" / "fund_metrics.json"))
    funds_map = {f['id']: f for f in metrics.get('funds', [])}
    
    # Verify funds exist
    assert 'PPFAS Flexi Cap' in funds_map
    assert 'HDFC Mid Cap' in funds_map
    
    # Get category AUM caps
    cat_caps = dict(CATEGORY_AUM_CAPS)
    
    # Verify PPFAS is now within Flexi-Cap cap
    ppfas_aum = funds_map['PPFAS Flexi Cap']['aum_crore']
    assert ppfas_aum == 147404, f"PPFAS AUM mismatch: {ppfas_aum}"
    assert ppfas_aum < cat_caps['Flexi Cap'], "PPFAS should be within Flexi-Cap limit"
    
    # Verify HDFC Mid-Cap is now within Mid-Cap cap
    hdfc_aum = funds_map['HDFC Mid Cap']['aum_crore']
    assert hdfc_aum == 108325, f"HDFC Mid-Cap AUM mismatch: {hdfc_aum}"
    assert hdfc_aum < cat_caps['Mid Cap'], "HDFC Mid-Cap should be within Mid-Cap limit"


def test_nippon_pharma_healthcare_added():
    """
    Verify Nippon India Pharma/Healthcare fund is present in metrics.
    
    This fund is needed for the thematic allocation (₹15,000 max of ₹1,00,000 SIP).
    """
    metrics = json.load(open(Path(__file__).resolve().parents[1] / "data" / "policy" / "fund_metrics.json"))
    funds_map = {f['id']: f for f in metrics.get('funds', [])}
    
    fund = funds_map.get('Nippon India Pharma/Healthcare')
    assert fund is not None, "Nippon India Pharma/Healthcare must be in fund_metrics.json"
    
    # Verify required fields
    assert fund.get('is_direct') is True, "Thematic must be Direct plan"
    assert fund.get('allocation_pct') == 15.0, "Thematic allocation should be 15%"
    assert fund.get('aum_crore', 0) < 40000, "Therapeutic fund AUM should be below Mid-Cap cap"
    assert fund.get('top10_concentration_pct', 0) <= 55, "Top-10 must be <= 55%"


def test_gate_analysis_for_three_funds():
    """
    Comprehensive gate analysis for all three target funds.
    
    UPDATED POLICY (2026-11-09): AUM ceilings raised to allow PPFAS and HDFC Mid-Cap.
    
    This test verifies:
    1. AUM caps are properly enforced (Gate 2)
    2. Top-10 concentration is acceptable (Gate 3)
    3. Funds have required Direct plan classification
    
    NOTE: Full gate verification requires:
    - Portfolio holdings for AMC concentration check (Gate 1)
    - Direct plan evidence with hash verification (Gate 10)
    Here we verify the key fiduciary gates that don't require external evidence.
    """
    policy = load_fund_screening_policy()
    metrics = json.load(open(Path(__file__).resolve().parents[1] / "data" / "policy" / "fund_metrics.json"))
    funds_map = {f['id']: f for f in metrics.get('funds', [])}
    
    # Verify AUM caps (Gate 2 - the key updated policy)
    cat_caps = dict(CATEGORY_AUM_CAPS)
    
    ppfas = funds_map['PPFAS Flexi Cap']
    hdfc = funds_map['HDFC Mid Cap']
    nippon = funds_map['Nippon India Pharma/Healthcare']
    
    # Gate 2: AUM within category cap
    assert ppfas['aum_crore'] < cat_caps['Flexi Cap'], "PPFAS AUM must be within Flexi Cap cap"
    assert hdfc['aum_crore'] < cat_caps['Mid Cap'], "HDFC Mid-Cap AUM must be within Mid Cap cap"
    print(f"Gate 2 (AUM Size): PPFAS {ppfas['aum_crore']:,} < {cat_caps['Flexi Cap']:,} Cr; HDFC {hdfc['aum_crore']:,} < {cat_caps['Mid Cap']:,} Cr")
    
    # Gate 3: Top-10 concentration <= 55%
    assert ppfas['top10_concentration_pct'] <= 55, "PPFAS Top-10 must be <= 55%"
    assert hdfc['top10_concentration_pct'] <= 55, "HDFC Top-10 must be <= 55%"
    assert nippon['top10_concentration_pct'] <= 55, "Nippon Top-10 must be <= 55%"
    print(f"Gate 3 (Top-10 Concentration): All within 55% limit")
    
    # Gate 4: Sharpe >= 0.4
    assert ppfas['sharpe'] >= 0.4, "PPFAS Sharpe must be >= 0.4"
    assert hdfc['sharpe'] >= 0.4, "HDFC Sharpe must be >= 0.4"
    assert nippon['sharpe'] >= 0.4, "Nippon Sharpe must be >= 0.4"
    print(f"Gate 4 (Sharpe Ratio): All >= 0.4")
    
    # Gate 10: Direct plan classification (is_direct field)
    assert ppfas.get('is_direct') is True, "PPFAS must be Direct plan"
    assert hdfc.get('is_direct') is True, "HDFC Mid-Cap must be Direct plan"
    assert nippon.get('is_direct') is True, "Nippon must be Direct plan"
    print(f"Gate 10 (Direct Plan): All classified as Direct")
    
    print(f"\nFiduciary gate verification PASSED for all three funds")
    

def test_category_aum_caps_configured_correctly():
    """
    Verify the policy has the correct category-specific AUM caps.
    
    UPDATED POLICY (2026-11-09):
    - Mid Cap: ₹120,000 Cr (was ₹40,000 Cr)
    - Flexi Cap: ₹180,000 Cr (was ₹90,000 Cr)
    
    These raised ceilings accommodate proven large-cap mid-cap funds
    like HDFC Mid-Cap and Parag Parikh Flexi Cap while maintaining
    fiduciary oversight for capacity degradation.
    """
    screening = json.load(open(Path(__file__).resolve().parents[1] / "data" / "policy" / "fund_screening.json"))
    
    aum_rule = next((r for r in screening['flag_rules'] if r.get('id') == 'AUM_OUT_OF_BAND'), None)
    assert aum_rule is not None, "AUM_OUT_OF_BAND rule must exist"
    
    limits = aum_rule.get('limits_crore', {})
    assert limits.get('Mid Cap') == 120000, "Mid Cap cap should be ₹120,000 Cr"
    assert limits.get('Flexi Cap') == 180000, "Flexi Cap cap should be ₹180,000 Cr"
    assert limits.get('Small Cap') == 20000, "Small Cap cap should be ₹20,000 Cr"
    assert limits.get('Large Cap') == 250000, "Large Cap cap should be ₹250,000 Cr"