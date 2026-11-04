from datetime import date
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl

from services import sip_recommendation as service


def _holding():
    return SimpleNamespace(
        scheme="Example Direct Growth",
        fund_id="FUND-1",
        scheme_id="SCHEME-1",
        plan_option_status="VERIFIED",
        option_type="GROWTH",
        is_direct=True,
        lookthrough_status="VERIFIED",
        metrics_status="VERIFIED",
        constituent_weights={"ISSUER-A": 60.0, "ISSUER-B": 40.0},
        equity_pct=100.0,
        constituent_weights_coverage_pct=100.0,
        current_value_inr=125000.0,
    )


def _inputs(tmp_path):
    cas = tmp_path / "cas.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", date.today().strftime("%d-%b-%Y")])
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append(["Synthetic Fund", "FOLIO-1", 100000.0, 125000.0, 1000.0])
    workbook.save(cas)
    return {
        "cas_path": cas,
        "metrics_path": None,
        "aliases_path": None,
        "monthly_budget_inr": 10000,
        "risk_profile": "Aggressive",
        "scheme_master": {"status": "VERIFIED"},
        "scheme_master_source_bytes": b"scheme master source",
        "portfolio_disclosures_by_scheme_id": {"SCHEME-1": {"scheme_id": "SCHEME-1"}},
        "portfolio_disclosure_source_bytes_by_scheme_id": {"SCHEME-1": b"disclosure source"},
        "disclosure_as_of_date": date.today(),
        "candidate_universe": [{"fund_id": "CANDIDATE-1", "scheme_id": "CANDIDATE-SCHEME-1"}],
    }


def test_missing_scheme_master_fails_closed_without_loading_cas(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["scheme_master"] = None
    monkeypatch.setattr(
        service, "load_holdings_from_cas_excel",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("CAS must not be loaded")),
    )

    result = service.recommend_sip(**args)

    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000
    assert any("scheme master" in reason for reason in result["reasons"])


def test_missing_holding_disclosure_fails_closed(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [
        SimpleNamespace(
            scheme="Example Direct Growth", fund_id="FUND-1", scheme_id="SCHEME-1",
            lookthrough_status="MISSING", constituent_weights_coverage_pct=None,
            current_value_inr=125000.0,
        )
    ])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Engine must not run")),
    )

    result = service.recommend_sip(**args)

    assert result["status"] == "HOLD"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000
    assert any("MISSING" in reason for reason in result["reasons"])


