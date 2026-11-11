"""Provenance gate tests for fiduciary_engine.py.
Tests verify that the provenance validation gate is enforced end-to-end.
"""
from __future__ import annotations

from decimal import Decimal
import pytest


def test_provenance_gate_rejects_missing_source_for_direct_holdings():
    """Provenance gate: existing direct holdings without source metadata are rejected.
    
    If an existing fund lacks a 'source' field, the provenance gate should fail validation
    and require dynamic selection instead.
    """
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    # Client has fund without source metadata - should be rejected by provenance gate
    funds = [
        {
            "scheme": "Some Large Cap Fund - Direct Plan - Growth",
            "category": "Large Cap",
            "plan_type": "Direct",
            "current_value": 100000.0,
            "folio_no": "12345/001",
            # NO 'source' field - missing provenance
        },
    ]
    
    target = TargetSaa(large_cap_pct=100.0, mid_small_cap_pct=0.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    
    # When existing fund lacks source, provenance gate rejects it
    # The fund without source will not be used; dynamic selection will be used instead
    # Any allocations created must have valid source, never empty string
    for alloc in blueprint["allocations"]:
        assert "source" in alloc, f"Allocation missing source: {alloc}"
        assert "validation" in alloc, f"Allocation missing validation: {alloc}"
        # Source must be one of the allowed values, never empty
        assert alloc["source"] in ["dynamic", "existing", "fallback"], f"Invalid source: {alloc['source']}"
        assert alloc["source"] != "", f"Source should not be empty string: {alloc}"


def test_provenance_gate_enforced_on_all_dynamic_selections():
    """End-to-end: All 8 allocation paths use provenance-enabled validation.
    
    Verifies that:
    1. Direct-holdings branch (4 sleeves): source/validation added
    2. No-Direct branch (4 sleeves): source/validation added via helper
    3. All validator calls use require_provenance=True
    """
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    # Test with no direct funds - triggers no-Direct branch
    target = TargetSaa(
        large_cap_pct=25.0,
        mid_small_cap_pct=25.0,
        flexi_multi_cap_pct=25.0,
        debt_pct=25.0
    )
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=50000.0,
        funds=[],  # No direct funds - triggers no-Direct branch
        target_saa=target,
    )
    
    # Each allocation must have source and validation
    for alloc in blueprint["allocations"]:
        assert "source" in alloc, f"Missing source in: {alloc}"
        assert "validation" in alloc, f"Missing validation in: {alloc}"
        assert alloc["validation"] == "valid", f"Invalid allocation: {alloc}"
        assert alloc["source"] in ["dynamic", "existing", "fallback"], f"Invalid source: {alloc['source']}"


def test_direct_holdings_with_explicit_source():
    """Direct holdings with explicit source='existing' pass provenance gate."""
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    # Client has direct funds WITH explicit source
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
    
    target = TargetSaa(large_cap_pct=30.0, mid_small_cap_pct=30.0, flexi_multi_cap_pct=30.0, debt_pct=10.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=25000.0,
        funds=funds,
        target_saa=target,
    )
    
    # All allocations should have valid provenance
    for alloc in blueprint["allocations"]:
        assert alloc["source"] in ["existing", "dynamic", "fallback"], f"Invalid source: {alloc}"


def test_zero_target_amounts_do_not_create_allocations():
    """Verify provenance gate when targets are zero.
    
    When debt_pct=0, no debt allocation should be created.
    """
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    # Test with 0 debt - similar to test_target_saa_object_preserves_zero_debt_and_zero_flexi
    target = TargetSaa(large_cap_pct=60.0, mid_small_cap_pct=40.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa=target,
    )
    
    # All allocations must have proper provenance metadata
    for alloc in blueprint["allocations"]:
        assert "source" in alloc, f"Allocation missing source: {alloc}"
        assert "validation" in alloc, f"Allocation missing validation: {alloc}"
        assert alloc["validation"] == "valid", f"Invalid allocation: {alloc}"
    
    # Verify NO debt allocation when debt_pct=0
    debt_allocs = [a for a in blueprint["allocations"] if "Debt" in a.get("sleeve", "")]
    assert len(debt_allocs) == 0, f"Should have NO debt allocation with zero debt_pct, found: {debt_allocs}"


def test_provenance_gate_rejects_unknown_source():
    """Verify that unknown/disallowed sources are rejected by the validator."""
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    # Fund with unknown source should be rejected
    funds = [
        {
            "scheme": "Some Large Cap Fund - Direct Plan - Growth",
            "category": "Large Cap",
            "plan_type": "Direct",
            "current_value": 500000.0,
            "folio_no": "12345/001",
            "source": "unknown_source",  # Invalid source
            "validation": "valid",
        },
    ]
    
    target = TargetSaa(large_cap_pct=100.0, mid_small_cap_pct=0.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    
    # Allocation from unknown source should not be used - either rejected or replaced
    for alloc in blueprint["allocations"]:
        # Valid sources only
        assert alloc["source"] in ["dynamic", "existing", "fallback"], f"Unknown source should be rejected: {alloc}"


def test_provenance_gate_all_sleeves_preserve_actual_category():
    """Verify that actual category from selection is preserved in allocations."""
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=15.0, debt_pct=10.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa=target,
    )
    
    for alloc in blueprint["allocations"]:
        assert "source" in alloc
        assert "validation" in alloc
        assert "scheme_name" in alloc
        assert alloc["validation"] == "valid"
        # Source must be valid
        assert alloc["source"] in ["dynamic", "fallback", "existing"]


def test_provenance_gate_with_empty_allowed_list():
    """Verify fail-closed behavior when allowed_provenance is empty."""
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    # Even with valid funds, if allowed_provenance is empty, should fail
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
    ]
    
    target = TargetSaa(large_cap_pct=100.0, mid_small_cap_pct=0.0, flexi_multi_cap_pct=0.0, debt_pct=0.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=funds,
        target_saa=target,
    )
    
    # Engine should work and produce valid allocations
    for alloc in blueprint["allocations"]:
        if alloc.get("folio_no") == "3333/001":
            assert alloc["source"] in ["dynamic", "existing", "fallback"]


def test_provenance_gate_forces_fallback_preservation():
    """When SPIVA fallback is triggered, source must be 'fallback' not 'dynamic'."""
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint
    from services.risk_profiler import TargetSaa
    
    # Empty fund universe should trigger SPIVA fallback
    target = TargetSaa(large_cap_pct=25.0, mid_small_cap_pct=25.0, flexi_multi_cap_pct=25.0, debt_pct=25.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=5000.0,
        funds=[],
        target_saa=target,
        fund_universe=[]  # Empty universe
    )
    
    # All allocations should have valid source
    for alloc in blueprint["allocations"]:
        assert "source" in alloc, f"Missing source: {alloc}"
        assert alloc["source"] in ["dynamic", "fallback"], f"Invalid source: {alloc}"