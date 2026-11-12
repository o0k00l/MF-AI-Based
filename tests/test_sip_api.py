import json
import os
from datetime import date
from pathlib import Path

# Set test environment before importing api.sip
# This ensures auth is not enforced by default in tests
os.environ.setdefault("MF_DEPLOYMENT_ENVIRONMENT", "test")

from fastapi.testclient import TestClient

from api import sip


def _upload(client, *, cas_bytes=b"synthetic cas bytes", **data):
    return client.post(
        "/v1/sip/recommendations",
        files={"cas_file": ("portfolio.xlsx", cas_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data=data,
    )


def _valid_cas_bytes(as_of_date):
    from io import BytesIO
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", as_of_date.strftime("%d-%b-%Y")])
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append(["Example Direct Growth", "FOLIO-1", 100000, 125000, 1000])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_readiness_distinguishes_live_api_from_missing_evidence_provider():
    client = TestClient(sip.create_sip_app())
    assert client.get("/health").json()["status"] == "ok"
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "not_ready",
        "service": "sip-decision-support",
        "checks": {"evidence_provider": "not_configured"},
        "evidence_validation_available": False,
        "recommendations_enabled": False,
        "release_blockers": [
            "evidence_provider_not_configured",
            "authenticated_daily_tri_unavailable",
            "independent_nse_calendar_unavailable",
            "research_release_approval_missing",
        ],
    }


def test_configured_provider_only_enables_evidence_validation_not_recommendations():
    client = TestClient(sip.create_sip_app(evidence_provider=lambda **kwargs: {}))
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "not_ready",
        "service": "sip-decision-support",
        "checks": {
            "evidence_provider": "configured",
            "independent_reviewer_trust_registry": "missing_or_invalid",
        },
        "evidence_validation_available": False,
        "recommendations_enabled": False,
        "release_blockers": [
            "independent_reviewer_trust_registry_unavailable",
            "authenticated_daily_tri_unavailable",
            "independent_nse_calendar_unavailable",
            "research_release_approval_missing",
        ],
    }


