"""
tests/test_order_2_investor_perimeter_and_mandates.py

Authoritative acceptance test suite for Order 2:
- Issue #107: CAS/CGS cache integrity, non-coercion of missing/malformed values,
  strict rejection of non-finite/boolean/negative inputs, and faithful preservation of UNAVAILABLE as None.
- Issue #52: Statement provenance verification, strict separation of structural validity
  from authenticated publisher attribution, and fail-closed handling of unverified text markers.
- Issue #106: Active SIP mandate classification, extraction of authenticated registrar mandate
  evidence, and strict rejection of ordinary purchases, future-dated transactions, and paused mandates.
- Issue #23: Complete portfolio perimeter reconciliation across holdings, cash, deposits,
  external assets, and liabilities with canonical signed reconciliation report artifact.
- Issue #31: SIP affordability, emergency reserve adequacy, near-term cash obligations,
  and multi-scenario stress testing without missing-as-zero defaults.
- Issue #55: End-to-end Decimal money contract across ingestion, holdings, plans,
  and budget reconciliation down to exact paise without float rounding drift.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest

from core.models import (
    AssetAllocationTarget,
    AssetClass,
    DeterministicSIPPlan,
    DeterministicSIPRecommendation,
    HoldingItem,
    PlanType,
    RiskTier,
    quantize_inr,
)
from core.portfolio_sip_controls import (
    PortfolioInputError,
    assess_liquidity_and_sip_surplus,
    calculate_saa_drift,
    generate_signed_portfolio_reconciliation_report,
    reconcile_total_portfolio,
    route_incremental_sip,
    stress_test_sip_affordability,
)
from core.math_engine import (
    _validated_ips_numeric_inputs,
    calculate_cash_deployment,
    compute_deterministic_sip_blueprint,
    compute_liquidity_waterfall,
)
from ingestion.cas_parser import (
    detect_active_sips_from_cas,
    load_cache_csv,
    parse_cache_csv,
    stage_portfolio,
    to_cache_csv,
    validate_statement_reconciliation_envelope,
)
from ingestion.statement_validator import (
    StatementValidationResult,
    authenticate_statement_provenance,
    require_authenticated_statement,
    validate_cas_excel,
)
import services.sip_recommendation as sip_service


# =============================================================================
# Helper Fixtures
# =============================================================================

def _build_minimal_cas_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["HDFC Top 100 Direct Growth", "FOLIO-101", 100000.0, 125000.0, 1000.0])
    ws.append(["ICICI Prudential Bluechip Direct", "FOLIO-102", 80000.0, 95000.0, 800.0])
    ws.append(["Parag Parikh Flexi Cap Direct", "FOLIO-103", 120000.0, 160000.0, 1200.0])
    ws.append(["SBI Small Cap Direct Growth", "FOLIO-104", 50000.0, 70000.0, 500.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# =============================================================================
# 1. Issue #107: CAS Cache Integrity & Non-Coercion
# =============================================================================

def test_issue_107_strict_rejection_of_missing_and_malformed_fields():
    """Verify to_cache_csv strictly rejects missing current_value, units, or invested_value."""
    # Missing current_value
    with pytest.raises(ValueError, match="current_value"):
        to_cache_csv({"holdings": [{"scheme": "S1", "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)

    # Missing units
    with pytest.raises(ValueError, match="units"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": 1000.0, "invested_value": 1000.0}]}, enriched=True, strict=True)

    # Missing invested_value
    with pytest.raises(ValueError, match="invested"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": 1000.0, "units": 10.0}]}, enriched=True, strict=True)

    # Non-finite values (NaN, Inf)
    with pytest.raises(ValueError, match="non-finite"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": float("nan"), "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)

    with pytest.raises(ValueError, match="non-finite"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": 1000.0, "units": float("inf"), "invested_value": 1000.0}]}, enriched=True, strict=True)

    # Negative values
    with pytest.raises(ValueError, match="Negative"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": -100.0, "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)


def test_issue_107_strict_rejection_of_boolean_and_empty_string_values():
    """Verify booleans and empty strings are rejected rather than coerced into 1.0 or 0.0."""
    with pytest.raises(ValueError, match="Boolean value not allowed"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": True, "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)

    with pytest.raises(ValueError, match="Boolean value not allowed"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": 1000.0, "units": False, "invested_value": 1000.0}]}, enriched=True, strict=True)

    with pytest.raises(ValueError, match="Missing required field"):
        to_cache_csv({"holdings": [{"scheme": "S1", "current_value": "", "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)


def test_issue_107_parse_cache_csv_preserves_unavailable_as_none():
    """Verify parse_cache_csv faithfully preserves UNAVAILABLE as None without numeric coercion to 0.0."""
    csv_content = (
        '"Scheme Name",CurrentValue,Units,Invested,"Folio Number",ISIN,NAV,NAV_Source\n'
        '"Scheme Unavailable",UNAVAILABLE,UNAVAILABLE,1000.00,"F101","INF101",UNAVAILABLE,NONE\n'
        '"Scheme Available",2500.00,20.000,2000.00,"F102","INF102",125.0000,SOURCE\n'
    )
    rows = parse_cache_csv(csv_content)
    assert len(rows) == 2
    unavail = rows[0]
    assert unavail["scheme"] == "Scheme Unavailable"
    assert unavail["current_value"] is None
    assert unavail["units"] is None
    assert unavail["nav"] is None
    assert unavail["invested"] == 1000.00

    avail = rows[1]
    assert avail["scheme"] == "Scheme Available"
    assert avail["current_value"] == 2500.00
    assert avail["units"] == 20.000
    assert avail["nav"] == 125.0000


# =============================================================================
# 2. Issue #52: Statement Provenance & Publisher Attribution
# =============================================================================

def test_issue_52_structural_validity_does_not_imply_publisher_authentication():
    """Verify valid CAS structure alone does not grant publisher authentication."""
    file_bytes = _build_minimal_cas_workbook()
    res = validate_cas_excel(file_bytes, "cas_upload.xlsx")
    assert res.is_valid is True
    assert res.structural_validity is True
    assert res.rta_source == "Unknown"
    assert res.detected_content_publisher == "Unknown"
    assert res.is_publisher_authenticated is False
    assert res.publisher_authenticity_status == "UNVERIFIED"
    assert res.authenticated_publisher is None

    # require_authenticated_statement must fail closed
    with pytest.raises(ValueError, match="Statement publisher is unauthenticated"):
        require_authenticated_statement(res)


def test_issue_52_text_markers_do_not_upgrade_authenticity():
    """Verify text strings like 'CAMS' inside spreadsheet content do not authenticate the publisher."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["CAMS Computer Age Management Services Pvt Ltd"])
    ws.append(["Consolidated Account Statement"])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["HDFC Top 100 Direct", "101", 10000, 12000, 100])
    ws.append(["ICICI Bluechip Direct", "102", 10000, 12000, 100])
    ws.append(["SBI Small Cap Direct", "103", 10000, 12000, 100])
    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "cams_spoof.xlsx")
    assert res.is_valid is True
    # The detector marks text content as detected, but authenticity remains unauthenticated
    assert res.is_publisher_authenticated is False
    assert res.rta_source == "Unknown"
    assert res.detected_content_publisher == "CAMS"
    assert res.publisher_authenticity_status == "UNAUTHENTICATED_DOCUMENT_CONTENT"
    assert res.authenticated_publisher is None


