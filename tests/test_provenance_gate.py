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
import json
import hashlib
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
    # Client holds an aggressive hybrid fund (72% equity, 28% debt look-through)
    hybrid_funds = [
        {
            "scheme": "ICICI Prudential Equity & Debt Fund - Direct Plan - Growth",
            "category": "Hybrid",
            "category_verified": True,
            "plan_type": "Direct",
            "current_value": 1000000.0,  # 10 Lakhs
            "folio_no": "1111/01",
            "source": "existing",
            "validation": "valid",
            "portfolio_exposure_verified": True,
            "verified_debt_pct": 28.0,
            "exposure_source": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
            "exposure_as_of": "2026-08-31",
            "exposure_evidence": {
                "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
                "source_document": "sharpely_monthly_disclosure_2026_08.json",
                "scheme_code": "ICICI Pru Equity & Debt",
                "reporting_period": "2026-08-31",
                "retrieval_date": "2026-11-07",
                "debt_pct": 28.0,
                "equity_pct": 72.0,
                "is_verified": True,
                "evidence_hash": "c14664114a8075778b73a96a0eccdd8ad3a8cfb1cc56639ce9579ca045f88587",
            },
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


# =====================================================================
# 8. FINANCIAL AUDIT: AUTHORITATIVE SCHEME MASTER & EXPOSURE BOUNDARIES
# =====================================================================

def test_unknown_scheme_remains_unclassified_in_cas():
    """Authoritative Scheme Master: Unknown scheme in CAS must remain strictly unclassified (category=None)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Units", "NAV", "Current Value"])
    ws.append(["Fake Moonshot Crypto Index Arbitrage Fund Direct Growth", 100.0, 50.0, 5000.0])
    
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    
    funds = parse_cas_file(buf)
    assert len(funds) == 1
    f = funds[0]
    
    # 1. Row integrity passes
    assert f["ingestion_status"] == "parsed_valid"
    assert f["validation"] == "valid"
    
    # 2. Scheme identity NOT verified
    assert f["scheme_identity_verified"] is False
    assert f["canonical_scheme_name"] is None
    
    # 3. Category MUST be None (NEVER defaulted to "Equity" or guessed from "Index"/"Arbitrage")
    assert f["category"] is None
    assert f["category_verified"] is False
    assert f["asset_class"] is None
    
    # 4. Exposure is unverified
    assert f["portfolio_exposure_verified"] is False
    assert f["verified_debt_pct"] is None


def test_misleading_scheme_name_uses_authoritative_scheme_master_category():
    """Scheme names with misleading keywords preserve true authoritative category from scheme master."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Units", "NAV", "Current Value"])
    # Motilal Defence Index contains "Index" but category in master is Thematic/Sectoral
    ws.append(["Motilal Oswal Defence Index Fund Direct Growth", 100.0, 50.0, 5000.0])
    
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    
    funds = parse_cas_file(buf)
    assert len(funds) == 1
    f = funds[0]
    assert f["scheme_identity_verified"] is True
    # Must NOT be classified as Large Cap just because it contains "Index"
    assert f["category"] != "Large Cap"


def test_dynamic_selection_fails_closed_when_category_is_missing():
    """Dynamic selection must fail closed if candidate lacks an authoritative category (never manufacture 'Equity')."""
    from services.fiduciary_engine import _select_market_nom_fund
    
    rules = {"category": "Large Cap", "sort_by": "aum_crore", "sort_order": "desc"}
    # Candidate with missing category
    unclassified_universe = [
        {"scheme": "No Category Fund Direct Growth", "plan_type": "Direct", "aum_crore": 50000.0, "category": None, "cat": None}
    ]
    res = _select_market_nom_fund(rules, unclassified_universe, nom_key="large_cap_index")
    assert res["validation"] == "failed"
    assert res["source"] == "unavailable"


def test_stability_buffer_override_withheld_on_indeterminate_debt_exposure():
    """Stability Buffer Override fails closed (withheld) if debt exposure is indeterminate."""
    # Client holds an unknown fund without verified factsheet look-through
    funds_unknown_exposure = [
        {
            "scheme": "Unindexed Boutique Hybrid Growth Fund - Direct Plan - Growth",
            "category": "Hybrid",
            "plan_type": "Direct",
            "current_value": 1000000.0,
            "folio_no": "9999/01",
            "source": "existing",
            "validation": "valid",
            # NO debt or verified_debt_pct field provided
        }
    ]
    
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=0.0, debt_pct=25.0)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds_unknown_exposure,
        target_saa=target,
    )
    
    # Stability Override MUST NOT trigger based on a guess (no 35% assumption)
    assert bp["stability_override_applied"] is False
    assert bp["stability_override_status"] == "INDETERMINATE"
    assert "indeterminate" in bp["stability_override_reason"].lower()
    # Debt allocation is preserved
    debt_allocs = [a for a in bp["allocations"] if "Debt" in a["sleeve"]]
    assert len(debt_allocs) == 1
    assert debt_allocs[0]["amount_inr"] == Decimal("2500.00")


def test_stability_buffer_override_withheld_on_malformed_debt_values():
    """Stability Buffer Override fails closed if a holding has non-finite debt values (NaN/inf)."""
    funds_malformed = [
        {
            "scheme": "ICICI Pru Balanced Advantage - Direct Plan - Growth",
            "category": "Hybrid",
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "1111/01",
            "source": "existing",
            "validation": "valid",
            "debt": float("nan"),  # Malformed NaN debt value
        }
    ]
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=0.0, debt_pct=25.0)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds_malformed,
        target_saa=target,
    )
    assert bp["stability_override_applied"] is False
    assert bp["stability_override_status"] == "INDETERMINATE"


def test_stability_calculation_excludes_untrusted_corrupted_records():
    """Corrupted or invalid records (validation!='valid') cannot distort the portfolio debt calculation."""
    funds_with_corrupted = [
        {
            "scheme": "HDFC Liquid Fund - Direct Plan - Growth",
            "category": "Debt",
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "1111/01",
            "source": "existing",
            "validation": "valid",
            "debt": 100.0,
        },
        {
            "scheme": "Corrupted Ghost Holding",
            "category": "Debt",
            "plan_type": "Direct",
            "current_value": 50000000.0,  # Massive 5 Crore fake holding
            "folio_no": "9999/99",
            "source": "existing",
            "validation": "failed",  # Corrupted row
            "debt": 100.0,
        },
    ]
    # Total valid portfolio is 5 Lakhs (100% debt). The 5 Crore fake holding must be excluded.
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=0.0, debt_pct=25.0)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds_with_corrupted,
        target_saa=target,
    )
    # Stability Override triggers because 100% (of valid 5 Lakhs) >= 25%
    assert bp["stability_override_applied"] is True


def test_strict_saa_validation_rejects_non_100_percent_sums():
    """Strict policy invariant: SAA targets summing to 99.9% or 100.1% must fail closed (±0.00% tolerance)."""
    # 99.9% sum
    res_99_9 = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa={"large_cap_pct": 49.9, "mid_small_cap_pct": 25.0, "debt_pct": 25.0, "flexi_multi_cap_pct": 0.0},
    )
    assert res_99_9["status"] == "INVALID_SAA_TARGET"
    assert "100.0%" in res_99_9["error"]

    # 100.1% sum
    res_100_1 = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa={"large_cap_pct": 50.1, "mid_small_cap_pct": 25.0, "debt_pct": 25.0, "flexi_multi_cap_pct": 0.0},
    )
    assert res_100_1["status"] == "INVALID_SAA_TARGET"
    assert "100.0%" in res_100_1["error"]


