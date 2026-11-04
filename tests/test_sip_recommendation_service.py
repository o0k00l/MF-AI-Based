from datetime import date
from pathlib import Path
from types import SimpleNamespace

from services import sip_recommendation as service


def _holding():
    return SimpleNamespace(
        scheme="Example Direct Growth",
        fund_id="FUND-1",
        scheme_id="SCHEME-1",
        lookthrough_status="VERIFIED",
        metrics_status="VERIFIED",
        constituent_weights={"ISSUER-A": 60.0, "ISSUER-B": 40.0},
        equity_pct=100.0,
        constituent_weights_coverage_pct=100.0,
        current_value_inr=125000.0,
    )


def _inputs(tmp_path):
    cas = tmp_path / "cas.xlsx"
    cas.write_bytes(b"synthetic CAS")
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
        "disclosure_as_of_date": date(2026, 11, 4),
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