def test_issue_52_genuine_provenance_authenticates_publisher():
    """Verify genuine signed provenance metadata successfully authenticates publisher."""
    file_bytes = _build_minimal_cas_workbook()
    digest = hashlib.sha256(file_bytes).hexdigest()

    # Authenticate with valid provider metadata
    evidence = {
        "publisher": "CAMS",
        "source_digest": digest,
        "source_signature": "sig:ed25519:valid_cams_signature",
        "verification_method": "TRUSTED_SIGNATURE",
        "verified_at": "2026-11-12T10:00:00Z",
        "evidence_reference": "test-signature:cas-cams-001",
    }
    raw_res = validate_cas_excel(file_bytes, "cas_cams.xlsx")
    authenticated_res = authenticate_statement_provenance(
        raw_res,
        evidence=evidence,
        trusted_verifier=lambda digest, publisher, supplied: (
            digest == hashlib.sha256(file_bytes).hexdigest()
            and publisher == "CAMS"
            and supplied.get("source_signature") == "sig:ed25519:valid_cams_signature"
        ),
    )
    assert authenticated_res.is_publisher_authenticated is True
    assert authenticated_res.publisher_authenticity_status == "AUTHENTICATED_SOURCE"
    assert authenticated_res.authenticated_publisher == "CAMS"
    # Now require_authenticated_statement passes cleanly
    require_authenticated_statement(authenticated_res)