def test_mixed_regular_and_direct_holdings_provenance():
    """In mixed holdings, Regular plans are strictly rejected from sleeves even if validly parsed."""
    mixed_funds = [
        {
            "scheme": "UTI Nifty 50 Index Fund - Regular Plan - Growth",
            "category": "Large Cap",
            "plan_type": "Regular",  # Regular plan
            "current_value": 300000.0,
            "folio_no": "REG-FOLIO-111",
            "source": "existing",
            "validation": "valid",
        },
        {
            "scheme": "Kotak Emerging Equity Fund - Direct Plan - Growth",
            "category": "Mid Cap",
            "plan_type": "Direct",  # Direct plan
            "current_value": 200000.0,
            "folio_no": "DIR-FOLIO-222",
            "source": "existing",
            "validation": "valid",
        },
    ]
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=50.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=mixed_funds,
        target_saa=target,
    )
    # Direct Mid Cap is allocated to client folio
    mid_alloc = [a for a in bp["allocations"] if "Mid" in a["sleeve"]][0]
    assert mid_alloc["folio_no"] == "DIR-FOLIO-222"
    assert mid_alloc["source"] == "existing"
    
    # Regular Large Cap is REJECTED; client folio is NOT used; new Direct mandate is issued
    large_alloc = [a for a in bp["allocations"] if "Large" in a["sleeve"]][0]
    assert large_alloc["folio_no"] == "New Direct Folio Mandate"
    assert large_alloc["source"] in ["dynamic", "fallback"]


# =====================================================================
# 6. ENHANCED FIDUCIARY AUDIT GATES (COMMIT REMEDIATION)
# =====================================================================

def test_scheme_resolution_eliminates_substring_matching():
    """Substring matching is eliminated: non-exact names never match via substring."""
    from services.cas_parser import resolve_authoritative_scheme
    # 'Nippon India Nifty 50 Index Fund' must NOT resolve to a Mid Cap fund just because 'Nippon India' is in the master
    res_partial = resolve_authoritative_scheme("Nippon India Nifty 50 Index Fund - Direct Plan - Growth")
    assert res_partial is None, "Substring matching must not resolve non-identical scheme"

    # 'HDFC Top 100 Advantage' must NOT resolve to 'HDFC Top 100'
    res_adv = resolve_authoritative_scheme("HDFC Top 100 Advantage Fund - Direct Plan - Growth")
    assert res_adv is None, "Partial scheme name with extra suffix must not match"


def test_scheme_resolution_rejects_ambiguous_matches():
    """Ambiguous queries matching multiple distinct schemes fail closed to None."""
    from services.cas_parser import resolve_authoritative_scheme
    # Construct a synthetic master with ambiguous alias
    ambiguous_master = {
        "schemes": {
            "Scheme Alpha": {
                "sid": 1001,
                "canonical_name": "Scheme Alpha",
                "category": "Large Cap",
                "aliases": ["shared fund alias"],
            },
            "Scheme Beta": {
                "sid": 1002,
                "canonical_name": "Scheme Beta",
                "category": "Mid Cap",
                "aliases": ["shared fund alias"],
            },
        }
    }
    # Query with the ambiguous alias
    res = resolve_authoritative_scheme("shared fund alias", scheme_master=ambiguous_master)
    assert res is None, "Ambiguous matches (>1 matching schemes) must reject to None"


def test_cas_parser_attaches_precise_sources_and_as_of_date():
    """CAS parser stamps SEBI_AMFI identity and SHARPELY factsheet disclosure with authentic as_of."""
    import io
    import openpyxl
    from services.cas_parser import parse_cas_file
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Units", "NAV", "Current Value"])
    ws.append(["HDFC Top 100 Fund - Direct Plan - Growth", 100.0, 50.0, 5000.0])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    funds = parse_cas_file(buf)
    assert len(funds) == 1
    f = funds[0]
    assert f["scheme_identity_verified"] is True
    assert f["scheme_identity_source"] == "SEBI_AMFI_OFFICIAL_SCHEME_MASTER"
    assert f["category_verified"] is True
    assert f["portfolio_exposure_verified"] is True
    assert f["exposure_source"] == "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE"
    assert f["exposure_as_of"] == "2026-08-31"
    assert "heuristic_display_allocations" in f
    assert f["heuristic_display_allocations"]["eq"] >= 0.0


def test_cas_parser_withholds_exposure_verification_when_as_of_missing():
    """CAS parser does not fabricate freshness: missing as_of sets portfolio_exposure_verified=False."""
    import io
    import openpyxl
    from unittest.mock import patch
    from services.cas_parser import parse_cas_file
    # Master entry with metrics but NO as_of date
    synthetic_master = {
        "schemes": {
            "HDFC Top 100": {
                "sid": 16055,
                "canonical_name": "HDFC Top 100",
                "category": "Large Cap",
                "portfolio_debt_pct": 5.0,
                "as_of": None,  # Missing authentic as_of date!
                "aliases": ["hdfc top 100 fund"],
            }
        }
    }
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Units", "NAV", "Current Value"])
    ws.append(["HDFC Top 100 Fund - Direct Plan - Growth", 100.0, 50.0, 5000.0])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    with patch("services.cas_parser.load_authoritative_scheme_master", return_value=synthetic_master):
        funds = parse_cas_file(buf)

    assert len(funds) == 1
    f = funds[0]
    assert f["scheme_identity_verified"] is True
    # Without authentic as_of date, exposure MUST NOT be verified
    assert f["portfolio_exposure_verified"] is False
    assert f["exposure_as_of"] is None
    assert f["exposure_source"] is None
    assert f["verified_debt_pct"] is None


def test_stability_buffer_override_withheld_on_generic_untrusted_debt():
    """Generic untrusted debt field on non-debt category fails closed to INDETERMINATE."""
    from services.risk_profiler import TargetSaa
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    funds = [
        {
            "scheme": "Some Random Hybrid Fund - Direct Plan - Growth",
            "category": "Hybrid",
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "1111/01",
            "source": "existing",
            "validation": "valid",
            "debt": 35.0,  # Generic untrusted debt field without exposure verification
        }
    ]
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=0.0, debt_pct=25.0)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    assert bp["stability_override_applied"] is False
    assert bp["stability_override_status"] == "INDETERMINATE"
    assert "indeterminate" in bp["stability_override_reason"].lower()


def test_stability_buffer_override_fails_closed_when_validation_missing():
    """Holding without explicit validation='valid' fails closed in stability override."""
    from services.risk_profiler import TargetSaa
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    funds = [
        {
            "scheme": "HDFC Liquid Fund - Direct Plan - Growth",
            "category": "Debt",
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "1111/01",
            "source": "existing",
            # validation key is MISSING (must not default to valid)
        }
    ]
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=0.0, debt_pct=25.0)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    # Since holding lacks validation='valid', it is excluded, so stability override cannot apply
    assert bp["stability_override_applied"] is False
    assert bp["stability_override_status"] == "NOT_APPLIED"


