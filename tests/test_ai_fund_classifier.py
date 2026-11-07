"""Tests for services/ai_fund_classifier.py — AI Fund-Wise Look-Through Engine.

Verifies that mutual fund schemes resolve to their authentic AMC factsheet disclosures
and SEBI regulatory mandates without crude heuristic substring assumptions.
"""
from __future__ import annotations

import pytest
from services.ai_fund_classifier import classify_fund_with_ai, enrich_funds_with_ai, extract_canonical_scheme_name


def test_hdfc_balanced_advantage_lookthrough():
    """HDFC BAF unbundles to ~73.3% equity, 23.86% debt, and 54.71% large cap."""
    res = classify_fund_with_ai("HDFC Balanced Advantage Fund - Direct Plan - Growth Option")
    assert res["category"] == "Hybrid"
    assert "Balanced Advantage" in res["scheme_type"] or "BAF" in res["scheme_type"]
    assert res["eq"] == 73.30
    assert res["debt"] == 23.86
    assert res["lc"] == 54.71
    assert res["mc"] == 9.59
    assert res["sc"] == 9.00
    assert "NIFTY 50 Hybrid" in res["benchmark"]


def test_hdfc_defence_lookthrough():
    """HDFC Defence resolves to Sectoral/Thematic Equity with verified market cap breakdown."""
    res = classify_fund_with_ai("HDFC Defence Fund Regular Growth")
    assert res["category"] == "Equity"
    assert "Sectoral" in res["scheme_type"] or "Thematic" in res["scheme_type"]
    assert res["eq"] == 98.11
    assert res["debt"] == 0.0
    assert res["lc"] == 43.86
    assert res["mc"] == 25.31
    assert res["sc"] == 29.04
    assert "Defence" in res["benchmark"]


def test_parag_parikh_flexi_cap_lookthrough():
    """PPFAS Flexi Cap captures direct foreign equity (~14.5%) and ~6.26% debt/cash."""
    res = classify_fund_with_ai("Parag Parikh Flexi Cap Fund - Regular Plan Growth")
    assert res["category"] == "Equity"
    assert res["scheme_type"] == "Flexi Cap"
    assert res["eq"] == 82.24
    assert res["debt"] == 6.26
    assert res["intl"] == 14.50
    assert res["lc"] == 74.62
    assert res["benchmark"] == "Nifty 500 TRI"


def test_canara_robeco_multi_asset_lookthrough():
    """Canara Robeco Multi Asset captures 22% debt and 9.5% domestic gold."""
    res = classify_fund_with_ai("Canara Robeco Multi Asset Allocation Fund Regular Growth")
    assert res["category"] == "Hybrid"
    assert "Multi Asset" in res["scheme_type"]
    assert res["eq"] == 68.50
    assert res["debt"] == 22.00
    assert res["gold"] == 9.50
    assert "Multi-Asset" in res["benchmark"]


def test_sbi_energy_opportunities_lookthrough():
    """SBI Energy Opportunities resolves to authentic energy theme and market cap split."""
    res = classify_fund_with_ai("SBI Energy Opportunities Fund- Regular Growth")
    assert res["category"] == "Equity"
    assert res["eq"] == 97.43
    assert res["debt"] == 0.06
    assert res["lc"] == 43.06
    assert res["sc"] == 33.32
    assert "Energy" in res["benchmark"]


def test_enrich_funds_with_ai():
    """enrich_funds_with_ai enhances raw CAS parsed items with look-through intelligence."""
    raw_funds = [
        {"scheme": "HDFC Balanced Advantage Fund - Direct Plan - Growth Option", "current_value": 475751.04},
        {"scheme": "Parag Parikh Flexi Cap Fund - Regular Plan Growth", "current_value": 534144.65},
        {"scheme": "Canara Robeco Multi Asset Allocation Fund Regular Growth", "current_value": 107594.62},
    ]
    enriched = enrich_funds_with_ai(raw_funds)
    assert len(enriched) == 3

    baf = enriched[0]
    assert baf["category"] == "Hybrid"
    assert baf["eq"] == 73.30
    assert baf["debt"] == 23.86
    assert baf["classification_source"] == "AMC Factsheet Look-Through"

    ppfas = enriched[1]
    assert ppfas["category"] == "Equity"
    assert ppfas["intl"] == 14.50
    assert ppfas["debt"] == 6.26

    crma = enriched[2]
    assert crma["category"] == "Hybrid"
    assert crma["gold"] == 9.50
    assert crma["debt"] == 22.00



def test_extract_canonical_scheme_name_and_dual_plan_detection():
    """Verify underlying scheme name normalizes across Direct and Regular plans."""
    d = "HDFC Flexi Cap Fund - Direct Plan - Growth Option"
    r = "HDFC Flexi Cap Fund - Regular Plan - Growth"
    assert extract_canonical_scheme_name(d) == extract_canonical_scheme_name(r) == "Hdfc Flexi Cap Fund"