def test_api_without_evidence_provider_returns_hold_and_full_budget():
    client = TestClient(sip.create_sip_app())

    response = _upload(
        client,
        monthly_budget_inr="25000",
        risk_profile="Aggressive",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HOLD"
    assert body["decision"] == "NO_ACTION"
    assert body["unallocated_budget_inr"] == "25000.00"


def test_api_passes_temporary_cas_to_evidence_provider_and_removes_it(monkeypatch):
    seen = {}

    def provider(**kwargs):
        seen["path"] = kwargs["cas_path"]
        assert kwargs["cas_path"].is_file()
        assert kwargs["cas_path"].read_bytes() == b"synthetic cas bytes"
        return {
            "metrics_path": Path(__file__),
            "aliases_path": None,
            "scheme_master": {
                "status": "VERIFIED",
                "source_url": "https://amfiindia.com/source",
                "source_document_sha256": __import__("hashlib").sha256(b"master bytes").hexdigest(),
                "reviewer_attested": True,
                "effective_date": "2026-11-01",
                "source_type": "OFFICIAL_SCHEME_MASTER",
                "schemes": [{
                    "scheme_id": "scheme-1", "isin": "INF000000001",
                    "scheme_name": "Example Direct Growth", "amc_name": "Example AMC",
                    "category": "Flexi Cap", "benchmark_identity": "Nifty 500 TRI",
                    "scheme_structure": "Open Ended",
                    "plan_type": "Direct", "option_type": "Growth", "riskometer_score": 5,
                }],
            },
            "scheme_master_source_bytes": b"master bytes",
            "portfolio_disclosures_by_scheme_id": {},
            "portfolio_disclosure_source_bytes_by_scheme_id": {},
            "disclosure_as_of_date": date(2026, 11, 4),
            "candidate_universe": [{
                "fund_id": "fund-1", "fund_name": "Example Direct Growth",
                "scheme_id": "scheme-1", "isin": "INF000000001",
                "amc_name": "Example AMC", "category": "Flexi Cap",
                "benchmark_identity": "Nifty 500 TRI",
                "scheme_structure": "Open Ended",
                    "plan_type": "Direct", "option_type": "Growth", "riskometer_score": 5,
                "is_direct": True,
                "_evidence_root": str(Path(__file__).parent),
                "direct_plan_evidence": {
                    "source_file": Path(__file__).name,
                    "source_document_sha256": __import__("hashlib").sha256(Path(__file__).read_bytes()).hexdigest(),
                    "source_url": "https://amfiindia.com/direct.pdf",
                    "source_type": "AMC_FACTSHEET",
                    "reviewer_attested": True,
                    "plan": "Direct",
                    "scheme_name": "Example Direct Growth",
                    "scheme_id": "scheme-1",
                    "isin": "INF000000001",
                    "amc_name": "Example AMC",
                    "reviewed_at": date.today().isoformat(),
                },
            }],
            "candidate_universe_source": {
                "source_url": "https://amfiindia.com/candidates",
                "source_document_sha256": __import__("hashlib").sha256(b"candidate bytes").hexdigest(),
                "reviewer_attested": True,
                "effective_date": "2026-11-01",
                "source_type": "REVIEWED_CANDIDATE_UNIVERSE",
                "universe_complete": True,
                "coverage_scope": "Synthetic API test universe",
            },
            "candidate_universe_source_bytes": b"candidate bytes",
        }

    def strict_service_contract(
        *,
        cas_path,
        metrics_path,
        aliases_path,
        monthly_budget_inr,
        risk_profile,
        scheme_master,
        scheme_master_source_bytes,
        portfolio_disclosures_by_scheme_id,
        portfolio_disclosure_source_bytes_by_scheme_id,
        disclosure_as_of_date,
        candidate_universe,
        portfolio_context=None,
    ):
        assert cas_path.is_file()
        assert metrics_path == Path(__file__)
        assert risk_profile == "Moderate"
        assert candidate_universe[0]["is_direct"] is True
        assert portfolio_context == {
            "as_of_date": date.today().isoformat(),
            "perimeter_complete": False,
            "_client_supplied_unverified": True,
        }
        return {
            "status": "HOLD",
            "decision": "NO_ACTION",
            "reasons": ["Synthetic API integration test."],
            "unallocated_budget_inr": monthly_budget_inr,
        }

    monkeypatch.setattr(sip, "recommend_sip", strict_service_contract)
    client = TestClient(sip.create_sip_app(evidence_provider=provider))

    response = _upload(
        client,
        monthly_budget_inr="15000",
        risk_profile="Moderate",
        portfolio_context_json='{"as_of_date":"' + date.today().isoformat() + '","perimeter_complete":false}',
    )

    assert response.status_code == 200
    assert response.json()["status"] == "HOLD"
    assert response.json()["unallocated_budget_inr"] == "15000.00"
    assert seen == {}  # Unauthenticated evidence must not reach the engine.
    assert "Independent reviewer trust registry" in response.json()["reasons"][0]


def test_api_rejects_non_xlsx_without_invoking_provider():
    called = []
    client = TestClient(sip.create_sip_app(evidence_provider=lambda **kwargs: called.append(kwargs)))

    response = client.post(
        "/v1/sip/recommendations",
        files={"cas_file": ("portfolio.pdf", b"not xlsx", "application/pdf")},
        data={"monthly_budget_inr": "10000", "risk_profile": "Aggressive"},
    )

    assert response.status_code == 415
    assert response.json()["decision"] == "NO_ACTION"
    assert called == []


def test_api_rejects_provider_override_of_user_request(monkeypatch):
    client = TestClient(
        sip.create_sip_app(
            evidence_provider=lambda **kwargs: {
                "cas_path": Path("/tmp/attacker.xlsx"),
                "metrics_path": None,
            }
        )
    )
    monkeypatch.setattr(
        sip,
        "recommend_sip",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Must not call service")),
    )

    response = _upload(
        client,
        monthly_budget_inr="12000",
        risk_profile="Conservative",
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "NO_ACTION"
    assert "Independent reviewer trust registry" in response.json()["reasons"][0]


def test_api_real_service_ingests_cas_and_holds_on_missing_portfolio_disclosure(tmp_path):
    import hashlib
    from io import BytesIO

    import openpyxl

    scheme_name = "Example Equity Fund - Direct Plan - Growth"
    amc_name = "Example AMC"
    scheme_id = "scheme-api-e2e"
    isin = "INF000000002"
    as_of = date.today()

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["Synthetic CAS"])
    sheet.append(["To Date", as_of.strftime("%d-%b-%Y")])
    sheet.append([
        "Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units", "AMC Name"
    ])
    sheet.append([scheme_name, "FOLIO-E2E", 90000.0, 100000.0, 1000.0, amc_name])
    stream = BytesIO()
    workbook.save(stream)
    cas_bytes = stream.getvalue()

    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps({"funds": [{
        "id": "fund-api-e2e", "scheme": scheme_name, "name": scheme_name,
        "scheme_id": scheme_id, "isin": isin,
        "cat": "Flexi Cap", "er": 0.65, "eq": 100.0, "debt": 0.0,
        "lc": 50.0, "mc": 30.0, "sc": 20.0, "h": [],
    }]}), encoding="utf-8")
    direct_source = Path(__file__)
    direct_bytes = direct_source.read_bytes()
    master_bytes = b"synthetic scheme master bytes"
    candidate_bytes = b"synthetic candidate universe bytes"

    def source_metadata(raw, url, source_type):
        return {
            "source_url": url,
            "source_document_sha256": hashlib.sha256(raw).hexdigest(),
            "reviewer_attested": True,
            "effective_date": as_of.isoformat(),
            "source_type": source_type,
        }

    def provider(*, cas_path, monthly_budget_inr, risk_profile):
        assert cas_path.is_file()
        assert cas_path.read_bytes() == cas_bytes
        candidate = {
            "fund_id": "fund-api-e2e",
            "fund_name": scheme_name,
            "scheme_id": scheme_id,
            "isin": isin,
            "amc_name": amc_name,
            "category": "Flexi Cap",
            "benchmark_identity": "Nifty 500 TRI",
            "scheme_structure": "Open Ended",
                    "plan_type": "Direct", "option_type": "Growth",
            "riskometer_score": 5,
            "is_direct": True,
            "_evidence_root": str(direct_source.parent),
            "direct_plan_evidence": {
                "source_file": direct_source.name,
                "source_document_sha256": hashlib.sha256(direct_bytes).hexdigest(),
                "source_url": "https://amfiindia.com/example-direct-factsheet.pdf",
                "source_type": "AMC_FACTSHEET",
                "reviewer_attested": True,
                "plan": "Direct",
                "scheme_name": scheme_name,
                "scheme_id": scheme_id,
                "isin": isin,
                "amc_name": amc_name,
                "reviewed_at": as_of.isoformat(),
            },
        }
        return {
            "metrics_path": metrics_path,
            "aliases_path": None,
            "metrics_source_metadata": {
                **source_metadata(
                    b"synthetic metrics source bytes",
                    "https://amfiindia.com/example-fund-metrics",
                    "OFFICIAL_FUND_METRICS",
                ),
                "normalized_metrics_sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
            },
            "metrics_source_bytes": b"synthetic metrics source bytes",
            "scheme_master": {
                "status": "VERIFIED",
                "schemes": [{
                    "scheme_id": scheme_id,
                    "isin": isin,
                    "scheme_name": scheme_name,
                    "amc_name": amc_name,
                    "category": "Flexi Cap",
                    "benchmark_identity": "Nifty 500 TRI",
                    "scheme_structure": "Open Ended",
                    "plan_type": "Direct", "option_type": "Growth",
                    "riskometer_score": 5,
                }],
                **source_metadata(master_bytes, "https://amfiindia.com/example-scheme-master", "OFFICIAL_SCHEME_MASTER"),
            },
            "scheme_master_source_bytes": master_bytes,
            "portfolio_disclosures_by_scheme_id": {},
            "portfolio_disclosure_source_bytes_by_scheme_id": {},
            "disclosure_as_of_date": as_of,
            "candidate_universe": [candidate],
            "candidate_universe_source": {
                **source_metadata(candidate_bytes, "https://amfiindia.com/example-candidate-universe", "REVIEWED_CANDIDATE_UNIVERSE"),
                "universe_complete": True,
                "coverage_scope": "Synthetic single-scheme test fixture",
            },
            "candidate_universe_source_bytes": candidate_bytes,
        }

    client = TestClient(sip.create_sip_app(evidence_provider=provider))
    response = client.post(
        "/v1/sip/recommendations",
        files={"cas_file": ("portfolio.xlsx", cas_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"monthly_budget_inr": "25000", "risk_profile": "Aggressive"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HOLD"
    assert body["decision"] == "NO_ACTION"
    assert body["unallocated_budget_inr"] == "25000.00"
    assert "Independent reviewer trust registry" in body["reasons"][0]


def test_api_runs_portfolio_saa_diagnostic_end_to_end_and_keeps_budget_on_hold(monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from services import sip_recommendation as service

    as_of = date.today()
    source_bytes = b"synthetic source"
    candidate_source_bytes = b"synthetic candidate universe"
    metrics_source_bytes = b"reviewed fund metrics source"
    rank_score_source_bytes = b"reviewed candidate ranking scores"
    category_anchor_source_bytes = b"approved large-cap benchmark anchor source"

    def metadata(raw, url, source_type):
        return {
            "source_url": url,
            "source_document_sha256": hashlib.sha256(raw).hexdigest(),
            "reviewer_attested": True,
            "effective_date": as_of.isoformat(),
            "source_type": source_type,
        }

    candidate_bytes = Path(__file__).read_bytes()
    candidate = {
        "fund_id": "fund-api-saa",
        "fund_name": "Example Direct Growth",
        "scheme_id": "scheme-api-saa",
        "isin": "INF000000003",
        "amc_name": "Example AMC",
        "category": "Large Cap",
        "benchmark_identity": "Nifty 100 TRI",
        "scheme_structure": "Open Ended",
                    "plan_type": "Direct", "option_type": "Growth",
        "riskometer_score": 5,
        "is_direct": True,
        "_evidence_root": str(Path(__file__).parent),
        "direct_plan_evidence": {
            "source_file": Path(__file__).name,
            "source_document_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "source_url": "https://amfiindia.com/example-direct-factsheet.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Example Direct Growth",
            "scheme_id": "scheme-api-saa",
            "isin": "INF000000003",
            "amc_name": "Example AMC",
            "reviewed_at": as_of.isoformat(),
        },
        "rank_score": "3.25",
        "rank_score_source_ref": "sha256:" + hashlib.sha256(rank_score_source_bytes).hexdigest(),
        "rank_score_as_of_date": as_of.isoformat(),
        "rank_score_methodology_version": "risk-quality-v1",
        "rank_score_scope": "PORTFOLIO_AWARE",
        "rank_score_portfolio_overlap_status": "VERIFIED",
        "rank_score_portfolio_overlap_pct": "18.5",
        "rank_score_portfolio_overlap_coverage_pct": "99.8",
        "rank_score_portfolio_overlap_source_ref": "sha256:" + hashlib.sha256(b"portfolio overlap source").hexdigest(),
        "rank_score_category_anchor_source_ref": "sha256:" + hashlib.sha256(category_anchor_source_bytes).hexdigest(),
        "rank_score_category_anchor_policy_version": "category-anchor-v1",
        "rank_score_benchmark_identity": "Nifty 100 TRI",
    }
    provider = lambda **kwargs: {
        "metrics_path": Path(__file__),
        "aliases_path": None,
        "scheme_master": {
            "status": "VERIFIED",
            "schemes": [{
                "scheme_id": "scheme-api-saa",
                "isin": "INF000000003",
                "scheme_name": "Example Direct Growth",
                "amc_name": "Example AMC",
                "category": "Large Cap",
                "benchmark_identity": "Nifty 100 TRI",
                "scheme_structure": "Open Ended",
                    "plan_type": "Direct", "option_type": "Growth",
                "riskometer_score": 5,
                "plan_type": "Direct",
                "option_type": "Growth",
            }],
            **metadata(source_bytes, "https://amfiindia.com/scheme-master", "OFFICIAL_SCHEME_MASTER"),
        },
        "scheme_master_source_bytes": source_bytes,
        "portfolio_disclosures_by_scheme_id": {},
        "portfolio_disclosure_source_bytes_by_scheme_id": {},
        "disclosure_as_of_date": as_of,
        "candidate_universe": [candidate],
        "candidate_universe_source": {
            **metadata(candidate_source_bytes, "https://amfiindia.com/candidates", "REVIEWED_CANDIDATE_UNIVERSE"),
            "universe_complete": True,
            "coverage_scope": "Synthetic API integration fixture",
            "normalized_candidate_universe_sha256": hashlib.sha256(
                __import__("json").dumps([candidate], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        "candidate_universe_source_bytes": candidate_source_bytes,
        "candidate_score_source_metadata": {
            **metadata(rank_score_source_bytes, "https://amfiindia.com/ranking-scores", "REVIEWED_CANDIDATE_RANKING"),
            "methodology_version": "risk-quality-v1",
            "score_scope": "PORTFOLIO_AWARE",
            "missing_overlap_policy": "BLOCK_SCORE",
        },
        "candidate_score_source_bytes": rank_score_source_bytes,
        "category_anchor_source_metadata": {
            **metadata(category_anchor_source_bytes, "https://amfiindia.com/benchmark-anchors", "APPROVED_CATEGORY_BENCHMARK_ANCHORS"),
            "reviewer_id": "independent-reviewer",
            "policy_version": "category-anchor-v1",
            "category_anchors": {
                "Large Cap": {
                    "status": "APPROVED",
                    "benchmark_identity": "Nifty 100 TRI",
                    "reviewer_id": "independent-reviewer",
                    "policy_version": "category-anchor-v1",
                    "effective_date": as_of.isoformat(),
                    "anchor_set": {
                        "alpha": [0, 5], "ret1y": [0, 30], "sharpe": [0.2, 1.0],
                        "ter": [0.1, 1.0], "buffer": [0, 15], "intl": [0, 10],
                        "overlap": [0, 100],
                    },
                }
            },
        },
        "category_anchor_source_bytes": category_anchor_source_bytes,
        "metrics_source_metadata": {
            **metadata(metrics_source_bytes, "https://amfiindia.com/fund-metrics", "OFFICIAL_FUND_METRICS"),
            "normalized_metrics_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "metrics_source_bytes": metrics_source_bytes,
    }

    holding = SimpleNamespace(
        scheme="Example Direct Growth",
        fund_id="FUND-API-SAA",
        scheme_id="scheme-api-saa",
        lookthrough_status="VERIFIED",
        metrics_status="VERIFIED",
        plan_option_status="VERIFIED",
        option_type="GROWTH",
        is_direct=True,
        constituent_weights_coverage_pct=100.0,
        current_value_inr=125000.0,
        asset_class="Large_Cap",
        equity_pct=100.0,
        constituent_weights={"ISSUER-A": 60.0, "ISSUER-B": 40.0},
    )
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *a, **k: [holding])
    monkeypatch.setattr(
        service,
        "compute_deterministic_sip_blueprint",
        lambda **kwargs: SimpleNamespace(items=[SimpleNamespace(monthly_inr=10000)]),
    )

    client = TestClient(sip.create_sip_app(evidence_provider=provider))
    response = _upload(
        client,
        cas_bytes=_valid_cas_bytes(date.today()),
        monthly_budget_inr="10000",
        risk_profile="Aggressive",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HOLD"
    assert body["decision"] == "NO_ACTION"
    assert body["unallocated_budget_inr"] == "10000.00"
    assert "Independent reviewer trust registry" in body["reasons"][0]


def test_api_rejects_malformed_portfolio_context_before_calling_provider():
    called = []
    client = TestClient(sip.create_sip_app(evidence_provider=lambda **kwargs: called.append(kwargs)))
    response = _upload(
        client, monthly_budget_inr="10000", risk_profile="Moderate",
        portfolio_context_json="{not-json",
    )
    assert response.status_code == 422
    assert response.json()["decision"] == "NO_ACTION"


def test_api_rejects_custom_until_custom_saa_contract_is_implemented():
    called = []
    client = TestClient(
        sip.create_sip_app(evidence_provider=lambda **kwargs: called.append(kwargs))
    )

    response = _upload(
        client,
        monthly_budget_inr="25000",
        risk_profile="Custom",
    )

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "HOLD"
    assert body["decision"] == "NO_ACTION"
    assert body["unallocated_budget_inr"] == "25000.00"
    assert any("Custom SAA is not implemented" in reason for reason in body["reasons"])
    assert called == []