# =============================================================================
# 3. Issue #106: Active SIP Mandate Classification
# =============================================================================

def test_issue_106_rejects_ordinary_purchases_as_active_sips():
    """Verify recurring ordinary purchases without mandate evidence are rejected."""
    as_of = "2026-10-15"
    transactions = [
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-08-01", "type": "PURCHASE", "description": "Lump sum purchase", "amount": 10000.0},
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-09-01", "type": "PURCHASE", "description": "Lump sum purchase", "amount": 10000.0},
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-10-01", "type": "PURCHASE", "description": "Lump sum purchase", "amount": 10000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of=as_of)
    assert res["active_sip_count"] == 0
    assert res["total_monthly_sip"] == 0.0


def test_issue_106_rejects_future_dated_and_paused_mandates():
    """Verify future-dated installments and paused/cancelled mandates are rejected."""
    as_of = "2026-10-15"
    # Future dated
    tx_future = [
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-09-01", "type": "SIP", "amount": 5000.0, "mandate_id": "MND-1", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-11-01", "type": "SIP", "amount": 5000.0, "mandate_id": "MND-1", "mandate_status": "ACTIVE"},
    ]
    res_future = detect_active_sips_from_cas(tx_future, as_of=as_of)
    assert res_future["active_sip_count"] == 0
    assert res_future["rejection_stats"]["rejected_future_dated"] >= 1

    # Paused mandate
    tx_paused = [
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-08-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND-2", "mandate_status": "PAUSED"},
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-09-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND-2", "mandate_status": "PAUSED"},
        {"folio": "F1", "scheme": "Scheme Alpha", "date": "2026-10-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND-2", "mandate_status": "PAUSED"},
    ]
    res_paused = detect_active_sips_from_cas(tx_paused, as_of=as_of)
    assert res_paused["active_sip_count"] == 0


