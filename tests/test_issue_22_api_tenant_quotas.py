"""
tests/test_issue_22_api_tenant_quotas.py - Acceptance tests for Issue #22.
Internal engineering for API authentication, tenant isolation, quotas, and deployment controls.
"""
from __future__ import annotations

import io
import json
import pytest
from starlette.testclient import TestClient

from api import sip


def _sample_xlsx_bytes() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["To Date", "2026-10-31"])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Test Scheme Direct", "12345", 10000, 12000, 100])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_api_security_headers_and_deployment_status():
    app = sip.create_sip_app(evidence_provider=lambda **kwargs: {})
    client = TestClient(app)

    # 1. Deployment status endpoint
    resp = client.get("/v1/deployment/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "deployment_environment" in data
    assert "auth_enforced" in data
    assert "quota_management_active" in data

    # 2. Security headers on responses
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Strict-Transport-Security" in resp.headers


def test_api_tenant_quotas_and_rate_limiting():
    registry = {
        "tenant-key-1": {
            "tenant_id": "tenant-alpha",
            "authorized_client_ids": ["client-alpha"],
            "rate_limit_per_minute": 2,
        },
        "tenant-key-2": {
            "tenant_id": "tenant-beta",
            "authorized_client_ids": ["client-beta"],
            "rate_limit_per_minute": 5,
        },
    }
    app = sip.create_sip_app(
        evidence_provider=lambda **kwargs: {},
        api_key_registry=registry,
        require_auth=True,
    )
    client = TestClient(app)

    # Tenant alpha: 2 requests allowed
    for _ in range(2):
        resp = client.post(
            "/v1/sip/recommendations",
            headers={"X-API-Key": "tenant-key-1", "X-Client-Id": "client-alpha"},
            data={"monthly_budget_inr": 10000, "risk_profile": "Moderate"},
            files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert resp.status_code in (200, 422)

    # Tenant alpha 3rd request -> 429 Quota Exceeded
    resp_quota = client.post(
        "/v1/sip/recommendations",
        headers={"X-API-Key": "tenant-key-1", "X-Client-Id": "client-alpha"},
        data={"monthly_budget_inr": 10000, "risk_profile": "Moderate"},
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_quota.status_code == 429
    assert any("quota exceeded" in r.lower() for r in resp_quota.json()["reasons"])
    assert "retry_after_seconds" in resp_quota.json()

    # Tenant beta has separate isolated quota: still succeeds
    resp_beta = client.post(
        "/v1/sip/recommendations",
        headers={"X-API-Key": "tenant-key-2", "X-Client-Id": "client-beta"},
        data={"monthly_budget_inr": 10000, "risk_profile": "Moderate"},
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_beta.status_code in (200, 422)


def test_api_custom_saa_profile_validation():
    app = sip.create_sip_app(evidence_provider=lambda **kwargs: {})
    client = TestClient(app)

    # Custom profile without custom_saa_target fails closed with 422
    resp_no_target = client.post(
        "/v1/sip/recommendations",
        data={"monthly_budget_inr": 10000, "risk_profile": "Custom"},
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_no_target.status_code == 422
    assert any("Custom SAA is not implemented" in r for r in resp_no_target.json()["reasons"])

    # Custom profile with malformed custom_saa_target fails closed with 422
    bad_context = json.dumps({"custom_saa_target": {"equity_pct": 150.0}})
    resp_bad = client.post(
        "/v1/sip/recommendations",
        data={
            "monthly_budget_inr": 10000,
            "risk_profile": "Custom",
            "portfolio_context_json": bad_context,
        },
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_bad.status_code == 422
    assert any("Invalid custom_saa_target" in r for r in resp_bad.json()["reasons"])