def test_verified_evidence_reaches_engine_but_provisional_allocations_are_suppressed(
    tmp_path, monkeypatch
):
    args = _inputs(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    captured = {}

    def fake_engine(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(items=[SimpleNamespace(monthly_inr=10000)])

    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", fake_engine)

    result = service.recommend_sip(**args)

    assert captured["holdings"][0].scheme_id == "SCHEME-1"
    assert captured["portfolio_disclosures_by_scheme_id"] is args["portfolio_disclosures_by_scheme_id"]
    assert captured["portfolio_disclosure_source_bytes_by_scheme_id"] is args[
        "portfolio_disclosure_source_bytes_by_scheme_id"
    ]
    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_custom_risk_profile_is_not_silently_mapped(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["risk_profile"] = "Custom"
    monkeypatch.setattr(
        service, "load_holdings_from_cas_excel",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Custom must not be mapped")),
    )

    result = service.recommend_sip(**args)

    assert result["status"] == "HOLD"
    assert any("Custom" in reason for reason in result["reasons"])


def test_malformed_coverage_fails_closed_without_raising(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    holding = _holding()
    holding.constituent_weights_coverage_pct = "not-a-number"
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [holding])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Engine must not run")),
    )

    result = service.recommend_sip(**args)

    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000
    assert any("malformed" in reason for reason in result["reasons"])


def test_cas_parser_errors_fail_closed_without_leaking_exception_text(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    monkeypatch.setattr(
        service, "load_holdings_from_cas_excel",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("private parser detail")),
    )

    result = service.recommend_sip(**args)

    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["unallocated_budget_inr"] == 10000
    assert "ValueError" in result["reasons"][0]
    assert "private parser detail" not in result["reasons"][0]



def test_missing_fund_metrics_blocks_even_when_scheme_and_lookthrough_are_verified(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    holding = _holding()
    holding.metrics_status = "MISSING"
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [holding])
    monkeypatch.setattr(
        service,
        "compute_deterministic_sip_blueprint",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Engine must not run")),
    )

    result = service.recommend_sip(**args)

    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000
    assert any("fund category/risk/exposure metrics are MISSING" in reason for reason in result["reasons"])


def test_verified_cas_holdings_return_policy_saa_diagnostic_but_never_route_budget(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    holding = _holding()
    holding.asset_class = "Large_Cap"
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [holding])
    monkeypatch.setattr(
        service,
        "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[SimpleNamespace(monthly_inr=10000)]),
    )

    result = service.recommend_sip(**args)

    assessment = result["portfolio_assessment"]
    assert assessment["status"] == "DIAGNOSTIC_ONLY"
    assert assessment["scope"] == "CAS_MUTUAL_FUND_HOLDINGS_ONLY"
    assert assessment["portfolio_perimeter_complete"] is False
    assert assessment["total_value_inr"] == 125000.0
    assert assessment["current_sleeve_values_inr"]["large_cap"] == 125000.0
    assert assessment["target_sleeve_weights_pct"]["large_cap"] == 20
    assert assessment["policy_profile"] == "very_high"
    assert assessment["saa_drift"]["current_weights_pct"]["large_cap"] == "100"
    assert assessment["sip_routing"]["status"] == "HOLD"
    assert assessment["sip_routing"]["allocated_budget_inr"] == 0.0
    assert assessment["lookthrough"]["status"] == "CALCULATED"
    assert float(assessment["lookthrough"]["issuer_exposure_inr"]["ISSUER-A"]) == 75000.0
    assert len(assessment["decision_trace"]["sha256"]) == 64
    assert assessment["decision_trace"]["algorithm"] == "SHA-256-CANONICAL-JSON-v1"
    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000


def _candidate_universe():
    candidates = []
    for index in range(1, 31):
        fund_id = f"CANDIDATE-{index}"
        scheme_id = f"CANDIDATE-SCHEME-{index}"
        isin = f"INF000000{index:03d}"
        candidates.append({
            "fund_id": fund_id, "scheme_id": scheme_id, "isin": isin,
            "amc_name": "Example AMC", "category": "Large Cap",
            "benchmark": "Nifty 100 TRI", "is_direct": True,
            "constituent_weights": {"ISSUER-A": 60, "ISSUER-C": 40},
            "constituent_weights_coverage_pct": 100,
            "rank_score": str(index),
            "rank_score_source_ref": f"sha256:rank-score-{index}",
            "rank_score_as_of_date": date.today().isoformat(),
            "direct_plan_evidence": {
                "scheme_id": scheme_id, "isin": isin, "plan": "Direct",
                "option": "Growth", "amc_name": "Example AMC",
                "benchmark": "Nifty 100 TRI", "reviewed_at": date.today().isoformat(),
                "source_document_sha256": f"{index:064x}",
            },
        })
    return candidates


def _complete_portfolio_context():
    as_of = date.today().isoformat()
    evidence_refs = {
        key: "sha256:" + key
        for key in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")
    }
    evidence_refs["as_of_dates"] = {
        key: as_of
        for key in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")
    }
    return {
        "evidence_attested_by_provider": True,
        "current_core_fund_count": 0,
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "assets": [
            {"asset_id": "cas-mf", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
             "value_inr": "125000", "source_ref": "sha256:cas", "owner_scope": "household", "as_of_date": as_of},
            {"asset_id": "mid", "asset_class": "equity", "saa_bucket": "mid_cap",
             "value_inr": "200000", "source_ref": "sha256:demat", "owner_scope": "household", "as_of_date": as_of,
             "constituent_weights": {"MID-ISSUER": 100}, "constituent_weights_coverage_pct": 100},
            {"asset_id": "small", "asset_class": "equity", "saa_bucket": "small_cap",
             "value_inr": "200000", "source_ref": "sha256:demat", "owner_scope": "household", "as_of_date": as_of,
             "constituent_weights": {"SMALL-ISSUER": 100}, "constituent_weights_coverage_pct": 100},
            {"asset_id": "flexi", "asset_class": "equity", "saa_bucket": "flexi_multi_cap",
             "value_inr": "175000", "source_ref": "sha256:demat", "owner_scope": "household", "as_of_date": as_of,
             "constituent_weights": {"FLEXI-ISSUER": 100}, "constituent_weights_coverage_pct": 100},
            {"asset_id": "debt", "asset_class": "deposit", "saa_bucket": "debt_liquid",
             "value_inr": "100000", "source_ref": "sha256:bank", "owner_scope": "household", "as_of_date": as_of},
            {"asset_id": "cash", "asset_class": "bank_cash", "saa_bucket": "debt_liquid",
             "value_inr": "200000", "source_ref": "sha256:bank", "owner_scope": "household", "as_of_date": as_of},
        ],
        "excluded_assets": [],
        "goal_policy": {
            "max_evidence_age_days": 30,
            "minimum_horizon_days_by_asset_class": {"equity": 3650},
        },
        "goals": [{
            "goal_id": "education", "mandate_approved": True, "source_ref": "sha256:goal",
            "evidence_as_of_date": as_of, "target_amount_inr": "2500000",
            "liabilities_inr": "100000", "target_date": f"{date.today().year + 11}-{date.today().month:02d}-{date.today().day:02d}",
            "asset_class": "equity", "approved_risk_profile": "Aggressive",
        }],
        "liquidity": {
            "verified_cash_inr": "200000", "approved_reserve_target_inr": "50000",
            "near_term_obligations_inr": "10000", "monthly_net_income_inr": "100000",
            "essential_monthly_expenses_inr": "40000", "monthly_debt_service_inr": "10000",
            "evidence_refs": evidence_refs, "max_evidence_age_days": 30,
        },
        "stress_scenarios": [{
            "scenario_id": "income-shock", "income_reduction_pct": "10",
            "expense_increase_pct": "5",
        }],
        "candidate_policy": {
            "max_evidence_age_days": 30,
            "mandatory_gates": [
                "direct_plan", "source_authenticity", "scheme_identity",
                "risk", "constituent_coverage", "operational",
            ],
            "candidate_sleeves": {f"CANDIDATE-{i}": "large_cap" for i in range(1, 31)},
            "rounding_increment_inr": "500",
        },
        "candidate_gate_results": {
            f"CANDIDATE-{i}": {
                "direct_plan": "PASS", "source_authenticity": "PASS",
                "scheme_identity": "PASS", "risk": "PASS",
                "constituent_coverage": "PASS", "operational": "PASS",
            } for i in range(1, 31)
        },
        "operational_evidence_by_candidate_id": {
            f"CANDIDATE-{i}": {
                "scheme_identity": {
                    "scheme_id": f"CANDIDATE-SCHEME-{i}", "isin": f"INF000000{i:03d}",
                    "plan": "Direct", "option": "Growth", "amc": "Example AMC",
                    "category": "Large Cap", "benchmark": "Nifty 100 TRI",
                },
                "evidence_ref": "sha256:ops", "evidence_as_of_date": as_of,
                "scheme_status": "ACTIVE", "minimum_monthly_sip_inr": "500",
                "exit_load_evidence_ref": "sha256:exit",
                "lockin_evidence_ref": "sha256:lock",
                "subscription_status_evidence_ref": "sha256:subscription",
            } for i in range(1, 31)
        },
        "ips": {
            "approved": True, "source_ref": "sha256:approved-ips",
            "effective_date": as_of,
            "target_weights_pct": {
                "large_cap": "20", "mid_cap": "25", "small_cap": "25",
                "flexi_multi_cap": "25", "debt_liquid": "5",
            },
            "tolerance_band_pct": "5",
            "tier6_equity_only_authorized": True,
        },
        "concentration_policy": {
            "max_issuer_pct_of_portfolio": "20",
            "max_sector_pct_of_portfolio": "100",
            "max_market_cap_pct_of_portfolio": "100",
            "max_theme_pct_of_portfolio": "100",
            "classification_as_of_date": as_of,
            "classification_source_ref": "sha256:issuer-classification",
            "issuer_classifications": {
                "ISSUER-A": {"sector": "Financials", "market_cap_bucket": "large_cap", "themes": ["value"]},
                "ISSUER-B": {"sector": "Financials", "market_cap_bucket": "large_cap", "themes": ["value"]},
                "ISSUER-C": {"sector": "Technology", "market_cap_bucket": "large_cap", "themes": ["digital"]},
                "MID-ISSUER": {"sector": "Industrials", "market_cap_bucket": "mid_cap", "themes": ["manufacturing"]},
                "SMALL-ISSUER": {"sector": "Healthcare", "market_cap_bucket": "small_cap", "themes": ["health"]},
                "FLEXI-ISSUER": {"sector": "Consumer", "market_cap_bucket": "large_cap", "themes": ["consumption"]},
            },
            "source_ref": "sha256:issuer-policy", "effective_date": as_of,
        },
        "freshness": {
            "recommendation_as_of_date": as_of, "max_age_days": 90,
            "event_flags": {"manager_change": False, "life_event": False},
        },
    }


def test_complete_portfolio_workflow_integrates_issues_23_to_34_without_authorizing_orders(
    tmp_path, monkeypatch
):
    args = _inputs(tmp_path)
    candidates = _candidate_universe()
    score_source = b"reviewed rank-score export for the integration case"
    score_ref = "sha256:" + hashlib.sha256(score_source).hexdigest()
    for candidate in candidates:
        candidate["rank_score_source_ref"] = score_ref
        candidate["rank_score_methodology_version"] = "risk-quality-v1"
    args["candidate_universe"] = candidates
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[SimpleNamespace(monthly_inr=10000)]),
    )

    metrics_source = b"reviewed original fund metrics"
    universe_source = b"reviewed original candidate universe"
    portfolio_source = b"reviewed original total portfolio context"
    result = service.recommend_sip(
        **args,
        portfolio_context=_complete_portfolio_context(),
        metrics_source_bytes=metrics_source,
        candidate_universe_source_bytes=universe_source,
        candidate_score_source_bytes=score_source,
        metrics_normalized_sha256="a" * 64,
        candidate_universe_normalized_sha256="b" * 64,
        portfolio_context_source_bytes=portfolio_source,
    )

    context = result["portfolio_assessment"]["total_portfolio_context"]
    assert context["status"] == "ASSESSMENT_COMPLETE"
    assert context["portfolio_reconciliation"]["total_value_inr"] == "1000000"
    assert context["cas_valuation_date_verified"] is True
    assert context["saa"]["drift"]["underweight_sleeves"] == ["flexi_multi_cap", "large_cap"]
    assert context["goal_suitability"]["status"] == "VALIDATED"
    assert context["liquidity_and_affordability"]["status"] == "AFFORDABLE"
    assert context["affordability_stress"]["all_scenarios_sustainable"] is True
    assert len(context["candidate_screening"]["eligible_candidate_ids"]) == 30
    assert context["scheme_operational_feasibility"]["CANDIDATE-1"]["status"] == "FEASIBLE_FOR_REVIEW"
    assert context["candidate_overlap_diagnostics"]["CANDIDATE-1"]["status"] == "ASSESSED"
    assert context["candidate_overlap_diagnostics"]["CANDIDATE-1"]["ticket_basis_inr"] == "1000"
    assert context["candidate_overlap_diagnostics"]["CANDIDATE-1"]["routed_sleeve_budget_inr"] == "3000"
    assert context["candidate_overlap_diagnostics"]["CANDIDATE-1"]["sector_market_cap_theme"]["status"] == "ASSESSED"
    assert context["candidate_level_sip_allocation_simulation"]["reconciliation_ok"] is True
    assert context["candidate_level_sip_allocation_simulation"]["allocated_budget_inr"] == "3000"
    assert context["candidate_level_sip_allocation_simulation"]["unallocated_budget_inr"] == "7000"
    assert context["candidate_level_sip_allocation_simulation"]["reconciliation_ok"] is True
    assert context["candidate_overlap_diagnostics"]["CANDIDATE-1"]["shared_issuers"] == ["ISSUER-A"]
    assert context["incremental_sip_routing_simulation"]["allocations_inr"] == {"large_cap": "5000"}
    assert context["freshness"]["status"] == "CURRENT"
    trace = result["portfolio_assessment"]["decision_trace"]
    trace_record = json.loads(trace["canonical_record"])
    assert trace_record["source_digests"]["metrics_source_sha256"] == hashlib.sha256(metrics_source).hexdigest()
    assert trace_record["source_digests"]["candidate_universe_source_sha256"] == hashlib.sha256(universe_source).hexdigest()
    assert trace_record["source_digests"]["candidate_score_source_sha256"] == hashlib.sha256(score_source).hexdigest()
    assert trace_record["source_digests"]["metrics_normalized_sha256"] == "a" * 64
    assert trace_record["source_digests"]["candidate_universe_normalized_sha256"] == "b" * 64
    assert trace_record["source_digests"]["portfolio_context_source_sha256"] == hashlib.sha256(portfolio_source).hexdigest()
    assert trace_record["as_of_dates"]["cas_valuation_date"] == date.today().isoformat()
    assert trace_record["portfolio_effect"]["candidate_level_allocation_simulation"]["reconciliation_ok"] is True
    assert trace_record["allocation"]["simulated_unallocated_budget_inr"] == "7000"
    assert trace_record["allocation"]["authorized_allocated_budget_inr"] == 0
    assert trace_record["allocation"]["simulated_allocated_budget_inr"] == "3000"
    assert len(trace_record["policy_source_sha256"]) == 64
    assert trace_record["eligibility"]["candidate_rank_evidence"]["CANDIDATE-1"]["rank_score"] == "1"
    assert trace_record["eligibility"]["candidate_rank_evidence"]["CANDIDATE-1"]["rank_score_methodology_version"] == "risk-quality-v1"
    assert result["portfolio_assessment"]["recommendation_lifecycle"]["state_persisted"] is False
    assert context["recommendation_authorized"] is False
    assert context["execution_authorized"] is False
    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_incomplete_total_portfolio_context_holds_and_keeps_budget_unallocated(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[]),
    )
    context = _complete_portfolio_context()
    context["perimeter_complete"] = False

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "HOLD"
    assert assessment["portfolio_reconciliation"]["reason"] == "PORTFOLIO_PERIMETER_NOT_ATTESTED"
    assert result["plan"]["unallocated_budget_inr"] == 10000
    assert result["plan"]["items"] == []


