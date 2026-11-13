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
            "mandate_signer_trust_registry_unavailable",
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
            "mandate_signer_trust_registry_unavailable",
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


def _valid_api_cas_for_publisher_review():
    from io import BytesIO
    import openpyxl
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", "12-Nov-2026"])
    sheet.append(["Name", "Test Investor"])
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append(["Example Fund Direct Growth", "FOLIO-1", 100000, 110000, 1000])
    sheet.append(["Second Fund Direct Growth", "FOLIO-2", 50000, 55000, 500])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_canonical_sip_upload_rejects_structurally_invalid_cas_before_provider(monkeypatch):
    called = []
    monkeypatch.setattr(sip, "load_sip_reviewer_trust_registry", lambda: {"schema_version": 1, "keys": [{"key_id": "sip"}]})
    monkeypatch.setattr(sip, "load_statement_publisher_trust_registry", lambda: None)
    client = TestClient(sip.create_sip_app(evidence_provider=lambda **kwargs: called.append(kwargs)))
    response = _upload(client, cas_bytes=b"not an xlsx workbook", monthly_budget_inr="25000", risk_profile="Aggressive")
    assert response.status_code == 422
    assert response.json()["decision"] == "NO_ACTION"
    assert called == []


def test_canonical_sip_upload_verifies_signed_independent_statement_review(monkeypatch):
    import hashlib
    from datetime import datetime, timezone, timedelta
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from services.sip_reviewer_approval import _b64url_encode, create_sip_reviewer_approval_envelope

    raw = _valid_api_cas_for_publisher_review()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    trust = {"schema_version": 1, "keys": [{
        "key_id": "statement-review-key", "reviewer_id": "independent-reviewer",
        "reviewer_role": "independent", "public_key": _b64url_encode(public_key),
        "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-12-31T23:59:59Z",
        "revoked": False,
    }]}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    verified_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    records = {
        "document_type": "CAS_EXCEL", "publisher": "CAMS",
        "verification_method": "INDEPENDENT_REVIEW", "verified_at": verified_at,
        "evidence_reference": "review-ticket:CAS-API-001", "source_url": "https://www.camsonline.com/",
    }
    approval = create_sip_reviewer_approval_envelope(
        private_key, key_id="statement-review-key", reviewer_id="independent-reviewer",
        scope="STATEMENT_PUBLISHER_AUTHENTICATION", source_bytes=raw,
        structured_records=records, issued_at=now, expires_at=now + timedelta(days=30),
        publisher="CAMS", verification_method="INDEPENDENT_REVIEW", verified_at=verified_at,
        evidence_reference="review-ticket:CAS-API-001", source_url="https://www.camsonline.com/",
    )
    monkeypatch.setattr(sip, "load_sip_reviewer_trust_registry", lambda: {"schema_version": 1, "keys": [{"key_id": "sip"}]})
    monkeypatch.setattr(sip, "load_statement_publisher_trust_registry", lambda: trust)
    monkeypatch.setattr(sip, "validate_evidence_provider_payload", lambda payload, **kwargs: {
        "metrics_path": Path(__file__), "aliases_path": None, "scheme_master": {},
        "scheme_master_source_bytes": b"master", "portfolio_disclosures_by_scheme_id": {},
        "portfolio_disclosure_source_bytes_by_scheme_id": {}, "disclosure_as_of_date": date(2026, 11, 12),
        "candidate_universe": [],
        # A generic reviewer-attested portfolio document must not become
        # provider-authenticated SIP mandate evidence at the API boundary.
        "portfolio_context": {"sip_mandate_evidence": {"coverage_status": "COMPLETE", "mandates": []}},
        "portfolio_context_source_metadata": {"source_document_sha256": "a" * 64},
        "portfolio_context_source_bytes": b"reviewer-attested portfolio context",
    })
    captured = {}
    def service(**kwargs):
        captured.update(kwargs)
        return {"status": "HOLD", "decision": "NO_ACTION", "unallocated_budget_inr": "25000.00"}
    monkeypatch.setattr(sip, "recommend_sip", service)
    client = TestClient(sip.create_sip_app(evidence_provider=lambda **kwargs: {}))
    response = client.post(
        "/v1/sip/recommendations",
        files={"cas_file": ("portfolio.xlsx", raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"monthly_budget_inr": "25000", "risk_profile": "Aggressive",
              "statement_publisher_approval_json": json.dumps(approval)},
    )
    assert response.status_code == 200
    provenance = response.json()["statement_provenance"]
    assert provenance["is_publisher_authenticated"] is True
    assert provenance["authenticated_publisher"] == "CAMS"
    assert provenance["publisher_authenticity_status"] == "AUTHENTICATED_SOURCE"
    assert captured["statement_provenance"] == provenance
    assert captured["portfolio_context"]["evidence_attested_by_provider"] is False
    assert captured["portfolio_context"]["_source_bundle_sha256"] == "a" * 64
    assert hashlib.sha256(raw).hexdigest() == provenance["source_sha256"]

    # A structurally valid upload without a signed reviewer envelope must not
    # inherit the publisher claim from workbook text or the configured trust root.
    unverified = client.post(
        "/v1/sip/recommendations",
        files={"cas_file": ("portfolio.xlsx", raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"monthly_budget_inr": "25000", "risk_profile": "Aggressive"},
    )
    unverified_provenance = unverified.json()["statement_provenance"]
    assert unverified_provenance["is_publisher_authenticated"] is False
    assert unverified_provenance["authenticated_publisher"] is None
    assert unverified_provenance["rta_source"] == "Unknown"
    assert unverified_provenance["publisher_authenticity_status"] == "UNVERIFIED"


def test_authenticated_cas_policy_holds_before_provider_without_signed_review(monkeypatch):
    called = []
    monkeypatch.setattr(sip, "load_sip_reviewer_trust_registry", lambda: {"schema_version": 1, "keys": [{"key_id": "sip"}]})
    monkeypatch.setattr(sip, "load_statement_publisher_trust_registry", lambda: None)
    client = TestClient(sip.create_sip_app(
        evidence_provider=lambda **kwargs: called.append(kwargs),
        require_authenticated_cas=True,
    ))
    response = _upload(
        client, cas_bytes=_valid_api_cas_for_publisher_review(),
        monthly_budget_inr="25000", risk_profile="Aggressive",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HOLD"
    assert body["decision"] == "NO_ACTION"
    assert body["unallocated_budget_inr"] == "25000.00"
    assert body["statement_provenance"]["publisher_authenticity_status"] == "UNVERIFIED"
    assert called == []


def test_production_defaults_to_requiring_authenticated_cas(monkeypatch):
    monkeypatch.setenv("MF_DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.delenv("MF_SIP_REQUIRE_AUTHENTICATED_CAS", raising=False)
    status = TestClient(sip.create_sip_app()).get("/v1/deployment/status").json()
    assert status["authenticated_cas_required"] is True


def test_api_derives_provider_attestation_only_from_mandate_signature_verification(monkeypatch):
    """A generic reviewer-approved context cannot self-assert mandate authentication."""
    from decimal import Decimal

    monkeypatch.setattr(
        sip, "validate_evidence_provider_payload",
        lambda payload, **kwargs: payload,
    )
    verification_results = iter((True, False))
    monkeypatch.setattr(
        sip, "_verify_provider_mandate_schedule",
        lambda context: next(verification_results),
    )
    observed_contexts = []

    def provider(**kwargs):
        return {
            "metrics_path": Path(__file__),
            "aliases_path": None,
            "scheme_master": {},
            "scheme_master_source_bytes": b"scheme-master",
            "portfolio_disclosures_by_scheme_id": {},
            "portfolio_disclosure_source_bytes_by_scheme_id": {},
            "disclosure_as_of_date": date.today(),
            "candidate_universe": [],
            "portfolio_context": {
                "as_of_date": date.today().isoformat(),
                "investor_owner_ref": "investor-1",
                "sip_mandate_evidence": {"coverage_status": "COMPLETE"},
                # An upstream boolean must never override cryptographic verification.
                "evidence_attested_by_provider": True,
            },
            "portfolio_context_source_metadata": {
                "source_document_sha256": "a" * 64,
            },
            "portfolio_context_source_bytes": b"reviewed-portfolio-context",
        }

    def capture_service_inputs(**kwargs):
        observed_contexts.append(kwargs["portfolio_context"])
        return {
            "status": "HOLD",
            "decision": "NO_ACTION",
            "unallocated_budget_inr": str(Decimal(kwargs["monthly_budget_inr"])),
        }

    monkeypatch.setattr(sip, "recommend_sip", capture_service_inputs)
    client = TestClient(sip.create_sip_app(
        evidence_provider=provider,
        require_authenticated_cas=False,
    ))

    for expected in (True, False):
        response = _upload(
            client,
            cas_bytes=_valid_cas_bytes(date.today()),
            monthly_budget_inr="10000",
            risk_profile="Moderate",
        )
        assert response.status_code == 200
        assert observed_contexts[-1]["evidence_attested_by_provider"] is expected
        assert observed_contexts[-1]["mandate_evidence_signature_verified"] is expected

    # The provider's cached source object was not mutated by request handling.
    original = provider()
    assert original["portfolio_context"]["evidence_attested_by_provider"] is True


def test_provider_mandate_verification_rejects_incomplete_or_invalid_context(monkeypatch):
    calls = []
    import services.sip_mandate_auth as mandate_auth

    def verified(evidence, *, owner_ref, as_of):
        calls.append((evidence, owner_ref, as_of))
        return {"status": "VERIFIED"}

    monkeypatch.setattr(mandate_auth, "verify_mandate_schedule", verified)
    context = {
        "as_of_date": "2026-11-13",
        "investor_owner_ref": "investor-1",
        "sip_mandate_evidence": {"coverage_status": "COMPLETE"},
    }
    assert sip._verify_provider_mandate_schedule(context) is True
    assert calls[-1][1:] == ("investor-1", date(2026, 11, 13))

    incomplete = dict(context)
    incomplete["sip_mandate_evidence"] = {"coverage_status": "PARTIAL"}
    assert sip._verify_provider_mandate_schedule(incomplete) is False
    assert len(calls) == 1

    monkeypatch.setattr(
        mandate_auth, "verify_mandate_schedule",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("invalid signature")),
    )
    assert sip._verify_provider_mandate_schedule(context) is False
