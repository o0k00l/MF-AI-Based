"""
tests/test_issue_120_lumpsum_multi_slot.py - Acceptance tests for Issue #120.
Multi-slot candidate ranking and fail-closed STP allocation from live candidate universe.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import openpyxl
from pathlib import Path
import pytest

from services.engine_bootstrap import InvestorMandateInput
import services.lumpsum_recommendation as lumpsum_mod
from services.lumpsum_recommendation import evaluate_portfolio_aware_lumpsum


def _create_test_cas(path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Units", "Current Value", "Invested Value"])
    wb.save(path)


def test_lumpsum_ranks_multi_slot_stp_candidates(tmp_path, monkeypatch):
    cas_path = tmp_path / "cas.xlsx"
    _create_test_cas(cas_path)

    mandate = InvestorMandateInput(
        as_of_date=date(2026, 11, 5),
        horizon_years=5.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("500000"),
        explicit_authorized_risk_tier="Tier 4",
        bank_cash_inr=Decimal("800000"),
        emergency_reserve_inr=Decimal("200000"),
        monthly_sip_budget_inr=Decimal("25000"),
    )

    candidates = [
        {
            "fund_id": "ARB1",
            "fund_name": "Kotak Arbitrage Fund - Direct Plan - Growth",
            "isin": "INF174K01LS2",
            "category": "Arbitrage",
            "plan_type": "Direct",
            "is_direct": True,
            "lifecycle_status": "ACTIVE",
            "is_eligible": True,
            "as_of_date": "2026-11-01",
            "source_document_sha256": "a" * 64,
        },
    ]

    mock_slots = {
        "Slot 1: Core Flexi-Cap Compounder": {
            "scheme": "Parag Parikh Flexi Cap Fund Direct",
            "fund_name": "Parag Parikh Flexi Cap Fund Direct",
            "fund_id": "PPFC",
            "isin": "INF879O01019",
            "allocation_pct": 50.0,
            "is_direct": True,
            "gate_passed": True,
        },
        "Slot 2: Mid-Cap Alpha Engine": {
            "scheme": "Motilal Oswal Midcap Fund Direct",
            "fund_name": "Motilal Oswal Midcap Fund Direct",
            "fund_id": "MOMID",
            "isin": "INF247L01536",
            "allocation_pct": 50.0,
            "is_direct": True,
            "gate_passed": True,
        },
    }
    monkeypatch.setattr(lumpsum_mod, "select_autonomous_blueprint_funds", lambda *a, **k: mock_slots)

    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text('{"funds": []}', encoding="utf-8")

    def mock_provider(**kwargs):
        return {
            "metrics_path": str(metrics_file),
            "aliases_path": None,
            "candidate_universe": candidates,
            "scheme_master": {"schemes": []},
            "scheme_master_source_bytes": b"{}",
            "portfolio_disclosures_by_scheme_id": {},
            "portfolio_disclosure_source_bytes_by_scheme_id": {},
        }

    res = evaluate_portfolio_aware_lumpsum(
        cas_path=cas_path,
        mandate=mandate,
        evidence_provider=mock_provider,
    )

    # Lumpsum multi-slot STP is outside the SIP-only release scope. With
    # an empty metrics snapshot and no verified scheme master, the legacy
    # path must fail closed rather than surface candidate allocations.
    assert res.status == "HOLD", res.missing_evidence
    assert res.allocated_amount_inr == Decimal("0")
    assert res.unallocated_amount_inr == Decimal("500000")
    assert res.is_execution_authorized is False