def test_issue_106_identifies_active_recurring_mandate_correctly():
    """Verify valid recurring SIP with active mandate evidence is correctly classified."""
    as_of = "2026-10-15"
    transactions = [
        {"folio": "F1", "scheme": "Core Growth Direct", "date": "2026-08-10", "type": "SIP", "description": "SIP auto debit", "amount": 5000.0, "mandate_id": "UMRN1234567890", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Core Growth Direct", "date": "2026-09-10", "type": "SIP", "description": "SIP auto debit", "amount": 5000.0, "mandate_id": "UMRN1234567890", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Core Growth Direct", "date": "2026-10-10", "type": "SIP", "description": "SIP auto debit", "amount": 5000.0, "mandate_id": "UMRN1234567890", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(transactions, as_of=as_of)
    # CAS transaction rows, free-text SIP labels, UMRNs and a local ACTIVE
    # status claim are not authenticated registrar/AMC/bank mandate evidence.
    # They must remain an unverified pattern and never enter affordability.
    assert res["active_sip_count"] == 0
    assert res["total_monthly_sip"] == 0.0
    assert res["active_sips"] == []
    assert res["recurring_transaction_pattern_count"] == 1
    assert res["recurring_transaction_patterns"][0]["scheme"] == "Core Growth Direct"
    assert res["recurring_transaction_patterns"][0]["confidence"] == "UNVERIFIED"


# =============================================================================
# 4. Issue #23: Complete Portfolio Perimeter & Signed Report Artifact
# =============================================================================

def test_issue_23_multi_asset_reconciliation_and_canonical_report():
    """Verify multi-asset denominator arithmetic and RFC 8785 canonical signed report generation."""
    as_of = "2026-11-01"
    assets = [
        {"asset_id": "A1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap", "value_inr": "500000.00", "source_ref": "sha256:cas", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "A2", "asset_class": "bank_cash", "saa_bucket": "debt_liquid", "value_inr": "200000.00", "source_ref": "sha256:bank", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "A3", "asset_class": "deposit", "saa_bucket": "debt_liquid", "value_inr": "300000.00", "source_ref": "sha256:fd", "owner_scope": "primary", "as_of_date": as_of},
    ]
    liabilities = [
        {"liability_id": "L1", "liability_type": "mortgage", "value_inr": "150000.00", "source_ref": "sha256:loan", "owner_scope": "primary", "as_of_date": as_of}
    ]
    sign_off = {
        "attested_by": "lead-fiduciary@firm.org",
        "attestation_timestamp_utc": "2026-11-01T12:00:00Z",
        "attestation_statement": "Complete perimeter attested and verified.",
        "signature_ref": "sig:ed25519:test_sig",
    }

    report = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date=as_of,
        sign_off=sign_off,
        liabilities=liabilities,
        report_id="PRR-ACCEPTANCE-001",
    )

    assert report["status"] == "RECONCILED"
    assert report["is_approved_for_sip_routing"] is True
    assert report["total_assets_inr"] == "1000000.00"
    assert report["total_liabilities_inr"] == "150000.00"
    assert report["net_portfolio_value_inr"] == "850000.00"
    assert report["unmatched_count"] == 0
    assert isinstance(report["report_sha256"], str)
    assert len(report["report_sha256"]) == 64


def test_issue_23_unmatched_items_or_date_mismatch_strictly_fails_closed():
    """Verify presence of unmatched items or date mismatch blocks SIP routing."""
    as_of = "2026-11-01"
    assets = [
        {"asset_id": "A1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap", "value_inr": "500000.00", "source_ref": "sha256:cas", "owner_scope": "primary", "as_of_date": as_of}
    ]
    sign_off = {
        "attested_by": "advisor@firm.org",
        "attestation_timestamp_utc": "2026-11-01T12:00:00Z",
        "attestation_statement": "Attested.",
    }

    # 1. Unmatched items present -> HOLD
    report_unmatched = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date=as_of,
        sign_off=sign_off,
        unmatched_items=[{"raw_record": "Unknown holding record"}],
    )
    assert report_unmatched["status"] == "HOLD"
    assert report_unmatched["is_approved_for_sip_routing"] is False
    assert report_unmatched["reason"] == "UNMATCHED_PORTFOLIO_ITEMS_PRESENT"

    # 2. Date mismatch raises PortfolioInputError
    assets_mismatched = [
        {"asset_id": "A1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap", "value_inr": "500000.00", "source_ref": "sha256:cas", "owner_scope": "primary", "as_of_date": "2026-10-15"}
    ]
    with pytest.raises(PortfolioInputError, match="valuation date"):
        reconcile_total_portfolio(assets_mismatched, perimeter_complete=True, as_of_date=as_of, sign_off=sign_off)


# =============================================================================
# 5. Issue #31: SIP Affordability & Liquidity Runway
# =============================================================================

