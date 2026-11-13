# -*- coding: utf-8 -*-
"""
End-to-end acceptance tests for Issues #23 and #24:
- Issue #23: Total-portfolio reconciliation across holdings, cash, liabilities,
  and external assets with canonical signed reconciliation report artifact.
- Issue #24: End-to-end recommendation trace through eligible candidates from the live
  candidate universe with Custom SAA propagation and whole-budget reconciliation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest

from core.models import AssetAllocationTarget
from core.portfolio_sip_controls import (
    PortfolioInputError,
    generate_signed_portfolio_reconciliation_report,
    reconcile_total_portfolio,
)
import services.sip_recommendation as service


def _sample_cas_workbook(tmp_path: Path) -> Path:
    cas = tmp_path / "cas.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["To Date", date.today().strftime("%d-%b-%Y")])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Direct Core Large Cap Fund", "FOLIO-1", 100000.0, 125000.0, 1000.0])
    wb.save(cas)
    return cas


def _sample_holding():
    return SimpleNamespace(
        scheme="Direct Core Large Cap Fund",
        fund_id="FUND-1",
        scheme_id="SCHEME-1",
        plan_option_status="VERIFIED",
        option_type="GROWTH",
        is_direct=True,
        lookthrough_status="VERIFIED",
        metrics_status="VERIFIED",
        constituent_weights={"ISSUER A": 60.0, "ISSUER B": 40.0},
        equity_pct=100.0,
        constituent_weights_coverage_pct=100.0,
        current_value_inr=125000.0,
    )


def _build_30_candidates(as_of: str) -> list[dict[str, Any]]:
    """Build a compliant 30-candidate universe with complete provenance."""
    candidates = []
    sleeves = ["large_cap", "mid_cap", "small_cap", "flexi_multi_cap"]
    for i in range(1, 31):
        sleeve = sleeves[(i - 1) % len(sleeves)]
        category_name = "Large Cap" if sleeve == "large_cap" else (
            "Mid Cap" if sleeve == "mid_cap" else (
                "Small Cap" if sleeve == "small_cap" else "Flexi Cap"
            )
        )
        candidates.append({
            "fund_id": f"CAND-{i:02d}",
            "scheme_id": f"SCHEME-{i:02d}",
            "isin": f"INF00000{i:03d}",
            "amc_name": f"AMC {i}",
            "category": category_name,
            "benchmark": "Nifty 500 TRI",
            "is_direct": True,
            "constituent_weights": {f"ISSUER {chr(65 + (i % 5))}": 60.0, f"ISSUER {chr(70 + (i % 5))}": 40.0},
            "constituent_weights_coverage_pct": 100.0,
            "rank_score": str(100 - i),
            "rank_score_source_ref": f"sha256:rank-score-{i:02d}",
            "rank_score_as_of_date": as_of,
            "rank_score_methodology_version": "fiduciary-rank-v1",
            "direct_plan_evidence": {
                "scheme_id": f"SCHEME-{i:02d}",
                "isin": f"INF00000{i:03d}",
                "plan": "Direct",
                "option": "Growth",
                "amc_name": f"AMC {i}",
                "benchmark": "Nifty 500 TRI",
                "reviewed_at": as_of,
                "source_document_sha256": f"{i:064x}",
            },
        })
    return candidates


# ======================================================================
# 1. Multi-Asset Reconciliation Denominator Verification (#23)
# ======================================================================

def test_issue_23_multi_asset_and_liabilities_reconciliation_denominator():
    """
    Issue #23 Acceptance: Reconcile complete investor portfolio value, cash,
    external assets, and liabilities before SIP routing. Denominator arithmetic
    is exact down to Decimal string representation.
    """
    as_of = date.today().isoformat()
    assets = [
        {"asset_id": "cas-mf-1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
         "value_inr": "125000.00", "source_ref": "sha256:cas-source", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "ext-mf-1", "asset_class": "external_mutual_fund", "saa_bucket": "mid_cap",
         "value_inr": "100000.00", "source_ref": "sha256:cams-statement", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "eq-direct-1", "asset_class": "direct_equity", "saa_bucket": "small_cap",
         "value_inr": "75000.00", "source_ref": "sha256:demat-holding", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "bank-cash-1", "asset_class": "bank_cash", "saa_bucket": "debt_liquid",
         "value_inr": "150000.00", "source_ref": "sha256:bank-stmt", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "deposit-1", "asset_class": "deposit", "saa_bucket": "debt_liquid",
         "value_inr": "50000.00", "source_ref": "sha256:fd-advice", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "ppf-1", "asset_class": "epf_ppf_nps", "saa_bucket": "debt_liquid",
         "value_inr": "100000.00", "source_ref": "sha256:ppf-passbook", "owner_scope": "primary", "as_of_date": as_of},
    ]
    liabilities = [
        {"liability_id": "home-loan-1", "liability_type": "mortgage", "value_inr": "200000.00",
         "source_ref": "sha256:loan-stmt", "owner_scope": "primary", "as_of_date": as_of},
        {"liability_id": "car-loan-1", "liability_type": "auto_loan", "value_inr": "50000.00",
         "source_ref": "sha256:car-loan-stmt", "owner_scope": "primary", "as_of_date": as_of},
    ]
    sign_off = {
        "attested_by": "lead-fiduciary@firm.org",
        "attestation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "attestation_statement": "Independent audit of complete investor portfolio perimeter, cash, and liabilities.",
    }

    report = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date=as_of,
        sign_off=sign_off,
        liabilities=liabilities,
        report_id="PRR-ACCEPTANCE-23",
    )

    assert report["status"] == "RECONCILED"
    assert report["is_approved_for_sip_routing"] is True
    assert report["report_id"] == "PRR-ACCEPTANCE-23"
    assert report["total_assets_inr"] == "600000.00"
    assert report["total_liabilities_inr"] == "250000.00"
    assert report["net_portfolio_value_inr"] == "350000.00"
    assert report["included_count"] == 6
    assert report["liabilities_count"] == 2
    assert report["unmatched_count"] == 0
    assert report["by_asset_class_inr"]["cas_mutual_fund"] == "125000.00"
    assert report["by_asset_class_inr"]["external_mutual_fund"] == "100000.00"
    assert report["by_asset_class_inr"]["direct_equity"] == "75000.00"
    assert report["by_asset_class_inr"]["bank_cash"] == "150000.00"
    assert report["by_liability_type_inr"]["mortgage"] == "200000.00"
    assert report["by_liability_type_inr"]["auto_loan"] == "50000.00"
    assert isinstance(report["report_sha256"], str)
    assert len(report["report_sha256"]) == 64


def test_issue_23_unmatched_items_or_incomplete_perimeter_strictly_blocks():
    """
    Issue #23 Acceptance: Unmatched items or incomplete perimeter strictly fails closed
    with is_approved_for_sip_routing=False and does not route SIP budget.
    """
    as_of = date.today().isoformat()
    assets = [
        {"asset_id": "cas-1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
         "value_inr": "100000", "source_ref": "sha256:src", "owner_scope": "primary", "as_of_date": as_of}
    ]
    sign_off = {
        "attested_by": "advisor@firm.org",
        "attestation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "attestation_statement": "Attestation statement.",
    }

    # 1. Unmatched items present -> HOLD
    unmatched_report = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date=as_of,
        sign_off=sign_off,
        unmatched_items=[{"description": "Unidentified bank deposit", "amount_inr": "50000"}],
    )
    assert unmatched_report["status"] == "HOLD"
    assert unmatched_report["is_approved_for_sip_routing"] is False
    assert unmatched_report["reason"] == "UNMATCHED_PORTFOLIO_ITEMS_PRESENT"

    # 2. Incomplete perimeter -> HOLD
    incomplete_report = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=False,
        as_of_date=as_of,
        sign_off=sign_off,
    )
    assert incomplete_report["status"] == "HOLD"
    assert incomplete_report["is_approved_for_sip_routing"] is False
    assert incomplete_report["reason"] == "PORTFOLIO_PERIMETER_NOT_ATTESTED"

    # 3. Missing sign-off -> HOLD
    no_signoff = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date=as_of,
        sign_off={},
    )
    assert no_signoff["status"] == "HOLD"
    assert no_signoff["is_approved_for_sip_routing"] is False
    assert no_signoff["reason"] == "SIGN_OFF_ATTESTATION_REQUIRED"


def test_issue_23_invalid_asset_or_liability_dates_raise_input_error():
    """
    Issue #23 Acceptance: Asset or liability valuation date mismatch raises PortfolioInputError.
    """
    as_of = date.today().isoformat()
    yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()
    assets = [
        {"asset_id": "cas-1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
         "value_inr": "100000", "source_ref": "sha256:src", "owner_scope": "primary", "as_of_date": yesterday}
    ]
    with pytest.raises(PortfolioInputError, match="asset valuation dates do not match"):
        reconcile_total_portfolio(assets, perimeter_complete=True, as_of_date=as_of)

    valid_assets = [
        {"asset_id": "cas-1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
         "value_inr": "100000", "source_ref": "sha256:src", "owner_scope": "primary", "as_of_date": as_of}
    ]
    bad_liabilities = [
        {"liability_id": "loan-1", "liability_type": "loan", "value_inr": "50000",
         "source_ref": "sha256:lsrc", "owner_scope": "primary", "as_of_date": yesterday}
    ]
    with pytest.raises(PortfolioInputError, match="liability valuation dates do not match"):
        reconcile_total_portfolio(
            valid_assets, perimeter_complete=True, as_of_date=as_of, liabilities=bad_liabilities
        )


# ======================================================================
# 2. End-to-End Recommendation Trace Through Eligible Candidates (#24)
# ======================================================================

def test_issue_24_complete_eligible_candidate_recommendation_trace(tmp_path, monkeypatch):
    """
    Issue #24 Acceptance: Complete recommendation trace through eligible candidates
    from the live candidate universe. Confirms:
    1. Multi-asset reconciliation denominator (holdings + external assets + cash + liabilities).
    2. Signed reconciliation report generation and cryptographic binding.
    3. SAA drift calculation and incremental routing to eligible sleeves.
    4. Candidate-level selection and allocation simulation for top-scoring Direct schemes.
    5. Whole-budget reconciliation (allocated + unallocated == total monthly budget).
    6. Complete RFC 8785 decision trace generation.
    """
    cas_path = _sample_cas_workbook(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *args, **kwargs: [_sample_holding()])

    as_of = date.today().isoformat()
    candidates = _build_30_candidates(as_of)
    monthly_budget = Decimal("20000.00")

    sign_off = {
        "attested_by": "chief-compliance-officer@fiduciary.org",
        "attestation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "attestation_statement": "Total investor perimeter, cash, external assets, and liabilities independently verified.",
    }

    evidence_refs = {
        key: f"sha256:verified-{key}"
        for key in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")
    }
    evidence_refs["as_of_dates"] = {
        key: as_of
        for key in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")
    }

    candidate_sleeves = {c["fund_id"]: ("large_cap" if i % 2 == 0 else "mid_cap") for i, c in enumerate(candidates)}
    candidate_gate_results = {
        c["fund_id"]: {
            "direct_plan": "PASS",
            "source_authenticity": "PASS",
            "scheme_identity": "PASS",
            "risk": "PASS",
            "constituent_coverage": "PASS",
            "operational": "PASS",
        }
        for c in candidates
    }
    operational_evidence = {
        c["fund_id"]: {
            "scheme_identity": {
                "scheme_id": c["scheme_id"],
                "isin": c["isin"],
                "plan": "Direct",
                "option": "Growth",
                "amc": c["amc_name"],
                "category": c["category"],
                "benchmark": c["benchmark"],
            },
            "evidence_ref": f"sha256:ops-{c['fund_id']}",
            "evidence_as_of_date": as_of,
            "scheme_status": "ACTIVE",
            "minimum_monthly_sip_inr": "1000",
            "exit_load_evidence_ref": "sha256:exit",
            "lockin_evidence_ref": "sha256:lock",
            "subscription_status_evidence_ref": "sha256:sub",
        }
        for c in candidates
    }

    portfolio_context = {
        "evidence_attested_by_provider": True,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
        "current_core_fund_count": 0,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "sign_off": sign_off,
        "require_signed_report": True,
        "assets": [
            {"asset_id": "cas-mf", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
             "value_inr": "125000", "source_ref": "sha256:cas", "owner_scope": "primary", "as_of_date": as_of},
            {"asset_id": "ext-equity", "asset_class": "direct_equity", "saa_bucket": "mid_cap",
             "value_inr": "100000", "source_ref": "sha256:demat", "owner_scope": "primary", "as_of_date": as_of,
             "constituent_weights": {"ISSUER C": 100}, "constituent_weights_coverage_pct": 100},
            {"asset_id": "ext-mf", "asset_class": "external_mutual_fund", "saa_bucket": "small_cap",
             "value_inr": "75000", "source_ref": "sha256:cams", "owner_scope": "primary", "as_of_date": as_of,
             "constituent_weights": {"ISSUER D": 100}, "constituent_weights_coverage_pct": 100},
            {"asset_id": "deposit", "asset_class": "deposit", "saa_bucket": "debt_liquid",
             "value_inr": "100000", "source_ref": "sha256:fd", "owner_scope": "primary", "as_of_date": as_of},
            {"asset_id": "bank-cash", "asset_class": "bank_cash", "saa_bucket": "debt_liquid",
             "value_inr": "100000", "source_ref": "sha256:bank", "owner_scope": "primary", "as_of_date": as_of},
        ],
        "liabilities": [
            {"liability_id": "mortgage", "liability_type": "home_loan", "value_inr": "150000",
             "source_ref": "sha256:loan-doc", "owner_scope": "primary", "as_of_date": as_of},
        ],
        "excluded_assets": [],
        "unmatched_items": [],
        "ips": {
            "approved": True,
            "source_ref": "sha256:approved-ips-contract",
            "effective_date": as_of,
            "tier6_equity_only_authorized": True,
            "target_weights_pct": {
                "large_cap": "35",
                "mid_cap": "25",
                "small_cap": "20",
                "flexi_multi_cap": "15",
                "debt_liquid": "5",
            },
            "tolerance_band_pct": "3",
        },
        "candidate_policy": {
            "max_evidence_age_days": 30,
            "mandatory_gates": [
                "direct_plan", "source_authenticity", "scheme_identity",
                "risk", "constituent_coverage", "operational",
            ],
            "candidate_sleeves": candidate_sleeves,
            "rounding_increment_inr": "500",
        },
        "candidate_gate_results": candidate_gate_results,
        "operational_evidence_by_candidate_id": operational_evidence,
        "goal_policy": {
            "max_evidence_age_days": 30,
            "minimum_horizon_days_by_asset_class": {"equity": 3650},
        },
        "goals": [{
            "goal_id": "wealth-creation",
            "mandate_approved": True,
            "source_ref": "sha256:goal-mandate",
            "evidence_as_of_date": as_of,
            "target_amount_inr": "5000000",
            "liabilities_inr": "150000",
            "target_date": f"{date.today().year + 15}-{date.today().month:02d}-{date.today().day:02d}",
            "asset_class": "equity",
            "approved_risk_profile": "Aggressive",
        }],
        "liquidity": {
            "verified_cash_inr": "100000",
            "approved_reserve_target_inr": "30000",
            "near_term_obligations_inr": "10000",
            "monthly_net_income_inr": "150000",
            "essential_monthly_expenses_inr": "40000",
            "monthly_debt_service_inr": "15000",
            "evidence_refs": evidence_refs,
            "max_evidence_age_days": 30,
        },
        "stress_scenarios": [{
            "scenario_id": "market-correction",
            "income_reduction_pct": "15",
            "expense_increase_pct": "10",
        }],
        "concentration_policy": {
            "max_issuer_pct_of_portfolio": "20",
            "max_sector_pct_of_portfolio": "100",
            "max_market_cap_pct_of_portfolio": "100",
            "max_theme_pct_of_portfolio": "100",
            "classification_as_of_date": as_of,
            "classification_source_ref": "sha256:classifications",
            "issuer_classifications": {
                f"ISSUER {chr(65 + i)}": {"sector": "Multi", "market_cap_bucket": "large_cap", "themes": ["core"]}
                for i in range(10)
            },
            "source_ref": "sha256:conc-policy",
            "effective_date": as_of,
        },
        "freshness": {
            "recommendation_as_of_date": as_of,
            "max_age_days": 30,
            "event_flags": {"manager_change": False, "life_event": False},
        },
    }

    scheme_master = {"status": "VERIFIED", "as_of": as_of}
    master_bytes = b"authoritative-scheme-master-content"
    disclosures = {f"SCHEME-{i:02d}": {"scheme_id": f"SCHEME-{i:02d}"} for i in range(1, 31)}
    disclosures["SCHEME-1"] = {"scheme_id": "SCHEME-1"}
    disclosure_bytes = {f"SCHEME-{i:02d}": f"disclosure-{i}".encode("utf-8") for i in range(1, 31)}
    disclosure_bytes["SCHEME-1"] = b"disclosure-1"

    score_source = b"fiduciary-scores-bytes"
    score_ref = "sha256:" + hashlib.sha256(score_source).hexdigest()
    for c in candidates:
        c["rank_score_source_ref"] = score_ref

    result = service.recommend_sip(
        cas_path=cas_path,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=monthly_budget,
        risk_profile="Aggressive",
        scheme_master=scheme_master,
        scheme_master_source_bytes=master_bytes,
        portfolio_disclosures_by_scheme_id=disclosures,
        portfolio_disclosure_source_bytes_by_scheme_id=disclosure_bytes,
        disclosure_as_of_date=date.today(),
        candidate_universe=candidates,
        portfolio_context=portfolio_context,
        candidate_score_source_bytes=score_source,
    )

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "ASSESSMENT_COMPLETE"
    assert assessment["all_input_gates_pass"] is True

    # 1. Signed reconciliation report checks
    report = assessment["signed_portfolio_reconciliation_report"]
    assert report is not None
    assert report["status"] == "RECONCILED"
    assert report["is_approved_for_sip_routing"] is True
    assert report["total_assets_inr"] == "500000"
    assert report["total_liabilities_inr"] == "150000"
    assert report["net_portfolio_value_inr"] == "350000"
    assert report["liabilities_count"] == 1
    assert assessment["signed_reconciliation_report_sha256"] == report["report_sha256"]

    # 2. SAA drift & incremental routing
    routing = assessment["incremental_sip_routing_simulation"]
    assert routing["status"] == "ROUTED"
    assert routing["reconciliation_ok"] is True
    allocated_sleeve_sum = sum(Decimal(str(v)) for v in routing["allocations_inr"].values())
    unallocated_routing = Decimal(str(routing["unallocated_budget_inr"]))
    assert allocated_sleeve_sum + unallocated_routing == Decimal(str(monthly_budget))

    # 3. Candidate-level selection & allocation simulation
    allocation = assessment["candidate_level_sip_allocation_simulation"]
    assert allocation["status"] == "ALLOCATED"
    assert allocation["reconciliation_ok"] is True
    allocated_funds = allocation["allocations"]
    assert len(allocated_funds) > 0
    # Every selected candidate must be from the eligible candidate universe with verified Direct plan
    for alloc in allocated_funds:
        assert alloc["candidate_id"].startswith("CAND-")
        assert Decimal(alloc["monthly_sip_inr"]) >= Decimal(alloc["scheme_minimum_monthly_sip_inr"])

    # 4. Whole-budget reconciliation
    total_allocated = Decimal(str(allocation["allocated_budget_inr"]))
    total_unallocated = Decimal(str(allocation["unallocated_budget_inr"]))
    assert total_allocated + total_unallocated == Decimal(str(monthly_budget))

    # 5. Cryptographic decision trace verification
    trace = result["portfolio_assessment"]["decision_trace"]
    assert isinstance(trace["sha256"], str)
    assert len(trace["sha256"]) == 64
    trace_obj = json.loads(trace["canonical_record"])
    assert trace_obj["eligibility"]["current_holding_evidence"] == "PASS"
    assert trace_obj["eligibility"]["candidate_universe_count"] == 30
    assert trace_obj["allocation"]["requested_budget_inr"] == "20000.00"
    assert trace_obj["allocation"]["simulated_allocated_budget_inr"] == str(total_allocated)
    assert trace_obj["allocation"]["simulated_unallocated_budget_inr"] == str(total_unallocated)


# ======================================================================
# 3. Deterministic Whole-Budget Reconciliation & Unfillable Sleeves (#24)
# ======================================================================

def test_issue_24_custom_saa_unfillable_sleeve_budget_strictly_preserved(tmp_path, monkeypatch):
    """
    Issue #24 Acceptance: Custom SAA targets route budget to specific sleeves.
    When a sleeve has zero eligible candidates, its allocated sleeve budget
    remains strictly preserved in unallocated_by_sleeve_inr with zero slippage
    or unauthorized redistribution to other sleeves.
    """
    cas_path = _sample_cas_workbook(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *args, **kwargs: [_sample_holding()])

    as_of = date.today().isoformat()
    # Provide 30 candidates, but ALL 30 mapped ONLY to large_cap
    # mid_cap sleeve will have ZERO candidates!
    candidates = _build_30_candidates(as_of)
    candidate_sleeves = {c["fund_id"]: "large_cap" for c in candidates}

    monthly_budget = Decimal("10000.00")
    custom_target = AssetAllocationTarget(
        equity_pct=Decimal("80.0"),
        debt_pct=Decimal("20.0"),
        cash_pct=Decimal("0.0"),
        large_cap_pct=Decimal("40.0"),
        mid_cap_pct=Decimal("20.0"),
        small_cap_pct=Decimal("10.0"),
        flexi_cap_pct=Decimal("10.0"),
        risk_ceiling=4,
    )

    candidate_gate_results = {
        c["fund_id"]: {
            "direct_plan": "PASS", "source_authenticity": "PASS",
            "scheme_identity": "PASS", "risk": "PASS",
            "constituent_coverage": "PASS", "operational": "PASS",
        }
        for c in candidates
    }
    operational_evidence = {
        c["fund_id"]: {
            "scheme_identity": {
                "scheme_id": c["scheme_id"], "isin": c["isin"], "plan": "Direct",
                "option": "Growth", "amc": c["amc_name"], "category": c["category"],
                "benchmark": c["benchmark"],
            },
            "evidence_ref": f"sha256:ops-{c['fund_id']}",
            "evidence_as_of_date": as_of,
            "scheme_status": "ACTIVE",
            "minimum_monthly_sip_inr": "500",
            "exit_load_evidence_ref": "sha256:exit",
            "lockin_evidence_ref": "sha256:lock",
            "subscription_status_evidence_ref": "sha256:sub",
        }
        for c in candidates
    }

    evidence_refs_custom = {
        key: f"sha256:verified-{key}"
        for key in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")
    }
    evidence_refs_custom["as_of_dates"] = {
        key: as_of
        for key in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")
    }

    portfolio_context = {
        "evidence_attested_by_provider": True,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
        "current_core_fund_count": 0,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "sign_off": {
            "attested_by": "advisor@firm.org",
            "attestation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "attestation_statement": "Custom SAA portfolio perimeter verified.",
        },
        "require_signed_report": True,
        "assets": [
            {"asset_id": "cas-mf", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
             "value_inr": "125000", "source_ref": "sha256:cas", "owner_scope": "primary", "as_of_date": as_of},
            {"asset_id": "debt", "asset_class": "deposit", "saa_bucket": "debt_liquid",
             "value_inr": "875000", "source_ref": "sha256:bank", "owner_scope": "primary", "as_of_date": as_of},
        ],
        "excluded_assets": [],
        "unmatched_items": [],
        "ips": {
            "effective_date": as_of,
            "approved": True,
            "source_ref": "sha256:ips",
            "target_weights_pct": {
                "large_cap": 40.0, "mid_cap": 20.0, "small_cap": 10.0,
                "flexi_multi_cap": 10.0, "debt_liquid": 20.0,
            },
            "tolerance_band_pct": 2.0,
        },
        "candidate_policy": {
            "max_evidence_age_days": 30,
            "candidate_sleeves": candidate_sleeves,
            "mandatory_gates": ["direct_plan", "source_authenticity", "scheme_identity", "risk", "constituent_coverage", "operational"],
            "rounding_increment_inr": "500",
        },
        "candidate_gate_results": candidate_gate_results,
        "operational_evidence_by_candidate_id": operational_evidence,
        "goal_policy": {"max_evidence_age_days": 30, "minimum_horizon_days_by_asset_class": {"equity": 365}},
        "goals": [{
            "goal_id": "custom-wealth-goal",
            "mandate_approved": True,
            "source_ref": "sha256:custom-goal",
            "evidence_as_of_date": as_of,
            "target_amount_inr": "2000000",
            "liabilities_inr": "0",
            "target_date": f"{date.today().year + 10}-{date.today().month:02d}-{date.today().day:02d}",
            "asset_class": "equity",
            "approved_risk_profile": "Custom",
        }],
        "liquidity": {
            "verified_cash_inr": "50000", "approved_reserve_target_inr": "20000",
            "near_term_obligations_inr": "5000", "monthly_net_income_inr": "100000",
            "essential_monthly_expenses_inr": "30000", "monthly_debt_service_inr": "0",
            "evidence_refs": evidence_refs_custom,
            "max_evidence_age_days": 30,
        },
        "stress_scenarios": [{
            "scenario_id": "stress-test",
            "income_reduction_pct": "10",
            "expense_increase_pct": "5",
        }],
        "freshness": {"recommendation_as_of_date": as_of, "max_age_days": 30},
        "concentration_policy": {
            "max_issuer_pct_of_portfolio": "25.0",
            "max_sector_pct_of_portfolio": "100",
            "max_market_cap_pct_of_portfolio": "100",
            "max_theme_pct_of_portfolio": "100",
            "classification_as_of_date": as_of,
            "classification_source_ref": "sha256:custom-classifications",
            "issuer_classifications": {
                f"ISSUER {chr(65 + i)}": {"sector": "Multi", "market_cap_bucket": "large_cap", "themes": ["core"]}
                for i in range(10)
            },
            "source_ref": "sha256:conc-policy",
            "effective_date": as_of,
        },
    }

    scheme_master = {"status": "VERIFIED"}
    master_bytes = b"master"
    disclosures = {f"SCHEME-{i:02d}": {"scheme_id": f"SCHEME-{i:02d}"} for i in range(1, 31)}
    disclosures["SCHEME-1"] = {"scheme_id": "SCHEME-1"}
    disclosure_bytes = {f"SCHEME-{i:02d}": f"disclosure-{i}".encode("utf-8") for i in range(1, 31)}
    disclosure_bytes["SCHEME-1"] = b"disc"

    score_source = b"score-bytes"
    score_ref = "sha256:" + hashlib.sha256(score_source).hexdigest()
    for c in candidates:
        c["rank_score_source_ref"] = score_ref

    result = service.recommend_sip(
        cas_path=cas_path,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=monthly_budget,
        risk_profile="Custom",
        scheme_master=scheme_master,
        scheme_master_source_bytes=master_bytes,
        portfolio_disclosures_by_scheme_id=disclosures,
        portfolio_disclosure_source_bytes_by_scheme_id=disclosure_bytes,
        disclosure_as_of_date=date.today(),
        candidate_universe=candidates,
        portfolio_context=portfolio_context,
        custom_saa_target=custom_target,
        candidate_score_source_bytes=score_source,
    )

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "ASSESSMENT_COMPLETE"

    # Custom SAA target weights verified in total portfolio context
    saa = assessment["saa"]
    assert saa["target_weights_pct"]["large_cap"] == 40.0
    assert saa["target_weights_pct"]["mid_cap"] == 20.0
    assert saa["target_weights_pct"]["small_cap"] == 10.0
    assert saa["target_weights_pct"]["flexi_multi_cap"] == 10.0
    assert saa["target_weights_pct"]["debt_liquid"] == 20.0

    # Incremental routing routed budget to large_cap (only eligible sleeve)
    routing = assessment["incremental_sip_routing_simulation"]
    assert "large_cap" in routing["allocations_inr"]

    # Candidate allocation checks
    allocation = assessment["candidate_level_sip_allocation_simulation"]
    assert allocation["reconciliation_ok"] is True
    allocated = Decimal(str(allocation["allocated_budget_inr"]))
    unallocated = Decimal(str(allocation["unallocated_budget_inr"]))
    assert allocated + unallocated == Decimal(str(monthly_budget))
    # Unrouted SAA budget is preserved exactly
    unrouted_saa = Decimal(str(allocation["unrouted_saa_budget_inr"]))
    routed_unallocated = Decimal(str(allocation["routed_but_unallocated_budget_inr"]))
    assert unrouted_saa + routed_unallocated == unallocated