def test_convert_cas_funds_to_holdings_maps_missing_category_to_other():
    """Missing category in CAS fund converts to AssetClass.OTHER with 0% equity and 0% debt default."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings
    from core.models import AssetClass
    funds = [
        {
            "scheme": "Unknown Mystery Fund Direct Growth",
            "category": None,  # Missing category
            "plan_type": "Direct",
            "current_value": 100000.0,
            "invested_value": 80000.0,
            "units": 1000.0,
            "nav": 100.0,
            "folio_no": "FOLIO-999",
            "source": "existing",
            "validation": "valid",
        }
    ]
    holdings = convert_cas_funds_to_holdings(funds)
    assert len(holdings) == 1
    h = holdings[0]
    assert h.asset_class == AssetClass.OTHER, f"Expected AssetClass.OTHER, got {h.asset_class}"
    assert h.equity_pct == 0.0, f"Expected 0.0% equity, got {h.equity_pct}"
    assert h.debt_pct == 0.0, f"Expected 0.0% debt, got {h.debt_pct}"


def test_stability_override_reason_reports_original_target_debt_pct():
    """Stability override explanation string reports the true original target debt percentage, not 0.00%."""
    from services.risk_profiler import TargetSaa
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    funds = [
        {
            "scheme": "HDFC Liquid Fund - Direct Plan - Growth",
            "category": "Debt",
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "1111/01",
            "source": "existing",
            "validation": "valid",
        }
    ]
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=0.0, debt_pct=25.0)
    bp = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    assert bp["stability_override_applied"] is True
    reason = bp["stability_override_reason"]
    # Target was 25.00%, reason must state 'target (25.00%)', NOT 'target (0.00%)'
    assert "target (25.00%)" in reason, f"Reason should report original target 25.00%, got: {reason}"


# =====================================================================
# 11. STRUCTURED EXPOSURE EVIDENCE & FIDUCIARY CALCULATION ISOLATION
# =====================================================================

def test_evidence_validation_rejects_missing_and_malformed():
    """validate_exposure_evidence rejects missing fields, bad types, unallowlisted sources, and malformed dates."""
    from datetime import date
    from services.cas_parser import validate_exposure_evidence

    ref_date = date(2026, 11, 11)

    # 1. Non-dict or empty
    assert not validate_exposure_evidence(None)[0]
    assert not validate_exposure_evidence({})[0]
    assert not validate_exposure_evidence("not-a-dict")[0]

    # Valid base template backed by real file on disk and authentic canonical hash
    valid_base = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "scheme_code": 16055,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "debt_pct": 23.86,
        "equity_pct": 73.3,
        "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
        "is_verified": True,
    }
    is_valid, msg = validate_exposure_evidence(valid_base, holding_scheme_code="16055", reference_date=ref_date)
    assert is_valid, f"Expected valid_base to pass, got: {msg}"

    # 2. Unallowlisted source
    bad_source = dict(valid_base, source_name="BLOG_SCRAPER")
    is_valid, msg = validate_exposure_evidence(bad_source, reference_date=ref_date)
    assert not is_valid
    assert "unsupported exposure source" in msg.lower()

    bad_source_2 = dict(valid_base, source_name="REDDIT_THREAD")
    assert not validate_exposure_evidence(bad_source_2, reference_date=ref_date)[0]

    # 3. Missing source document
    no_doc = dict(valid_base, source_document="")
    is_valid, msg = validate_exposure_evidence(no_doc, reference_date=ref_date)
    assert not is_valid
    assert "source_document" in msg.lower()

    # 4. is_verified not True
    unverified = dict(valid_base, is_verified=False)
    assert not validate_exposure_evidence(unverified, reference_date=ref_date)[0]

    # 5. Missing or malformed reporting_period
    no_rep = dict(valid_base, reporting_period="")
    assert not validate_exposure_evidence(no_rep, reference_date=ref_date)[0]

    bad_rep = dict(valid_base, reporting_period="31-10-2026")
    is_valid, msg = validate_exposure_evidence(bad_rep, reference_date=ref_date)
    assert not is_valid
    assert "malformed" in msg.lower() or "iso" in msg.lower()

    # 6. Missing or malformed retrieval_date
    no_ret = dict(valid_base, retrieval_date="")
    assert not validate_exposure_evidence(no_ret, reference_date=ref_date)[0]

    bad_ret = dict(valid_base, retrieval_date="not-a-date")
    assert not validate_exposure_evidence(bad_ret, reference_date=ref_date)[0]

    # 7. Invalid numeric bounds
    bad_equity_neg = dict(valid_base, equity_pct=-5.0)
    assert not validate_exposure_evidence(bad_equity_neg, reference_date=ref_date)[0]

    bad_equity_high = dict(valid_base, equity_pct=105.0)
    assert not validate_exposure_evidence(bad_equity_high, reference_date=ref_date)[0]

    bad_sum = dict(valid_base, equity_pct=70.0, debt_pct=40.0)
    is_valid, msg = validate_exposure_evidence(bad_sum, reference_date=ref_date)
    assert not is_valid
    assert "exceeds 100%" in msg.lower()


def test_evidence_validation_rejects_missing_scheme_code():
    """validate_exposure_evidence fails closed when evidence omits mandatory scheme_code."""
    from datetime import date
    from services.cas_parser import validate_exposure_evidence

    ref_date = date(2026, 11, 11)
    ev_no_code = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "scheme_code": None,  # Missing mandatory scheme_code
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "debt_pct": 23.86,
        "equity_pct": 73.3,
        "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
        "is_verified": True,
    }
    is_valid, msg = validate_exposure_evidence(ev_no_code, reference_date=ref_date)
    assert not is_valid
    assert "missing mandatory scheme_code" in msg.lower()

    ev_empty_code = dict(ev_no_code, scheme_code="")
    assert not validate_exposure_evidence(ev_empty_code, reference_date=ref_date)[0]


def test_evidence_validation_rejects_non_existent_source_document():
    """validate_exposure_evidence fails closed when referenced source_document does not exist on disk."""
    from datetime import date
    from services.cas_parser import validate_exposure_evidence

    ref_date = date(2026, 11, 11)
    ev_missing_file = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "ghost_portfolio_disclosure_never_existed.json",
        "scheme_code": 16055,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "debt_pct": 23.86,
        "equity_pct": 73.3,
        "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
        "is_verified": True,
    }
    is_valid, msg = validate_exposure_evidence(ev_missing_file, reference_date=ref_date)
    assert not is_valid
    assert "does not exist on disk" in msg.lower()


def test_evidence_validation_rejects_fake_and_mismatched_evidence_hash():
    """validate_exposure_evidence fails closed on malformed or fabricated evidence hashes."""
    from datetime import date
    from services.cas_parser import validate_exposure_evidence

    ref_date = date(2026, 11, 11)
    base = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "scheme_code": 16055,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "debt_pct": 23.86,
        "equity_pct": 73.3,
        "is_verified": True,
    }

    # 1. Missing hash
    assert not validate_exposure_evidence(dict(base, evidence_hash=""), reference_date=ref_date)[0]

    # 2. Malformed length / non-hex
    assert not validate_exposure_evidence(dict(base, evidence_hash="short_hash"), reference_date=ref_date)[0]
    assert not validate_exposure_evidence(dict(base, evidence_hash="z" * 64), reference_date=ref_date)[0]

    # 3. Fabricated hash that does not match canonical document bytes
    fake_hash_ev = dict(base, evidence_hash="0" * 64)
    is_valid, msg = validate_exposure_evidence(fake_hash_ev, reference_date=ref_date)
    assert not is_valid
    assert "evidence hash mismatch" in msg.lower()


def test_evidence_validation_rejects_future_dates():
    """validate_exposure_evidence rejects future reporting periods and future retrieval dates."""
    from datetime import date
    from services.cas_parser import validate_exposure_evidence

    ref_date = date(2026, 11, 11)

    future_rep = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "scheme_code": 16055,
        "reporting_period": "2026-12-31",  # Future relative to 2026-11-11
        "retrieval_date": "2026-11-05",
        "equity_pct": 73.3,
        "debt_pct": 23.86,
        "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
        "is_verified": True,
    }
    is_valid, msg = validate_exposure_evidence(future_rep, reference_date=ref_date)
    assert not is_valid
    assert "future reporting_period" in msg.lower()

    future_ret = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "scheme_code": 16055,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-20",  # Future relative to 2026-11-11
        "equity_pct": 73.3,
        "debt_pct": 23.86,
        "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
        "is_verified": True,
    }
    is_valid, msg = validate_exposure_evidence(future_ret, reference_date=ref_date)
    assert not is_valid
    assert "future retrieval_date" in msg.lower()


def test_evidence_validation_rejects_stale_dates():
    """validate_exposure_evidence rejects evidence reporting periods older than 365 days."""
    from datetime import date
    from services.cas_parser import validate_exposure_evidence

    ref_date = date(2026, 11, 11)

    stale_evidence = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "scheme_code": 16055,
        "reporting_period": "2025-10-31",  # ~376 days before 2026-11-11
        "retrieval_date": "2026-11-05",
        "equity_pct": 73.3,
        "debt_pct": 23.86,
        "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
        "is_verified": True,
    }
    is_valid, msg = validate_exposure_evidence(stale_evidence, reference_date=ref_date)
    assert not is_valid
    assert "stale reporting_period" in msg.lower()


def test_evidence_validation_rejects_mismatched_scheme_code():
    """validate_exposure_evidence rejects evidence where scheme_code does not match the holding."""
    from datetime import date
    from services.cas_parser import validate_exposure_evidence

    ref_date = date(2026, 11, 11)

    mismatched_evidence = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "scheme_code": 16055,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "equity_pct": 73.3,
        "debt_pct": 23.86,
        "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
        "is_verified": True,
    }
    # Holding scheme code is 999999
    is_valid, msg = validate_exposure_evidence(mismatched_evidence, holding_scheme_code="999999", reference_date=ref_date)
    assert not is_valid
    assert "scheme code mismatch" in msg.lower()

    # Exact match passes
    is_valid_match, _ = validate_exposure_evidence(mismatched_evidence, holding_scheme_code="16055", reference_date=ref_date)
    assert is_valid_match


def test_category_to_asset_class_explicit_mapping():
    """Authoritative category mapping assigns broad asset classes strictly via allowlist, never falling through to Equity."""
    from services.cas_parser import SEBI_CATEGORY_TO_ASSET_CLASS

    # Equity classes
    assert SEBI_CATEGORY_TO_ASSET_CLASS["flexi cap"] == "Equity"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["mid cap"] == "Equity"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["small cap"] == "Equity"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["large cap"] == "Equity"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["elss"] == "Equity"

    # Debt classes
    assert SEBI_CATEGORY_TO_ASSET_CLASS["liquid"] == "Debt"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["money market"] == "Debt"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["corporate bond"] == "Debt"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["overnight"] == "Debt"

    # Hybrid classes
    assert SEBI_CATEGORY_TO_ASSET_CLASS["balanced advantage"] == "Hybrid"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["arbitrage"] == "Hybrid"
    assert SEBI_CATEGORY_TO_ASSET_CLASS["aggressive hybrid"] == "Hybrid"

    # International
    assert SEBI_CATEGORY_TO_ASSET_CLASS["fund of funds - overseas"] == "International"

    # Unknown categories return None
    assert SEBI_CATEGORY_TO_ASSET_CLASS.get("unregistered_asset_class") is None
    assert SEBI_CATEGORY_TO_ASSET_CLASS.get("cryptocurrency") is None
    assert SEBI_CATEGORY_TO_ASSET_CLASS.get("") is None


def test_convert_cas_funds_does_not_manufacture_percentages_from_category():
    """Unverified CAS funds never receive manufactured 100% equity or 65/35% hybrid defaults."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings
    from core.models import AssetClass

    unverified_hybrid = {
        "scheme": "Unverified Generic Hybrid Fund Direct Growth",
        "category": "Balanced Advantage",
        "category_verified": True,
        "plan_type": "Direct",
        "current_value": 200000.0,
        "invested_value": 180000.0,
        "units": 2000.0,
        "nav": 100.0,
        "folio_no": "F-001",
        "source": "existing",
        "validation": "valid",
        # No exposure_evidence, portfolio_exposure_verified is False
        "portfolio_exposure_verified": False,
    }

    holdings = convert_cas_funds_to_holdings([unverified_hybrid])
    assert len(holdings) == 1
    h = holdings[0]
    assert h.asset_class == AssetClass.HYBRID
    # Must NOT manufacture 65.0% equity or 35.0% debt!
    assert h.equity_pct == 0.0, f"Expected 0.0% measured equity, got {h.equity_pct}"
    assert h.debt_pct == 0.0, f"Expected 0.0% measured debt, got {h.debt_pct}"
    assert h.lookthrough_status == "INDETERMINATE"