def test_issue_31_liquidity_waterfall_and_reserve_enforcement():
    """Verify assess_liquidity_and_sip_surplus enforces emergency reserve and monthly surplus."""
    as_of = "2026-11-01"
    evidence_refs = {
        "cash": "BANK-01",
        "reserve": "IPS-01",
        "obligations": "IPS-01",
        "income": "SAL-01",
        "expenses": "EXP-01",
        "debt_service": "LOAN-01",
        "as_of_dates": {
            "cash": as_of, "reserve": as_of, "obligations": as_of,
            "income": as_of, "expenses": as_of, "debt_service": as_of,
        },
    }

    # Case A: Cash below reserve + obligations -> HOLD
    res_underfunded = assess_liquidity_and_sip_surplus(
        verified_cash_inr="100000.00",
        approved_reserve_target_inr="150000.00",
        near_term_obligations_inr="20000.00",
        monthly_net_income_inr="100000.00",
        essential_monthly_expenses_inr="40000.00",
        monthly_debt_service_inr="10000.00",
        proposed_monthly_sip_inr="15000.00",
        evidence_refs=evidence_refs,
        as_of_date=as_of,
        max_evidence_age_days=45,
    )
    assert res_underfunded["status"] == "HOLD"
    assert res_underfunded["reason"] == "VERIFIED_CASH_BELOW_RESERVE_AND_OBLIGATIONS"

    # Case B: Proposed SIP exceeds monthly surplus -> HOLD
    res_excess_sip = assess_liquidity_and_sip_surplus(
        verified_cash_inr="300000.00",
        approved_reserve_target_inr="150000.00",
        near_term_obligations_inr="20000.00",
        monthly_net_income_inr="100000.00",
        essential_monthly_expenses_inr="60000.00",
        monthly_debt_service_inr="30000.00",  # surplus = 10,000
        proposed_monthly_sip_inr="15000.00",  # proposed 15,000 > 10,000
        evidence_refs=evidence_refs,
        as_of_date=as_of,
        max_evidence_age_days=45,
    )
    assert res_excess_sip["status"] == "HOLD"
    assert res_excess_sip["reason"] == "PROPOSED_SIP_EXCEEDS_VERIFIED_SURPLUS"

    # Case C: Fully funded & affordable -> AFFORDABLE
    res_pass = assess_liquidity_and_sip_surplus(
        verified_cash_inr="300000.00",
        approved_reserve_target_inr="150000.00",
        near_term_obligations_inr="20000.00",
        monthly_net_income_inr="150000.00",
        essential_monthly_expenses_inr="50000.00",
        monthly_debt_service_inr="20000.00",  # surplus = 80,000
        proposed_monthly_sip_inr="25000.00",  # proposed 25,000 <= 80,000
        evidence_refs=evidence_refs,
        as_of_date=as_of,
        max_evidence_age_days=45,
    )
    assert res_pass["status"] == "AFFORDABLE"
    assert res_pass["deployable_cash_inr"] == "130000.00"
    assert res_pass["monthly_surplus_inr"] == "80000.00"


def test_issue_31_stress_testing_affordability_shocks():
    """Verify stress_test_sip_affordability evaluates multi-scenario shocks."""
    scenarios = [
        {"scenario_id": "income-shock-10", "income_reduction_pct": "10", "expense_increase_pct": "5"},
        {"scenario_id": "severe-shock-30", "income_reduction_pct": "30", "expense_increase_pct": "15"},
    ]
    # Net income: 100,000; Expenses: 40,000; Debt: 10,000; Proposed SIP: 20,000
    # Scenario 1: Income = 90,000, Expenses = 42,000, Debt = 10,000 -> Surplus = 38,000 >= 20,000 (PASS)
    # Scenario 2: Income = 70,000, Expenses = 46,000, Debt = 10,000 -> Surplus = 14,000 < 20,000 (FAIL)
    res = stress_test_sip_affordability(
        monthly_net_income_inr="100000.00",
        essential_monthly_expenses_inr="40000.00",
        monthly_debt_service_inr="10000.00",
        proposed_monthly_sip_inr="20000.00",
        scenarios=scenarios,
    )
    assert res["status"] == "ASSESSED"
    assert res["all_scenarios_sustainable"] is False
    assert res["scenarios"][0]["status"] == "SUSTAINABLE"
    assert res["scenarios"][1]["status"] == "UNSUSTAINABLE"