def test_client_declared_portfolio_context_never_passes_provider_provenance_gate(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[]),
    )
    context = _complete_portfolio_context()
    context["_client_supplied_unverified"] = True
    context["evidence_attested_by_provider"] = False

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["trust_level"] == "UNVERIFIED_CLIENT_DECLARATIONS"
    assert assessment["all_input_gates_pass"] is False
    assert assessment["status"] == "HOLD"
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_candidate_issuer_concentration_breach_blocks_portfolio_assessment(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    candidates = _candidate_universe()
    candidates[0]["constituent_weights"] = {"ISSUER-A": 100}
    args["candidate_universe"] = candidates
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[]),
    )
    context = _complete_portfolio_context()
    context["concentration_policy"]["max_issuer_pct_of_portfolio"] = "7"

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["candidate_overlap_diagnostics"]["CANDIDATE-1"]["status"] == "HOLD"
    assert "ISSUER-A" in assessment["candidate_overlap_diagnostics"]["CANDIDATE-1"]["breaching_issuers"]
    assert assessment["all_input_gates_pass"] is False
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_cas_asset_value_mismatch_blocks_total_portfolio_saa(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[]),
    )
    context = _complete_portfolio_context()
    context["assets"][0]["value_inr"] = "100000"

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "HOLD"
    assert "PORTFOLIO_CONTEXT_INVALID_OR_INCOMPLETE" in assessment["reason"]
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_candidate_universe_below_policy_minimum_never_enters_scoring(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", lambda **kwargs: SimpleNamespace(items=[]))

    result = service.recommend_sip(**args, portfolio_context=_complete_portfolio_context())

    screening = result["portfolio_assessment"]["total_portfolio_context"]["candidate_screening"]
    assert screening["status"] == "UNIVERSE_INSUFFICIENT"
    assert screening["universe_minimum"] == 30
    assert screening["universe_observed"] == 1
    assert screening["scoring_permitted"] is False
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_external_equity_without_lookthrough_blocks_portfolio_risk_clearance(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["candidate_universe"] = _candidate_universe()
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", lambda **kwargs: SimpleNamespace(items=[]))
    context = _complete_portfolio_context()
    context["assets"][1].pop("constituent_weights")

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["external_asset_lookthrough"]["status"] == "HOLD"
    assert assessment["external_asset_lookthrough"]["reason"] == "EXTERNAL_EQUITY_LOOKTHROUGH_MISSING"
    assert assessment["all_input_gates_pass"] is False
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_client_ips_cannot_exceed_risk_profile_equity_limit(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["candidate_universe"] = _candidate_universe()
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", lambda **kwargs: SimpleNamespace(items=[]))
    context = _complete_portfolio_context()
    context["ips"]["target_weights_pct"] = {
        "large_cap": "25", "mid_cap": "25", "small_cap": "25",
        "flexi_multi_cap": "25", "debt_liquid": "0",
    }

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "HOLD"
    assert "PORTFOLIO_CONTEXT_INVALID_OR_INCOMPLETE" in assessment["reason"]
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_goal_risk_profile_mismatch_blocks_sip_suitability(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["candidate_universe"] = _candidate_universe()
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", lambda **kwargs: SimpleNamespace(items=[]))
    context = _complete_portfolio_context()
    context["goals"][0]["approved_risk_profile"] = "Moderate"

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["goal_suitability"]["status"] == "HOLD"
    assert assessment["goal_suitability"]["reason"] == "GOAL_RISK_PROFILE_CONFLICT"
    assert assessment["all_input_gates_pass"] is False
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_sector_concentration_breach_blocks_candidate_even_when_issuer_cap_allows(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["candidate_universe"] = _candidate_universe()
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", lambda **kwargs: SimpleNamespace(items=[]))
    context = _complete_portfolio_context()
    context["concentration_policy"]["max_issuer_pct_of_portfolio"] = "100"
    context["concentration_policy"]["max_sector_pct_of_portfolio"] = "10"

    result = service.recommend_sip(**args, portfolio_context=context)

    candidate = result["portfolio_assessment"]["total_portfolio_context"]["candidate_overlap_diagnostics"]["CANDIDATE-1"]
    assert candidate["status"] == "HOLD"
    assert "Financials" in candidate["sector_market_cap_theme"]["breaches"]["sector"]
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_missing_issuer_classification_fails_closed_for_candidate_routing(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["candidate_universe"] = _candidate_universe()
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", lambda **kwargs: SimpleNamespace(items=[]))
    context = _complete_portfolio_context()
    context["concentration_policy"]["issuer_classifications"].pop("ISSUER-B")

    result = service.recommend_sip(**args, portfolio_context=context)

    candidate = result["portfolio_assessment"]["total_portfolio_context"]["candidate_overlap_diagnostics"]["CANDIDATE-1"]
    assert candidate["status"] == "HOLD"
    assert candidate["sector_market_cap_theme"]["reason"] == "ISSUER_CLASSIFICATION_MISSING_OR_INVALID"
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_service_persists_draft_lifecycle_snapshot_outside_checkout(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["candidate_universe"] = _candidate_universe()
    lifecycle_dir = tmp_path / "external-lifecycle"
    monkeypatch.setenv("MF_SIP_LIFECYCLE_DIR", str(lifecycle_dir))
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(service, "compute_deterministic_sip_blueprint", lambda **kwargs: SimpleNamespace(items=[]))

    result = service.recommend_sip(**args, portfolio_context=_complete_portfolio_context())

    lifecycle = result["portfolio_assessment"]["recommendation_lifecycle"]
    assert lifecycle["state"] == "DRAFT"
    assert lifecycle["state_persisted"] is True
    assert lifecycle["persistence_status"] == "RECORDED"
    record_path = lifecycle_dir / f"{lifecycle['decision_trace_sha256']}.json"
    assert record_path.is_file()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["execution_authorized"] is False
    assert set(record) == {
        "schema_version", "state", "decision_trace_sha256",
        "created_at", "execution_authorized",
    }


def test_combined_selected_funds_cannot_collectively_breach_sector_cap(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    candidates = _candidate_universe()
    args["candidate_universe"] = candidates
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[]),
    )
    context = _complete_portfolio_context()
    context["candidate_policy"]["candidate_sleeves"] = {
        f"CANDIDATE-{index}": (
            "large_cap" if index <= 15 else "flexi_multi_cap"
        )
        for index in range(1, 31)
    }
    context["concentration_policy"]["max_issuer_pct_of_portfolio"] = "100"
    context["concentration_policy"]["max_sector_pct_of_portfolio"] = "12.8"

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    individual = assessment["candidate_overlap_diagnostics"]["CANDIDATE-1"]
    combined = assessment["proposed_candidate_set_concentration"]
    allocation = assessment["candidate_level_sip_allocation_simulation"]
    assert individual["status"] == "ASSESSED", individual
    assert combined["status"] == "HOLD"
    assert float(combined["sector_market_cap_theme"]["breaches"]["sector"]["Financials"]) > 12.8
    assert allocation["status"] == "HOLD"
    assert allocation["allocated_budget_inr"] == "0"
    assert allocation["unallocated_budget_inr"] == "10000"
    assert allocation["reconciliation_ok"] is True
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 10000


def test_individual_concentration_uses_fund_minimum_and_combined_selection_uses_actual_allocations(tmp_path, monkeypatch):
    args = _inputs(tmp_path)
    args["candidate_universe"] = _candidate_universe()
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [_holding()])
    monkeypatch.setattr(
        service, "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[]),
    )
    context = _complete_portfolio_context()
    context["concentration_policy"]["max_issuer_pct_of_portfolio"] = "100"
    context["concentration_policy"]["max_sector_pct_of_portfolio"] = "12.8"
    context["candidate_policy"]["candidate_sleeves"] = {
        f"CANDIDATE-{index}": (
            "large_cap" if index <= 15 else "flexi_multi_cap"
        )
        for index in range(1, 31)
    }

    result = service.recommend_sip(**args, portfolio_context=context)

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    individual = assessment["candidate_overlap_diagnostics"]["CANDIDATE-1"]
    assert individual["status"] == "ASSESSED"
    assert individual["ticket_basis_inr"] == "1000"
    assert individual["routed_sleeve_budget_inr"] == "3000"
    allocation = assessment["candidate_level_sip_allocation_simulation"]
    assert allocation["reconciliation_ok"] is True
    assert Decimal(allocation["allocated_budget_inr"]) <= Decimal("10000")
    assert Decimal(allocation["unallocated_budget_inr"]) + Decimal(allocation["allocated_budget_inr"]) == Decimal("10000")