def test_evaluate_portfolio_saa_audit_fails_closed_on_indeterminate_holdings():
    """evaluate_portfolio_saa_audit returns status='INDETERMINATE' when any holding lacks verified look-through."""
    from services.fiduciary_engine import evaluate_portfolio_saa_audit

    unverified_funds = [
        {
            "scheme": "Unverified Emerging Opportunities Fund Direct Growth",
            "category": "Mid Cap",
            "plan_type": "Direct",
            "current_value": 300000.0,
            "invested_value": 250000.0,
            "units": 3000.0,
            "nav": 100.0,
            "folio_no": "F-002",
            "source": "existing",
            "validation": "valid",
            "portfolio_exposure_verified": False,
        }
    ]

    target = {"total_equity_pct": 70.0, "debt_pct": 30.0}
    audit = evaluate_portfolio_saa_audit(unverified_funds, target_saa=target)

    assert audit["status"] == "INDETERMINATE"
    assert audit["lookthrough_verified"] is False
    assert len(audit["indeterminate_holdings"]) == 1
    assert "Unverified Emerging Opportunities Fund" in audit["indeterminate_holdings"][0]
    assert "Fiduciary SAA calculations require authenticated factsheet disclosures" in audit["reason"]
    # Fail closed: no rebalance or gap calculated
    assert audit["rebalance_required"] is None
    assert audit["is_debt_deficit"] is None