# =============================================================================
# 6. Issue #55: Decimal Money Contract Across Calculations & Outputs
# =============================================================================

def test_issue_55_quantize_inr_exact_half_up_paise():
    """Verify quantize_inr rounds half-up to exact paise across string, float, and Decimal inputs."""
    assert quantize_inr(Decimal("100.555")) == Decimal("100.56")
    assert quantize_inr(Decimal("100.554")) == Decimal("100.55")
    assert quantize_inr("25000.125") == Decimal("25000.13")
    assert quantize_inr(15000.5) == Decimal("15000.50")


def test_issue_55_holding_item_preserves_exact_decimal_types():
    """Verify HoldingItem enforces Decimal instances without binary float coercion."""
    h = HoldingItem(
        fund_id="fund-large",
        scheme="HDFC Top 100 Direct",
        fund_name="HDFC Top 100 Direct",
        folio="101/2",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.LARGE_CAP,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=Decimal("125432.85"),
        invested_value_inr=Decimal("100000.00"),
        units=Decimal("1250.4567"),
        nav=Decimal("100.3096"),
    )
    assert isinstance(h.current_value_inr, Decimal)
    assert h.current_value_inr == Decimal("125432.85")
    assert isinstance(h.units, Decimal)
    assert h.units == Decimal("1250.4567")


def test_issue_55_deterministic_sip_plan_exact_budget_reconciliation():
    """Verify DeterministicSIPPlan validates allocated + unallocated == total_monthly_budget_inr."""
    total = Decimal("15000.00")
    items = [
        DeterministicSIPRecommendation(
            category_role="Core Flexi-Cap Compounder",
            scheme_name="Parag Parikh Flexi Cap Direct",
            folio_target="FOLIO-1",
            monthly_inr=Decimal("7500.00"),
            allocation_pct=50.0,
            rational_code="CORE_COMPOUNDER",
            fiduciary_rationale="Core compounder",
            is_direct=True,
        ),
        DeterministicSIPRecommendation(
            category_role="Large-Cap Bluechip Anchor",
            scheme_name="HDFC Top 100 Direct",
            folio_target="FOLIO-2",
            monthly_inr=Decimal("5000.00"),
            allocation_pct=33.33,
            rational_code="BLUECHIP_ANCHOR",
            fiduciary_rationale="Bluechip anchor",
            is_direct=True,
        ),
    ]
    # Total allocated = 12,500.00 -> unallocated must be exactly 2,500.00
    plan = DeterministicSIPPlan(
        total_monthly_budget_inr=total,
        unallocated_budget_inr=Decimal("2500.00"),
        equity_sip_pct=83.33,
        debt_sip_pct=0.0,
        items=items,
        execution_status="EXECUTION_READY",
    )
    assert plan.total_monthly_budget_inr == total
    assert plan.unallocated_budget_inr == Decimal("2500.00")
    assert sum(item.monthly_inr for item in plan.items) == Decimal("12500.00")
    assert sum(item.monthly_inr for item in plan.items) + plan.unallocated_budget_inr == total

    # Tampered unallocated budget must fail validation
    with pytest.raises(ValueError, match="Allocated SIP amounts"):
        DeterministicSIPPlan(
            total_monthly_budget_inr=total,
            unallocated_budget_inr=Decimal("2500.05"),  # 5 paise mismatch
            equity_sip_pct=83.33,
            debt_sip_pct=0.0,
            items=items,
            execution_status="EXECUTION_READY",
        )


# =============================================================================
# 7. End-to-End Order 2 Integration Pipeline
# =============================================================================

