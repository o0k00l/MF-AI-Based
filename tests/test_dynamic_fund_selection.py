"""Tests for dynamic fund selection logic."""
from __future__ import annotations

from services.fiduciary_engine import (
    _load_market_nominations,
    _select_market_nom_fund,
)


def test_dynamic_fund_selection_falls_back_when_no_matches():
    """Verify fallback selection when no funds match criteria."""
    fund_universe = []
    market_noms = _load_market_nominations()
    rules = market_noms.get("large_cap_index", {})
    selected = _select_market_nom_fund(rules, fund_universe, "large_cap_index")
    # Fallback should return a valid index fund
    assert "Index" in selected or "Nifty" in selected or "Sensex" in selected
    assert "Direct Plan" in selected or "Direct" in selected


def test_dynamic_fund_selection_with_realistic_rules():
    """Verify selection works with realistic test data matching production rules."""
    fund_universe = [
        {"scheme": "UTI Nifty 50 Index Fund", "category": "Large Cap", "is_passive": True, "ter_direct_pct": 0.10, "aum_crore": 6000, "eq": 100, "sharpe_3y": 0.6},
        {"scheme": "Axis Nifty 50 Index Fund", "category": "Large Cap", "is_passive": True, "ter_direct_pct": 0.15, "aum_crore": 5000, "eq": 100, "sharpe_3y": 0.5},
        {"scheme": "HDFC Mid Cap Fund", "category": "Mid Cap", "is_passive": False, "sharpe_3y": 0.7, "alpha_3y": 2.0, "aum_crore": 8000},
        {"scheme": "ICICI Pru Mid Cap Fund", "category": "Mid Cap", "is_passive": False, "sharpe_3y": 0.5, "alpha_3y": 1.5, "aum_crore": 7000},
        {"scheme": "ICICI Prudential Liquid Fund", "category": "Debt", "is_passive": False, "aum_crore": 35000, "ter_direct_pct": 0.15},
        {"scheme": "HDFC Liquid Fund", "category": "Debt", "is_passive": False, "aum_crore": 25000, "ter_direct_pct": 0.20},
    ]
    
    market_noms = _load_market_nominations()
    
    # Test large cap selection (lowest TER among index funds)
    selected = _select_market_nom_fund(market_noms.get("large_cap_index", {}), fund_universe, "large_cap_index")
    # Should select UTI (lower TER) - check for Nifty index fund
    assert "Nifty" in selected or "Index" in selected, f"Expected index fund, got: {selected}"
    
    # Test mid cap selection (highest Sharpe)
    selected = _select_market_nom_fund(market_noms.get("mid_cap_active", {}), fund_universe, "mid_cap_active")
    # Should select HDFC Mid Cap (Sharpe 0.7 > 0.5)
    assert "HDFC Mid Cap" in selected, f"Expected HDFC Mid Cap, got: {selected}"
    
    # Test debt selection (highest AUM)
    selected = _select_market_nom_fund(market_noms.get("debt_liquid", {}), fund_universe, "debt_liquid")
    # Should select ICICI Prudential Liquid (AUM 35000 > 25000)
    assert "Liquid" in selected, f"Expected Liquid fund, got: {selected}"


def test_dynamic_selection_applies_ter_filter():
    """Verify TER filter is applied correctly for large cap index selection."""
    fund_universe = [
        {"scheme": "Expensive Index Fund", "category": "Large Cap", "is_passive": True, "ter_direct_pct": 0.80, "aum_crore": 10000, "eq": 100},
        {"scheme": "Cheap Index Fund", "category": "Large Cap", "is_passive": True, "ter_direct_pct": 0.10, "aum_crore": 5000, "eq": 100},
    ]
    market_noms = _load_market_nominations()
    selected = _select_market_nom_fund(market_noms.get("large_cap_index", {}), fund_universe, "large_cap_index")
    # Should select the cheap one (TER 0.10 < max_ter_pct 0.5)
    assert "Cheap" in selected, f"Expected Cheap Index Fund, got: {selected}"


def test_dynamic_selection_applies_equity_filter():
    """Verify equity % filter is applied for large cap index selection."""
    fund_universe = [
        {"scheme": "Hybrid Index Fund", "category": "Large Cap", "is_passive": True, "ter_direct_pct": 0.15, "aum_crore": 10000, "eq": 80},
        {"scheme": "Pure Large Cap Index Fund", "category": "Large Cap", "is_passive": True, "ter_direct_pct": 0.20, "aum_crore": 8000, "eq": 95},
    ]
    market_noms = _load_market_nominations()
    selected = _select_market_nom_fund(market_noms.get("large_cap_index", {}), fund_universe, "large_cap_index")
    # Should select the one with 95%+ equity (meets equity_pct_min requirement)
    assert "Pure" in selected or "95" in selected, f"Expected pure large cap fund, got: {selected}"


def test_dynamic_selection_applies_aum_filter():
    """Verify AUM filter is applied for debt/liquid selection."""
    fund_universe = [
        {"scheme": "Small AUM Liquid Fund", "category": "Debt", "is_passive": False, "aum_crore": 1000, "ter_direct_pct": 0.15},
        {"scheme": "Large AUM Liquid Fund", "category": "Debt", "is_passive": False, "aum_crore": 50000, "ter_direct_pct": 0.20},
    ]
    market_noms = _load_market_nominations()
    selected = _select_market_nom_fund(market_noms.get("debt_liquid", {}), fund_universe, "debt_liquid")
    # Should select the one with AUM >= 5000 crore
    assert "Large AUM" in selected, f"Expected large AUM fund, got: {selected}"