def test_changing_display_estimates_does_not_alter_fiduciary_recommendations():
    """Mutating heuristic display allocations or display fields has zero effect on fiduciary SIP recommendations or SAA audit."""
    from services.fiduciary_engine import (
        generate_fiduciary_sip_blueprint,
        convert_cas_funds_to_holdings,
        evaluate_portfolio_saa_audit,
    )
    from services.risk_profiler import TargetSaa

    base_fund = {
        "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
        "canonical_scheme_name": "Parag Parikh Flexi Cap Fund",
        "scheme_code": 19701,
        "category": "Flexi Cap",
        "category_verified": True,
        "plan_type": "Direct",
        "current_value": 500000.0,
        "invested_value": 400000.0,
        "units": 10000.0,
        "nav": 50.0,
        "folio_no": "112233/44",
        "source": "existing",
        "validation": "valid",
        "portfolio_exposure_verified": True,
        "verified_equity_pct": 82.24,
        "verified_debt_pct": 6.26,
        "exposure_source": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "exposure_as_of": "2026-08-31",
        "exposure_evidence": {
            "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
            "source_document": "sharpely_monthly_disclosure_2026_08.json",
            "scheme_code": 19701,
            "reporting_period": "2026-08-31",
            "retrieval_date": "2026-11-07",
            "equity_pct": 82.24,
            "debt_pct": 6.26,
            "evidence_hash": "4ab21447b76b35111961599558592329b62f44b8cea0362792cbb72ca1b36330",
            "is_verified": True,
        },
        # Display estimates
        "heuristic_display_allocations": {"eq": 100.0, "debt": 2.0, "lc": 60.0, "mc": 30.0, "sc": 10.0},
        "eq": 82.24,
        "debt": 6.26,
    }

    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=25.0, debt_pct=0.0)

    # Run fiduciary calculations with baseline display estimates
    h1 = convert_cas_funds_to_holdings([base_fund])
    audit1 = evaluate_portfolio_saa_audit([base_fund], target_saa={"total_equity_pct": 100.0, "debt_pct": 0.0})
    bp1 = generate_fiduciary_sip_blueprint(monthly_budget_inr=20000.0, funds=[base_fund], target_saa=target)

    # Now create modified fund where heuristic display allocations are radically changed
    modified_fund = dict(base_fund)
    modified_fund["heuristic_display_allocations"] = {
        "eq": 15.0,     # Radically changed
        "debt": 85.0,   # Radically changed
        "lc": 5.0,
        "mc": 5.0,
        "sc": 5.0,
    }

    h2 = convert_cas_funds_to_holdings([modified_fund])
    audit2 = evaluate_portfolio_saa_audit([modified_fund], target_saa={"total_equity_pct": 100.0, "debt_pct": 0.0})
    bp2 = generate_fiduciary_sip_blueprint(monthly_budget_inr=20000.0, funds=[modified_fund], target_saa=target)

    # Fiduciary outputs must be IDENTICAL
    assert h1[0].equity_pct == h2[0].equity_pct
    assert h1[0].debt_pct == h2[0].debt_pct
    assert audit1["status"] == audit2["status"]
    assert audit1["current_equity_pct"] == audit2["current_equity_pct"]
    assert audit1["current_debt_pct"] == audit2["current_debt_pct"]
    assert bp1["status"] == bp2["status"]
    assert bp1["allocations"] == bp2["allocations"]
    assert bp1["stability_override_applied"] == bp2["stability_override_applied"]


def test_convert_cas_funds_rejects_legacy_boolean_bypass():
    """Supplying portfolio_exposure_verified=True and verified_debt_pct without structured evidence fails closed."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings

    bypass_fund = {
        "scheme": "Adversarial Mystery Fund Direct Growth",
        "category": "Debt",
        "category_verified": False,
        "plan_type": "Direct",
        "current_value": 100000.0,
        "invested_value": 90000.0,
        "units": 1000.0,
        "nav": 100.0,
        "folio_no": "BYPASS-01",
        "source": "existing",
        "validation": "valid",
        # Legacy boolean bypass attempt:
        "portfolio_exposure_verified": True,
        "verified_debt_pct": 50.0,
        "verified_equity_pct": 50.0,
        # NO exposure_evidence dict!
    }

    holdings = convert_cas_funds_to_holdings([bypass_fund])
    assert len(holdings) == 1
    h = holdings[0]
    # Legacy bypass must be rejected
    assert h.lookthrough_status == "INDETERMINATE"
    assert h.debt_pct == 0.0
    assert h.equity_pct == 0.0


def test_generate_sip_blueprint_rejects_legacy_boolean_and_as_of_bypass():
    """generate_fiduciary_sip_blueprint withholds stability override if holding lacks valid exposure evidence."""
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa

    bypass_funds = [
        {
            "scheme": "Adversarial Mystery Liquid Direct Growth",
            "category": "Debt",
            "category_verified": False,
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "BYPASS-02",
            "source": "existing",
            "validation": "valid",
            "portfolio_exposure_verified": True,
            "verified_debt_pct": 100.0,
            # No valid exposure_evidence dict
        }
    ]
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=0.0, debt_pct=25.0)
    bp = generate_fiduciary_sip_blueprint(monthly_budget_inr=10000.0, funds=bypass_funds, target_saa=target)

    # Legacy bypass cannot activate stability override
    assert bp["stability_override_applied"] is False


def test_gold_exposure_is_never_added_to_debt():
    """Gold / commodities exposure is kept separate and is never added to debt_pct."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings

    multi_asset_holding = {
        "scheme": "Adversarial Multi Asset Allocation Direct Growth",
        "category": "Multi Asset Allocation",
        "category_verified": False,
        "plan_type": "Direct",
        "current_value": 200000.0,
        "invested_value": 180000.0,
        "units": 2000.0,
        "nav": 100.0,
        "folio_no": "GOLD-01",
        "source": "existing",
        "validation": "valid",
        "gold": 25.0,
        "exposure_evidence": {
            "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
            "source_document": "sharpely_monthly_disclosure_2026_08.json",
            "scheme_code": 16055,
            "reporting_period": "2026-08-31",
            "retrieval_date": "2026-11-07",
            "debt_pct": 23.86,
            "equity_pct": 73.3,
            "evidence_hash": "770993a53395eb00f6518cb75917797cdf8dc586c4e064e2fd5843d3494611e7",
            "is_verified": True,
        },
    }

    holdings = convert_cas_funds_to_holdings([multi_asset_holding])
    assert len(holdings) == 1
    h = holdings[0]
    # debt_pct must be strictly the measured debt (23.86%), NOT 23.86 + 25.0 = 48.86%!
    assert h.debt_pct == 23.86, f"Gold was incorrectly added to debt! Got {h.debt_pct}, expected 23.86"