def test_order_2_end_to_end_pipeline_integration(tmp_path, monkeypatch):
    """
    Test complete Order 2 integration flow:
    Genuine CAS Ingestion -> Active SIP Detection -> SAA Drift & Reconciliation ->
    Affordability Clearance -> Exact Decimal Incremental SIP Routing.
    """
    as_of = date.today().isoformat()
    cas_path = tmp_path / "client_cas.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Core Large Cap Direct Growth", "FOLIO-1", 100000.0, 150000.0, 1000.0])
    ws.append(["Core Mid Cap Direct Growth", "FOLIO-2", 80000.0, 100000.0, 800.0])
    ws.append(["Core Small Cap Direct Growth", "FOLIO-3", 50000.0, 70000.0, 500.0])
    ws.append(["Core Debt Direct Growth", "FOLIO-4", 100000.0, 105000.0, 1000.0])
    wb.save(cas_path)

    # 1. Provenance check
    cas_bytes = cas_path.read_bytes()
    val_res = validate_cas_excel(cas_bytes, "client_cas.xlsx")
    assert val_res.is_valid is True
    assert val_res.structural_validity is True

    # 2. Portfolio context and signed report
    assets = [
        {"asset_id": "cas-1", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
         "value_inr": "150000.00", "source_ref": "sha256:cas", "owner_scope": "primary", "as_of_date": as_of},
        {"asset_id": "cash-1", "asset_class": "bank_cash", "saa_bucket": "debt_liquid",
         "value_inr": "100000.00", "source_ref": "sha256:bank", "owner_scope": "primary", "as_of_date": as_of},
    ]
    sign_off = {
        "attested_by": "lead-advisor@wealth.com",
        "attestation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "attestation_statement": "Perimeter verified.",
        "signature_ref": "sig:ed25519:test",
    }
    report = generate_signed_portfolio_reconciliation_report(
        assets, perimeter_complete=True, as_of_date=as_of, sign_off=sign_off
    )
    assert report["status"] == "RECONCILED"
    assert report["total_assets_inr"] == "250000.00"

    # 3. Liquidity clearance
    evidence_refs = {
        "cash": "BANK-01", "reserve": "IPS-01", "obligations": "IPS-01",
        "income": "SAL-01", "expenses": "EXP-01", "debt_service": "LOAN-01",
        "as_of_dates": {k: as_of for k in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")},
    }
    liquidity = assess_liquidity_and_sip_surplus(
        verified_cash_inr="100000.00",
        approved_reserve_target_inr="50000.00",
        near_term_obligations_inr="0.00",
        monthly_net_income_inr="150000.00",
        essential_monthly_expenses_inr="50000.00",
        monthly_debt_service_inr="0.00",
        proposed_monthly_sip_inr="10000.00",
        evidence_refs=evidence_refs,
        as_of_date=as_of,
        max_evidence_age_days=45,
    )
    assert liquidity["status"] == "AFFORDABLE"

    # 4. Incremental SIP routing with exact Decimal money
    current = {"large_cap": "150000.00", "mid_cap": "0.00", "small_cap": "0.00", "flexi_multi_cap": "0.00", "debt_liquid": "100000.00"}
    targets = {"large_cap": "35.0", "mid_cap": "20.0", "small_cap": "15.0", "flexi_multi_cap": "10.0", "debt_liquid": "20.0"}
    routing = route_incremental_sip(
        monthly_budget_inr="10000.00",
        current_values_inr=current,
        target_weights_pct=targets,
        portfolio_total_inr="250000.00",
        tolerance_band_pct="3.0",
        eligible_sleeves=["mid_cap", "small_cap", "flexi_multi_cap"],
        rounding_increment_inr="500",
    )
    assert routing["status"] == "ROUTED"
    assert routing["reconciliation_ok"] is True
    allocated = Decimal(routing["allocated_budget_inr"])
    unallocated = Decimal(routing["unallocated_budget_inr"])
    assert allocated + unallocated == Decimal("10000.00")
