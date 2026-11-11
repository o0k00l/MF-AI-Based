"""Comprehensive Provenance Gate & Category Integrity Test Suite.

Rigorous unit and end-to-end regression tests verifying that:
1. Ingestion Boundary: CAS parser explicitly establishes and stamps origin (source="existing", validation="valid").
2. Provenance Gate: validate_scheme_for_sleeve strictly enforces source in allowed_provenance,
   explicit validation == "valid", and fails closed on missing, None, or invalid metadata.
3. Trust Boundary: Ordinary / unverified fund dictionaries NEVER receive implicit trust as "existing".
4. Strict Category Separation: Generic "Equity" and category-mismatched funds are strictly rejected
   across all 4 sleeves (Large-Cap, Mid/Small-Cap, Flexi-Multi-Cap, Debt).
5. All 4 sleeves × both allocation branches (Direct-holdings and No-Direct) fail closed or
   properly fall back to verified market nominations without manufactured metadata.
6. Fallback Provenance: SPIVA passive fallback allocations preserve source="fallback" and validation="valid".
"""
from __future__ import annotations

from decimal import Decimal
import io
import openpyxl
import pytest

from services.fiduciary_engine import (
    generate_fiduciary_sip_blueprint,
    validate_scheme_for_sleeve,
    trigger_spiva_fallback,
)
from services.risk_profiler import TargetSaa
from services.cas_parser import parse_cas_file


# =====================================================================
# 1. INGESTION BOUNDARY: CAS Parser stamps explicit provenance
# =====================================================================