def test_category_provenance_requires_verified_category():
    """Unverified categories on unknown schemes are mapped to AssetClass.OTHER and rejected."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings
    from core.models import AssetClass

    unverified_claim = {
        "scheme": "Unregistered Mystery Fund Direct Growth",
        "category": "Liquid",  # Self-declared liquid
        "category_verified": False,  # Not verified!
        "plan_type": "Direct",
        "current_value": 100000.0,
        "invested_value": 90000.0,
        "units": 1000.0,
        "nav": 100.0,
        "folio_no": "UNV-01",
        "source": "existing",
        "validation": "valid",
    }

    holdings = convert_cas_funds_to_holdings([unverified_claim])
    assert len(holdings) == 1
    h = holdings[0]
    # Unverified category cannot map to AssetClass.DEBT
    assert h.asset_class == AssetClass.OTHER


# =====================================================================
# 11. ADVERSARIAL DISCLOSURE INTEGRITY & AUTHENTICITY TESTS
# =====================================================================

def test_evidence_validation_fails_closed_when_scheme_missing_from_disclosure():
    """Fail-Closed: validate_exposure_evidence rejects evidence referencing scheme absent from disclosure store."""
    from services.cas_parser import validate_exposure_evidence
    import hashlib, json

    canonical_obj = {
        "debt_pct": 5.0,
        "equity_pct": 95.0,
        "is_verified": True,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "scheme_code": 99999999,  # Absent from disclosures
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
    }
    rec_hash = hashlib.sha256(json.dumps(canonical_obj, sort_keys=True).encode("utf-8")).hexdigest()

    ev = dict(canonical_obj, evidence_hash=rec_hash)
    is_valid, msg = validate_exposure_evidence(ev, 99999999)
    assert is_valid is False
    assert "not found in disclosure document" in msg


def test_evidence_validation_fails_closed_on_malformed_json_source(tmp_path):
    """Zero Exception Suppression: malformed JSON in source document fails closed with descriptive error."""
    from services.cas_parser import validate_exposure_evidence
    import hashlib

    # Create a corrupted JSON file
    corrupt_file = tmp_path / "corrupt_disclosure.json"
    corrupt_file.write_text("{ this is completely invalid json !!! ", encoding="utf-8")
    corrupt_hash = hashlib.sha256(corrupt_file.read_bytes()).hexdigest()

    ev = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": str(corrupt_file),
        "scheme_code": 10101,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "debt_pct": 4.3,
        "equity_pct": 95.7,
        "evidence_hash": corrupt_hash,
        "is_verified": True,
    }

    is_valid, msg = validate_exposure_evidence(ev, 10101)
    assert is_valid is False
    assert "validation failed: malformed JSON" in msg


def test_evidence_validation_fails_closed_on_mismatched_reporting_period():
    """Reporting Period Reconciliation: evidence claiming different period than disclosure file fails closed."""
    from services.cas_parser import validate_exposure_evidence
    import hashlib, json

    canonical_obj = {
        "debt_pct": 4.3,
        "equity_pct": 95.7,
        "is_verified": True,
        "reporting_period": "2026-07-31",  # Document has 2026-08-31!
        "retrieval_date": "2026-11-07",
        "scheme_code": 10101,
        "source_document": "sharpely_monthly_disclosure_2026_08.json",
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
    }
    rec_hash = hashlib.sha256(json.dumps(canonical_obj, sort_keys=True).encode("utf-8")).hexdigest()

    ev = dict(canonical_obj, evidence_hash=rec_hash)
    is_valid, msg = validate_exposure_evidence(ev, 10101)
    assert is_valid is False
    assert "Reporting period mismatch" in msg


def test_evidence_validation_fails_closed_on_incomplete_asset_class_breakdown(tmp_path):
    """Calculation Reconciliation: disclosure entry whose asset classes do not sum to 100% fails closed."""
    from services.cas_parser import validate_exposure_evidence
    import hashlib, json

    incomplete_store = {
        "_metadata": {
            "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
            "source_authenticity": "PROVISIONAL_INTERNAL",
        },
        "disclosures": {
            "77777": {
                "scheme_code": 77777,
                "canonical_name": "Incomplete Fund",
                "reporting_period": "2026-08-31",
                "retrieval_date": "2026-11-07",
                "is_verified": True,
                "debt_pct": 20.0,
                "equity_pct": 50.0,
                "cash_pct": 0.0,
                "gold_pct": 0.0,
                "other_pct": 0.0,  # Sum = 70.0% != 100.0%!
            }
        }
    }
    doc_path = tmp_path / "incomplete_disclosure.json"
    doc_path.write_text(json.dumps(incomplete_store), encoding="utf-8")
    doc_hash = hashlib.sha256(doc_path.read_bytes()).hexdigest()

    ev = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": str(doc_path),
        "scheme_code": 77777,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "debt_pct": 20.0,
        "equity_pct": 50.0,
        "evidence_hash": doc_hash,
        "is_verified": True,
    }

    is_valid, msg = validate_exposure_evidence(ev, 77777)
    assert is_valid is False
    assert "does not reconcile to 100%" in msg


def test_convert_cas_funds_never_assumes_equity_when_equity_missing():
    """Assumed Equity Bug Prevention: missing equity exposure NEVER defaults to 100 - debt."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings

    # Fund has debt measured but equity is missing/None
    partial_fund = {
        "scheme": "Adversarial Partial Holding Direct Growth",
        "category": "Hybrid",
        "category_verified": True,
        "plan_type": "Direct",
        "current_value": 100000.0,
        "invested_value": 90000.0,
        "units": 1000.0,
        "nav": 100.0,
        "folio_no": "PARTIAL-01",
        "source": "existing",
        "validation": "valid",
        "exposure_evidence": {
            "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
            "source_document": "sharpely_monthly_disclosure_2026_08.json",
            "scheme_code": 10101,
            "reporting_period": "2026-08-31",
            "retrieval_date": "2026-11-07",
            "debt_pct": 4.3,
            "equity_pct": None,  # Missing equity!
            "is_verified": True,
            "evidence_hash": "a" * 64,
        },
    }

    holdings = convert_cas_funds_to_holdings([partial_fund])
    assert len(holdings) == 1
    h = holdings[0]
    # Incomplete measurement must remain missing (0.0%), and status must be INDETERMINATE
    assert h.lookthrough_status == "INDETERMINATE"
    assert h.equity_pct == 0.0
    assert h.debt_pct == 0.0
    assert "No verified factsheet look-through" in h.lookthrough_reason


def test_holding_explanation_never_uses_stale_hardcoded_date():
    """Explanation Governance: missing reporting date produces 'date unavailable', never '2026-08-31'."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings

    unverified_fund = {
        "scheme": "Some Random Fund - Direct Plan - Growth",
        "category": "Equity",
        "category_verified": True,
        "plan_type": "Direct",
        "current_value": 50000.0,
        "folio_no": "FOLIO-X",
        "source": "existing",
        "validation": "valid",
    }

    holdings = convert_cas_funds_to_holdings([unverified_fund])
    assert len(holdings) == 1
    h = holdings[0]
    assert h.lookthrough_status == "INDETERMINATE"
    assert "2026-08-31" not in h.lookthrough_reason
    assert h.lookthrough_effective_date is None


def test_dummy_unmeasured_schemes_in_master_fail_closed_to_indeterminate():
    """Provisional Dataset Governance: the 9 unmeasured schemes in master have no fake evidence and fail closed."""
    from services.fiduciary_engine import convert_cas_funds_to_holdings
    from services.cas_parser import resolve_authoritative_scheme

    # Verify in scheme master directly
    master_entry = resolve_authoritative_scheme("BANDHAN Nifty 50 Index Fund - Direct Plan - Growth")
    assert master_entry is not None
    assert master_entry.get("exposure_evidence") is None
    assert master_entry.get("eq") is None
    assert master_entry.get("debt") is None

    # Verify when held in client portfolio
    holding_fund = {
        "scheme": "BANDHAN Nifty 50 Index Fund - Direct Plan - Growth",
        "category": "Large Cap",
        "category_verified": True,
        "plan_type": "Direct",
        "current_value": 200000.0,
        "folio_no": "BND-01",
        "source": "existing",
        "validation": "valid",
    }

    holdings = convert_cas_funds_to_holdings([holding_fund])
    assert len(holdings) == 1
    h = holdings[0]
    assert h.lookthrough_status == "INDETERMINATE"
    assert h.equity_pct == 0.0
    assert h.debt_pct == 0.0


def test_provenance_tier_distinguishes_integrity_from_publisher_authentication():
    """Source Authenticity: validate_exposure_evidence fails closed when publisher authentication is required."""
    from services.cas_parser import validate_exposure_evidence, resolve_authoritative_scheme

    hdfc_top100 = resolve_authoritative_scheme("HDFC Top 100 Fund - Direct Plan - Growth")
    assert hdfc_top100 is not None
    ev = hdfc_top100["exposure_evidence"]
    assert ev is not None

    # When require_publisher_authentication=False: integrity and scheme verification pass on PROVISIONAL_INTERNAL
    ok_prov, msg_prov = validate_exposure_evidence(ev, hdfc_top100["sid"], require_publisher_authentication=False)
    assert ok_prov is True
    assert msg_prov == "OK"

    # When require_publisher_authentication=True: fails closed because dataset is provisional
    ok_auth, msg_auth = validate_exposure_evidence(ev, hdfc_top100["sid"], require_publisher_authentication=True)
    assert ok_auth is False
    assert "External publisher authentication not established" in msg_auth


def test_evidence_validation_fails_closed_when_disclosure_content_percentage_mismatched():
    """Adversarial Tampering: modifying debt_pct in evidence vs verified source document fails closed."""
    from services.cas_parser import validate_exposure_evidence, resolve_authoritative_scheme
    import hashlib, json

    hdfc_top100 = resolve_authoritative_scheme("HDFC Top 100 Fund - Direct Plan - Growth")
    real_ev = dict(hdfc_top100["exposure_evidence"])

    # Adversary alters debt from 4.3 to 9.9 and adjusts equity to 90.1 so sum=100.0,
    # and creates valid canonical hash for their altered record
    tampered_obj = dict(real_ev, debt_pct=9.9, equity_pct=90.1)
    tampered_canonical = {
        "debt_pct": 9.9,
        "equity_pct": 90.1,
        "is_verified": True,
        "reporting_period": tampered_obj["reporting_period"],
        "retrieval_date": tampered_obj["retrieval_date"],
        "scheme_code": tampered_obj["scheme_code"],
        "source_document": tampered_obj["source_document"],
        "source_name": tampered_obj["source_name"],
    }
    tampered_hash = hashlib.sha256(json.dumps(tampered_canonical, sort_keys=True).encode("utf-8")).hexdigest()
    tampered_obj["evidence_hash"] = tampered_hash

    # Cross-document reconciliation must detect that source document has 4.3, not 9.9
    is_valid, msg = validate_exposure_evidence(tampered_obj, hdfc_top100["sid"])
    assert is_valid is False
    assert "Evidence debt_pct 9.9 != source document debt_pct 4.3" in msg


def test_evidence_validation_fails_closed_when_file_bytes_modified(tmp_path):
    """Integrity Verification: modifying a single byte in source document invalidates byte hash."""
    from services.cas_parser import validate_exposure_evidence
    from pathlib import Path
    import hashlib

    # Create a legitimate document
    original_path = Path("data/policy/sharpely_monthly_disclosure_2026_08.json")
    original_bytes = original_path.read_bytes()

    tampered_doc = tmp_path / "sharpely_monthly_disclosure_2026_08.json"
    tampered_doc.write_bytes(original_bytes + b" ")  # Tamper by appending whitespace

    original_file_hash = hashlib.sha256(original_bytes).hexdigest()

    ev = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": str(tampered_doc),
        "scheme_code": 10101,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "debt_pct": 4.3,
        "equity_pct": 95.7,
        "evidence_hash": original_file_hash,  # Hash of original file, but file on disk has changed!
        "is_verified": True,
    }

    is_valid, msg = validate_exposure_evidence(ev, 10101)
    assert is_valid is False
    assert "Evidence hash mismatch" in msg


def test_evidence_policy_distinguishes_strict_advice_from_research_provisional():
    """P0-1: Policy governance enforces AUTHENTICATED_EXTERNAL for advice and flags provisional lookthrough."""
    from services.cas_parser import (
        validate_exposure_evidence,
        resolve_authoritative_scheme,
        ExposureEvidencePolicy,
    )
    from services.fiduciary_engine import convert_cas_funds_to_holdings, evaluate_portfolio_saa_audit

    entry = resolve_authoritative_scheme("HDFC Top 100 Fund - Direct Plan - Growth")
    assert entry is not None
    ev = entry["exposure_evidence"]
    assert ev is not None

    # Under STRICT_ADVICE policy: provisional internal disclosures fail closed
    ok_advice, msg_advice = validate_exposure_evidence(
        ev,
        entry["sid"],
        evidence_policy=ExposureEvidencePolicy.STRICT_ADVICE,
    )
    assert ok_advice is False
    assert "External publisher authentication not established" in msg_advice

    # Under RESEARCH_PROVISIONAL policy: provisional internal disclosures pass integrity check
    ok_res, msg_res = validate_exposure_evidence(
        ev,
        entry["sid"],
        evidence_policy=ExposureEvidencePolicy.RESEARCH_PROVISIONAL,
    )
    assert ok_res is True

    # Holdings conversion under STRICT_ADVICE fails closed to INDETERMINATE
    fund_record = {
        "scheme": "HDFC Top 100 Fund - Direct Plan - Growth",
        "scheme_code": entry["sid"],
        "category": "Large Cap",
        "current_value": 500000.0,
        "source": "existing",
        "validation": "valid",
        "portfolio_exposure_verified": True,
        "verified_equity_pct": ev["equity_pct"],
        "verified_debt_pct": ev["debt_pct"],
        "exposure_evidence": ev,
    }
    holdings_advice = convert_cas_funds_to_holdings(
        [fund_record],
        evidence_policy=ExposureEvidencePolicy.STRICT_ADVICE,
    )
    assert holdings_advice[0].lookthrough_status == "INDETERMINATE"
    assert "rejected for strict fiduciary advice" in holdings_advice[0].lookthrough_reason

    # SAA audit under STRICT_ADVICE fails closed to INDETERMINATE
    audit_advice = evaluate_portfolio_saa_audit(
        [fund_record],
        evidence_policy=ExposureEvidencePolicy.STRICT_ADVICE,
    )
    assert audit_advice["status"] == "INDETERMINATE"

    # Holdings conversion under RESEARCH_PROVISIONAL tags as PROVISIONAL_LOOKTHROUGH (never VERIFIED)
    holdings_res = convert_cas_funds_to_holdings(
        [fund_record],
        evidence_policy=ExposureEvidencePolicy.RESEARCH_PROVISIONAL,
    )
    assert holdings_res[0].lookthrough_status == "PROVISIONAL_LOOKTHROUGH"
    assert "Provisional factsheet disclosure" in holdings_res[0].lookthrough_reason

    # SAA audit under RESEARCH_PROVISIONAL returns ANALYZED with is_provisional=True
    audit_res = evaluate_portfolio_saa_audit(
        [fund_record],
        evidence_policy=ExposureEvidencePolicy.RESEARCH_PROVISIONAL,
    )
    assert audit_res["status"] == "ANALYZED"
    assert audit_res["is_provisional"] is True
    assert audit_res["evidence_tier"] == "PROVISIONAL_INTERNAL"


def test_disclosure_identity_checks_are_strictly_mandatory(tmp_path):
    """P0-2: Mandatory presence and exact match of scheme_code and reporting_period in disclosure document."""
    from services.cas_parser import validate_exposure_evidence

    # Base valid doc
    valid_doc = {
        "_metadata": {
            "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
            "source_authenticity": "AUTHENTICATED_EXTERNAL",
            "publisher_authenticated": True,
        },
        "disclosures": {
            "99901": {
                "scheme_code": 99901,
                "scheme_name": "Test Identity Scheme",
                "reporting_period": "2026-08-31",
                "retrieval_date": "2026-11-07",
                "equity_pct": 80.0,
                "debt_pct": 20.0,
                "cash_pct": 0.0,
                "gold_pct": 0.0,
                "other_pct": 0.0,
                "is_verified": True,
            }
        }
    }

    # Case A: Missing scheme_code in disclosure entry fails closed
    doc_missing_code = json.loads(json.dumps(valid_doc))
    del doc_missing_code["disclosures"]["99901"]["scheme_code"]
    path_a = tmp_path / "missing_code.json"
    path_a.write_text(json.dumps(doc_missing_code), encoding="utf-8")
    ev_a = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": str(path_a),
        "scheme_code": 99901,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "equity_pct": 80.0,
        "debt_pct": 20.0,
        "evidence_hash": hashlib.sha256(path_a.read_bytes()).hexdigest(),
        "is_verified": True,
    }
    ok_a, msg_a = validate_exposure_evidence(ev_a, 99901)
    assert ok_a is False
    assert "missing mandatory scheme_code" in msg_a

    # Case B: Missing reporting_period in disclosure entry fails closed
    doc_missing_period = json.loads(json.dumps(valid_doc))
    del doc_missing_period["disclosures"]["99901"]["reporting_period"]
    path_b = tmp_path / "missing_period.json"
    path_b.write_text(json.dumps(doc_missing_period), encoding="utf-8")
    ev_b = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": str(path_b),
        "scheme_code": 99901,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "equity_pct": 80.0,
        "debt_pct": 20.0,
        "evidence_hash": hashlib.sha256(path_b.read_bytes()).hexdigest(),
        "is_verified": True,
    }
    ok_b, msg_b = validate_exposure_evidence(ev_b, 99901)
    assert ok_b is False
    assert "missing mandatory reporting_period" in msg_b


def test_missing_asset_class_measurements_fail_closed_never_default_zero(tmp_path):
    """P0-3: Every asset class (equity, debt, cash, gold, other) must explicitly exist; missing is never assumed zero."""
    from services.cas_parser import validate_exposure_evidence

    base_doc = {
        "_metadata": {
            "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
            "source_authenticity": "AUTHENTICATED_EXTERNAL",
            "publisher_authenticated": True,
        },
        "disclosures": {
            "88801": {
                "scheme_code": 88801,
                "scheme_name": "Test Incomplete Breakdown Scheme",
                "reporting_period": "2026-08-31",
                "retrieval_date": "2026-11-07",
                "equity_pct": 75.0,
                "debt_pct": 25.0,
                # cash_pct, gold_pct, other_pct omitted!
                "is_verified": True,
            }
        }
    }

    path = tmp_path / "omitted_cash.json"
    path.write_text(json.dumps(base_doc), encoding="utf-8")
    ev = {
        "source_name": "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
        "source_document": str(path),
        "scheme_code": 88801,
        "reporting_period": "2026-08-31",
        "retrieval_date": "2026-11-07",
        "equity_pct": 75.0,
        "debt_pct": 25.0,
        "evidence_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "is_verified": True,
    }

    ok, msg = validate_exposure_evidence(ev, 88801)
    assert ok is False
    assert "missing mandatory asset-class measurement" in msg


def test_audit_cas_document_integrity_binds_complete_evidence():
    """P0-4: Canonical audit hash binds all asset classes, scheme codes, and temporal metadata."""
    from services.cas_parser import audit_cas_document_integrity

    fund_a = {
        "scheme": "Scheme A Direct",
        "scheme_code": 111,
        "current_value": 100000.0,
        "nav": 50.0,
        "exposure_evidence": {
            "scheme_code": 111,
            "equity_pct": 80.0,
            "debt_pct": 20.0,
            "cash_pct": 0.0,
            "gold_pct": 0.0,
            "other_pct": 0.0,
            "reporting_period": "2026-08-31",
            "source_authenticity": "PROVISIONAL_INTERNAL",
        }
    }
    fund_b = {
        "scheme": "Scheme A Direct",
        "scheme_code": 111,
        "current_value": 100000.0,
        "nav": 50.0,
        "exposure_evidence": {
            "scheme_code": 111,
            "equity_pct": 75.0,  # Changed asset class exposure!
            "debt_pct": 20.0,
            "cash_pct": 5.0,   # Cash changed!
            "gold_pct": 0.0,
            "other_pct": 0.0,
            "reporting_period": "2026-08-31",
            "source_authenticity": "PROVISIONAL_INTERNAL",
        }
    }

    res_a = audit_cas_document_integrity([fund_a])
    res_b = audit_cas_document_integrity([fund_b])

    assert res_a["status"] == "VERIFIED"
    assert res_b["status"] == "VERIFIED"
    assert res_a["audit_hash"] != res_b["audit_hash"], "Audit hash must change when asset-class exposure changes!"


def test_classifier_never_infers_debt_from_market_cap_residual(monkeypatch):
    """P1-5: Classifier online factsheet resolution preserves residual as unclassified other, never debt."""
    from services import ai_fund_classifier
    import io

    ddg_html = b'<a class="result-link" href="https://www.etmoney.com/mutual-funds/test-fund/123/portfolio-details">link</a>'
    et_html = b'''
    <div class="product-heading">Large Cap</div>
    <p class="product-amount">60.0%</p>
    <div class="product-heading">Mid Cap</div>
    <p class="product-amount">20.0%</p>
    <div class="product-heading">Small Cap</div>
    <p class="product-amount">10.0%</p>
    '''

    class MockResponse(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=None):
        full_url = req.full_url if hasattr(req, "full_url") else str(req)
        if "duckduckgo" in full_url:
            return MockResponse(ddg_html)
        return MockResponse(et_html)

    monkeypatch.setattr(ai_fund_classifier.urllib.request, "urlopen", mock_urlopen)

    res = ai_fund_classifier.lookup_fund_segment_allocation_online("Aditya Birla Sun Life Frontline Equity Fund Direct-Growth")
    assert res is not None
    assert res["eq"] == 90.0
    assert res["debt"] == 0.0, "Market cap residual MUST NOT be inferred as debt!"
    assert res["other"] == 10.0, "Residual must be safely recorded as unclassified other!"


def test_stability_buffer_lookup_exception_fails_closed_explicitly(monkeypatch):
    """P1-6: Exceptions during stability buffer scheme lookup fail closed explicitly without silent suppression."""
    from services import fiduciary_engine
    import services.cas_parser

    # Force resolve_authoritative_scheme to raise an unexpected runtime error
    def broken_lookup(name):
        raise RuntimeError("Simulated database failure during scheme resolution")

    monkeypatch.setattr(services.cas_parser, "resolve_authoritative_scheme", broken_lookup)

    holdings = [
        {
            "scheme": "Arbitrary Hybrid Fund Direct",
            "category": "Aggressive Hybrid",
            "current_value": 200000.0,
            "source": "existing",
            "validation": "valid",
            "portfolio_exposure_verified": False,
        }
    ]

    blueprint = fiduciary_engine.generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=holdings,
        target_saa={"large_cap": 50.0, "mid_small": 25.0, "flexi": 0.0, "debt": 25.0},
    )

    # Must withhold stability buffer override and record explicit indeterminate reason
    assert blueprint["stability_override_applied"] is False
    assert blueprint["stability_override_status"] == "INDETERMINATE"
    assert "simulated database failure" in blueprint["stability_override_reason"].lower()