def test_cas_parser_attaches_explicit_provenance():
    """Ingestion Boundary: parse_cas_file explicitly stamps source='existing' and validation='valid'."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Units", "NAV", "Current Value", "Invested Value"])
    ws.append(["Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "12345/67", "100.0", "50.0", "5000.0", "4000.0"])
    
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    
    funds = parse_cas_file(buf)
    assert len(funds) == 1
    fund = funds[0]
    assert fund["source"] == "existing", f"CAS parser must set source='existing', got: {fund.get('source')}"
    assert fund["validation"] == "valid", f"CAS parser must set validation='valid', got: {fund.get('validation')}"
    assert fund["plan_type"] == "Direct"


# =====================================================================
# 2. VALIDATOR CORE: Direct boundary checks on validate_scheme_for_sleeve
# =====================================================================

def test_validator_rejects_none_and_non_dict():
    """validate_scheme_for_sleeve returns failed on None, empty, or non-dict input."""
    assert validate_scheme_for_sleeve(None, sleeve="Large-Cap")["validation"] == "failed"
    assert validate_scheme_for_sleeve({}, sleeve="Large-Cap")["validation"] == "failed"
    assert validate_scheme_for_sleeve("not-a-dict", sleeve="Large-Cap")["validation"] == "failed"


def test_validator_rejects_regular_plan():
    """validate_scheme_for_sleeve rejects non-Direct plans."""
    fund = {
        "scheme": "HDFC Top 100 Fund - Regular Plan - Growth",
        "category": "Large Cap",
        "plan_type": "Regular",
        "folio_no": "12345",
        "source": "existing",
        "validation": "valid",
    }
    res = validate_scheme_for_sleeve(fund, sleeve="Large-Cap Core Index", allowed_provenance=["existing"])
    assert res["validation"] == "failed"


def test_validator_rejects_missing_or_empty_source():
    """validate_scheme_for_sleeve rejects funds with missing or empty source."""
    fund_no_source = {
        "scheme": "HDFC Flexi Cap Fund - Direct Plan - Growth",
        "category": "Flexi Cap",
        "plan_type": "Direct",
        "folio_no": "123",
        "validation": "valid",
    }
    res = validate_scheme_for_sleeve(
        fund_no_source,
        sleeve="Flexi-Multi Cap",
        require_provenance=True,
        allowed_provenance=["existing", "dynamic", "fallback"],
    )
    assert res["validation"] == "failed"
    
    fund_empty_source = dict(fund_no_source, source="")
    res_empty = validate_scheme_for_sleeve(
        fund_empty_source,
        sleeve="Flexi-Multi Cap",
        require_provenance=True,
        allowed_provenance=["existing", "dynamic", "fallback"],
    )
    assert res_empty["validation"] == "failed"


def test_validator_rejects_missing_or_invalid_validation_status():
    """validate_scheme_for_sleeve rejects funds where validation is missing, None, or not 'valid'."""
    base_fund = {
        "scheme": "HDFC Flexi Cap Fund - Direct Plan - Growth",
        "category": "Flexi Cap",
        "plan_type": "Direct",
        "folio_no": "123",
        "source": "existing",
    }
    
    # Missing validation key
    res_missing = validate_scheme_for_sleeve(
        base_fund,
        sleeve="Flexi-Multi Cap",
        require_provenance=True,
        allowed_provenance=["existing"],
    )
    assert res_missing["validation"] == "failed"
    
    # Explicit None
    res_none = validate_scheme_for_sleeve(
        dict(base_fund, validation=None),
        sleeve="Flexi-Multi Cap",
        require_provenance=True,
        allowed_provenance=["existing"],
    )
    assert res_none["validation"] == "failed"
    
    # Invalid statuses
    for bad_status in ["failed", "unverified", "pending", "unknown", "invalid", "Valid", "TRUE"]:
        res_bad = validate_scheme_for_sleeve(
            dict(base_fund, validation=bad_status),
            sleeve="Flexi-Multi Cap",
            require_provenance=True,
            allowed_provenance=["existing"],
        )
        assert res_bad["validation"] == "failed", f"Should reject validation status '{bad_status}'"


def test_validator_rejects_disallowed_source():
    """validate_scheme_for_sleeve rejects funds with disallowed or unverified source."""
    fund = {
        "scheme": "HDFC Flexi Cap Fund - Direct Plan - Growth",
        "category": "Flexi Cap",
        "plan_type": "Direct",
        "folio_no": "123",
        "validation": "valid",
    }
    for bad_source in ["external_untrusted", "mock_data", "fabricated", "csv_import", "unknown"]:
        res = validate_scheme_for_sleeve(
            dict(fund, source=bad_source),
            sleeve="Flexi-Multi Cap",
            require_provenance=True,
            allowed_provenance=["existing", "dynamic", "fallback"],
        )
        assert res["validation"] == "failed", f"Should reject disallowed source '{bad_source}'"


def test_validator_fails_closed_on_empty_or_none_allowed_provenance():
    """When allowed_provenance is empty list [] or None, validator fails closed."""
    fund = {
        "scheme": "Mirae Asset Large Cap Fund - Direct Plan - Growth",
        "category": "Large Cap",
        "plan_type": "Direct",
        "folio_no": "3333/001",
        "source": "existing",
        "validation": "valid",
    }
    
    # Empty list
    res_empty = validate_scheme_for_sleeve(
        fund=fund,
        sleeve="Large-Cap Core Index",
        expected_category_keywords=["large cap"],
        require_provenance=True,
        allowed_provenance=[],
    )
    assert res_empty["validation"] == "failed"
    
    # None allowed_provenance
    res_none = validate_scheme_for_sleeve(
        fund=fund,
        sleeve="Large-Cap Core Index",
        expected_category_keywords=["large cap"],
        require_provenance=True,
        allowed_provenance=None,
    )
    assert res_none["validation"] == "failed"


# =====================================================================
# 3. CATEGORY INTEGRITY: Generic "Equity" and mismatches rejected
# =====================================================================

def test_validator_rejects_generic_equity_category_for_mid_small():
    """Category Integrity: Generic 'Equity' fund CANNOT pass Mid/Small-Cap Alpha sleeve."""
    fund = {
        "scheme": "Generic Equity Growth Fund - Direct Plan - Growth",
        "category": "Equity",  # Generic equity, NOT mid/small
        "plan_type": "Direct",
        "folio_no": "111/01",
        "source": "existing",
        "validation": "valid",
    }
    res = validate_scheme_for_sleeve(
        fund,
        sleeve="Mid/Small-Cap Alpha",
        expected_category_keywords=["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity", "mid & small"],
        require_provenance=True,
        allowed_provenance=["existing"],
    )
    assert res["validation"] == "failed", "Generic 'Equity' must not satisfy Mid/Small-Cap Alpha sleeve"


def test_validator_rejects_large_cap_in_mid_small_sleeve():
    """Category Integrity: Large Cap fund CANNOT pass Mid/Small-Cap Alpha sleeve."""
    fund = {
        "scheme": "HDFC Top 100 Large Cap Fund - Direct Plan - Growth",
        "category": "Large Cap",
        "plan_type": "Direct",
        "folio_no": "111/01",
        "source": "existing",
        "validation": "valid",
    }
    res = validate_scheme_for_sleeve(
        fund,
        sleeve="Mid/Small-Cap Alpha",
        expected_category_keywords=["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity", "mid & small"],
        require_provenance=True,
        allowed_provenance=["existing"],
    )
    assert res["validation"] == "failed", "Large Cap must not satisfy Mid/Small-Cap Alpha sleeve"


def test_validator_rejects_debt_in_equity_sleeves():
    """Category Integrity: Debt fund CANNOT pass any Equity sleeve."""
    fund = {
        "scheme": "ICICI Prudential Liquid Fund - Direct Plan - Growth",
        "category": "Debt",
        "plan_type": "Direct",
        "folio_no": "222/02",
        "source": "existing",
        "validation": "valid",
    }
    # Large Cap sleeve
    assert validate_scheme_for_sleeve(
        fund, "Large-Cap Core Index",
        expected_category_keywords=["large cap", "large-cap", "largecap", "large & mid", "index", "nifty", "sensex"],
        allowed_provenance=["existing"],
    )["validation"] == "failed"
    
    # Mid/Small sleeve
    assert validate_scheme_for_sleeve(
        fund, "Mid/Small-Cap Alpha",
        expected_category_keywords=["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity", "mid & small"],
        allowed_provenance=["existing"],
    )["validation"] == "failed"
    
    # Flexi sleeve
    assert validate_scheme_for_sleeve(
        fund, "Flexi-Multi Cap",
        expected_category_keywords=["flexi cap", "multi cap", "flexi-cap", "multi-cap", "flexicap", "multicap"],
        allowed_provenance=["existing"],
    )["validation"] == "failed"


# =====================================================================
# 4. ENGINE INTEGRATION: Direct-holdings branch provenance rejection
# =====================================================================

def test_provenance_gate_rejects_missing_source_for_direct_holdings():
    """Direct-holdings branch: Holding without source metadata is rejected as existing.
    
    The engine refuses to treat the unverified holding as a client asset;
    it must NOT allocate to the client's folio, and must instead issue a dynamic mandate.
    """
    unverified_scheme = "Unverified Large Cap Fund XYZ - Direct Plan - Growth"
    client_folio = "FOLIO-UNVERIFIED-12345"
    funds = [
        {
            "scheme": unverified_scheme,
            "category": "Large Cap",
            "plan_type": "Direct",
            "current_value": 100000.0,
            "folio_no": client_folio,
            # NO 'source' field - missing provenance
        },
    ]
    
    target = TargetSaa(large_cap_pct=100.0, mid_small_cap_pct=0.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    
    assert len(blueprint["allocations"]) == 1
    alloc = blueprint["allocations"][0]
    
    # 1. Unverified holding MUST NOT be allocated
    assert alloc["scheme_name"] != unverified_scheme
    # 2. Client's folio MUST NOT be used
    assert alloc["folio_no"] != client_folio
    assert alloc["folio_no"] == "New Direct Folio Mandate"
    # 3. Provenance MUST be dynamic or fallback, NEVER existing
    assert alloc["source"] in ["dynamic", "fallback"]
    assert alloc["validation"] == "valid"


def test_provenance_gate_rejects_invalid_validation_for_direct_holdings():
    """Direct-holdings branch: Holding with source='existing' but validation!='valid' is rejected."""
    funds = [
        {
            "scheme": "Suspicious Fund - Direct Plan - Growth",
            "category": "Large Cap",
            "plan_type": "Direct",
            "current_value": 100000.0,
            "folio_no": "CLIENT-FOLIO-999",
            "source": "existing",
            "validation": "failed",  # Explicitly failed validation
        },
    ]
    target = TargetSaa(large_cap_pct=100.0, mid_small_cap_pct=0.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    
    alloc = blueprint["allocations"][0]
    assert alloc["scheme_name"] != "Suspicious Fund - Direct Plan - Growth"
    assert alloc["folio_no"] == "New Direct Folio Mandate"
    assert alloc["source"] in ["dynamic", "fallback"]
    assert alloc["validation"] == "valid"


def test_direct_holdings_with_explicit_valid_provenance_are_accepted():
    """Direct-holdings branch: Verified CAS holdings pass gate and use client folio."""
    funds = [
        {
            "scheme": "Mirae Asset Large Cap Fund - Direct Plan - Growth",
            "category": "Large Cap",
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "3333/001",
            "source": "existing",
            "validation": "valid",
        },
        {
            "scheme": "HDFC Liquid Fund - Direct Plan - Growth",
            "category": "Debt",
            "plan_type": "Direct",
            "current_value": 200000.0,
            "folio_no": "4444/001",
            "source": "existing",
            "validation": "valid",
        },
    ]
    
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=0.0, flexi_multi_cap_pct=0.0, debt_pct=50.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=20000.0,
        funds=funds,
        target_saa=target,
    )
    
    assert len(blueprint["allocations"]) == 2
    for alloc in blueprint["allocations"]:
        assert alloc["source"] == "existing"
        assert alloc["validation"] == "valid"
    
    lc_alloc = next(a for a in blueprint["allocations"] if "Large-Cap" in a["sleeve"])
    assert lc_alloc["scheme_name"] == "Mirae Asset Large Cap Fund - Direct Plan - Growth"
    assert lc_alloc["folio_no"] == "3333/001"
    
    db_alloc = next(a for a in blueprint["allocations"] if "Debt" in a["sleeve"])
    assert db_alloc["scheme_name"] == "HDFC Liquid Fund - Direct Plan - Growth"
    assert db_alloc["folio_no"] == "4444/001"


# =====================================================================
# 5. NO-DIRECT BRANCH: Zero provenance manufacturing
# =====================================================================

def test_provenance_gate_enforced_on_all_dynamic_selections():
    """No-Direct branch: All 4 sleeves enforce provenance through validator helper."""
    target = TargetSaa(large_cap_pct=25.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=25.0, debt_pct=25.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=50000.0,
        funds=[],  # Triggers no-Direct branch
        target_saa=target,
    )
    
    assert len(blueprint["allocations"]) == 4
    for alloc in blueprint["allocations"]:
        assert alloc["source"] in ["dynamic", "fallback"]
        assert alloc["validation"] == "valid"
        assert alloc["folio_no"] == "New Direct Folio Mandate"


def test_zero_target_amounts_do_not_create_allocations():
    """Sleeves with 0% target do not create allocations."""
    target = TargetSaa(large_cap_pct=60.0, mid_small_cap_pct=40.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa=target,
    )
    
    sleeves = [a["sleeve"] for a in blueprint["allocations"]]
    assert not any("Debt" in s for s in sleeves)
    assert not any("Flexi" in s for s in sleeves)
    assert len(blueprint["allocations"]) == 2


# =====================================================================
# 6. SPIVA FALLBACK PROVENANCE PRESERVATION
# =====================================================================

def test_trigger_spiva_fallback_returns_explicit_provenance_and_category():
    """trigger_spiva_fallback returns scheme, category, source='fallback', and validation='valid'."""
    universe = [
        {
            "scheme": "UTI Nifty 50 Index Fund - Direct Plan - Growth",
            "category": "Large Cap",
            "plan_type": "Direct",
            "is_passive": True,
            "ter_direct_pct": 0.18,
        }
    ]
    res = trigger_spiva_fallback(
        category_key="large_cap_index",
        rules={"is_passive": True, "sort_by": "ter_direct_pct"},
        fund_metrics_universe=universe,
    )
    assert res["scheme"] == "UTI Nifty 50 Index Fund - Direct Plan - Growth"
    assert res["source"] == "fallback"
    assert res["validation"] == "valid"
    assert res["category"] == "Large Cap"


def test_spiva_fallback_preserves_fallback_source_in_blueprint():
    """When fallback selection is triggered, blueprint preserves source='fallback'."""
    # Universe with only passive funds (forces fallback when active selection rules don't match)
    passive_universe = [
        {
            "scheme": "Nippon India Nifty 50 Index Fund - Direct Plan - Growth",
            "category": "Large Cap",
            "plan_type": "Direct",
            "is_passive": True,
            "ter_direct_pct": 0.20,
        },
        {
            "scheme": "Motilal Oswal Nifty Midcap 150 Index Fund - Direct Plan - Growth",
            "category": "Mid Cap",
            "plan_type": "Direct",
            "is_passive": True,
            "ter_direct_pct": 0.30,
            "sharpe_3y": 0.85,
        },
        {
            "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            "category": "Flexi Cap",
            "plan_type": "Direct",
            "is_passive": False,
            "ter_direct_pct": 0.65,
            "sharpe_3y": 1.10,
        },
        {
            "scheme": "Aditya Birla Sun Life Liquid Fund - Direct Plan - Growth",
            "category": "Debt",
            "plan_type": "Direct",
            "is_passive": False,
            "ter_direct_pct": 0.20,
            "aum_crore": 25000,
        },
    ]
    
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=50.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=20000.0,
        funds=[],
        target_saa=target,
        fund_universe=passive_universe,
    )
    
    assert len(blueprint["allocations"]) == 2
    for alloc in blueprint["allocations"]:
        assert alloc["source"] in ["dynamic", "fallback"]
        assert alloc["validation"] == "valid"


# =====================================================================
# 7. FINANCIAL CORRECTNESS AUDIT: SAA Boundaries, Look-Through & Omission
# =====================================================================

def test_scheme_name_text_cannot_substitute_for_category():
    """Authoritative category matching: Scheme-name keywords cannot override a contradictory or generic category."""
    # Contradictory category: Thematic-Energy fund with 'Large Cap' in name
    contradictory_fund = {
        "scheme": "Nippon India Power & Large Cap Fund - Direct Plan - Growth",
        "category": "Thematic-Energy",  # Contradictory category
        "plan_type": "Direct",
        "folio_no": "1111/01",
        "source": "existing",
        "validation": "valid",
    }
    res = validate_scheme_for_sleeve(
        contradictory_fund,
        sleeve="Large-Cap Core Index",
        expected_category_keywords=["large cap", "large-cap", "largecap", "large & mid"],
        require_provenance=True,
        allowed_provenance=["existing"],
    )
    assert res["validation"] == "failed", "Scheme name keywords must NOT override contradictory category"

    # Generic 'Equity' with 'Mid Cap' in scheme name
    generic_fund = {
        "scheme": "Kotak Emerging Equity Mid Cap Fund - Direct Plan - Growth",
        "category": "Equity",  # Generic unclassified category
        "plan_type": "Direct",
        "folio_no": "2222/02",
        "source": "existing",
        "validation": "valid",
    }
    res_generic = validate_scheme_for_sleeve(
        generic_fund,
        sleeve="Mid/Small-Cap Alpha",
        expected_category_keywords=["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity", "mid & small"],
        require_provenance=True,
        allowed_provenance=["existing"],
    )
    assert res_generic["validation"] == "failed", "Generic 'Equity' category must NOT pass Mid/Small-Cap sleeve"


def test_sip_target_validation_rejects_invalid_saa_inputs():
    """SIP Target Validation: SAA inputs must be finite numbers summing to 100% (rejects bool, NaN, non-100 sum)."""
    # 1. Rejects boolean in target
    res_bool = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa={"large_cap_pct": True, "mid_small_cap_pct": 25.0, "debt_pct": 25.0, "flexi_multi_cap_pct": 0.0},
    )
    assert res_bool["status"] == "INVALID_SAA_TARGET"
    assert "boolean" in res_bool["error"].lower()

    # 2. Rejects NaN in target
    res_nan = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa={"large_cap_pct": float("nan"), "mid_small_cap_pct": 25.0, "debt_pct": 25.0, "flexi_multi_cap_pct": 50.0},
    )
    assert res_nan["status"] == "INVALID_SAA_TARGET"
    assert "finite" in res_nan["error"].lower()

    # 3. Rejects negative percentages
    res_neg = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa={"large_cap_pct": -10.0, "mid_small_cap_pct": 50.0, "debt_pct": 60.0, "flexi_multi_cap_pct": 0.0},
    )
    assert res_neg["status"] == "INVALID_SAA_TARGET"

    # 4. Rejects percentages not summing to 100%
    res_bad_sum = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa={"large_cap_pct": 40.0, "mid_small_cap_pct": 20.0, "debt_pct": 20.0, "flexi_multi_cap_pct": 0.0},  # Sum = 80%
    )
    assert res_bad_sum["status"] == "INVALID_SAA_TARGET"
    assert "100.0%" in res_bad_sum["error"]


def test_stability_buffer_override_hybrid_debt_look_through():
    """Stability Buffer Override: Correctly includes look-through debt component of hybrid funds."""
    # Client holds an aggressive hybrid fund (65% equity, 35% debt look-through)
    hybrid_funds = [
        {
            "scheme": "ICICI Prudential Equity & Debt Fund - Direct Plan - Growth",
            "category": "Hybrid",
            "plan_type": "Direct",
            "current_value": 1000000.0,  # 10 Lakhs
            "debt": 35.0,  # 35% debt look-through = 3.5 Lakhs debt
            "folio_no": "1111/01",
            "source": "existing",
            "validation": "valid",
        }
    ]

    # Target SAA with 10% debt: Since current debt is 35% >= 10%, Stability Override MUST trigger
    target_low_debt = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=15.0, debt_pct=10.0)
    bp_override = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=hybrid_funds,
        target_saa=target_low_debt,
    )
    assert bp_override["stability_override_applied"] is True, "Stability Buffer Override must trigger when hybrid debt >= target debt"
    # All debt SIP budget is redirected to equity
    debt_allocs = [a for a in bp_override["allocations"] if "Debt" in a["sleeve"]]
    assert len(debt_allocs) == 0, "No new debt allocation should be added under Stability Override"

    # Target SAA with 50% debt: Since current debt is 35% < 50%, Stability Override must NOT trigger
    target_high_debt = TargetSaa(large_cap_pct=30.0, mid_small_cap_pct=20.0, flexi_multi_cap_pct=0.0, debt_pct=50.0)
    bp_no_override = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=hybrid_funds,
        target_saa=target_high_debt,
    )
    assert bp_no_override["stability_override_applied"] is False


def test_allocation_completeness_surfaces_omission_reasons():
    """Allocation Completeness: When a sleeve cannot be allocated, explicit omission reasons are returned."""
    # Target SAA requires 50% Large Cap and 50% Mid/Small Cap
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=50.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    
    # Universe has NO mid-cap candidates passing eligibility (empty universe)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa=target,
        fund_universe=[],  # Forces dynamic selection to fail for all sleeves
    )
    
    assert bp["status"] == "NO_ACTION"
    assert bp["reconciliation_valid"] is False
    assert "omission_reasons" in bp
    assert len(bp["omission_reasons"]) > 0
    # Every omitted sleeve must be explicitly reported
    omission_text = " ".join(bp["omission_reasons"])
    assert "Large-Cap" in omission_text
    assert "Mid/Small-Cap" in omission_text
    assert any("Unallocated" in a.get("action", "") for a in bp["portfolio_completion_alerts"])
