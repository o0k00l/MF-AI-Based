"""
Unit tests for SIP API authentication, authorization, and client scope boundaries.
Addresses Issue #22: Resolve AI provider authentication and define production deployment target.
"""
from __future__ import annotations

import io
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


def test_api_rejects_unauthenticated_requests_when_auth_required():
    app = sip.create_sip_app(
        evidence_provider=lambda **kwargs: {},
        require_auth=True,
    )
    client = TestClient(app)

    response = client.post(
        "/v1/sip/recommendations",
        data={"monthly_budget_inr": 10000, "risk_profile": "Moderate"},
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 401
    assert "Authentication required" in response.json()["reasons"][0]


def test_api_accepts_valid_api_key_and_enforces_client_scope():
    registry = {
        "valid-secret-key-123": {
            "authorized_client_ids": ["client-alpha", "client-beta"],
            "tier": "enterprise",
        }
    }
    app = sip.create_sip_app(
        evidence_provider=lambda **kwargs: {},
        api_key_registry=registry,
        require_auth=True,
    )
    client = TestClient(app)

    # 1. Invalid API key -> 401
    resp_invalid = client.post(
        "/v1/sip/recommendations",
        headers={"X-API-Key": "wrong-key"},
        data={"monthly_budget_inr": 10000, "risk_profile": "Moderate"},
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_invalid.status_code == 401
    assert "Invalid or revoked API key" in resp_invalid.json()["reasons"][0]

    # 2. Valid key but unauthorized client_id -> 403 Forbidden
    resp_forbidden = client.post(
        "/v1/sip/recommendations",
        headers={"X-API-Key": "valid-secret-key-123", "X-Client-Id": "unauthorized-client-gamma"},
        data={"monthly_budget_inr": 10000, "risk_profile": "Moderate"},
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_forbidden.status_code == 403
    assert "not within the authorized scope" in resp_forbidden.json()["reasons"][0]

    # 3. Valid key and authorized client_id -> passes auth gate
    resp_ok = client.post(
        "/v1/sip/recommendations",
        headers={"Authorization": "Bearer valid-secret-key-123", "X-Client-Id": "client-alpha"},
        data={"monthly_budget_inr": 10000, "risk_profile": "Moderate"},
        files={"cas_file": ("statement.xlsx", _sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    # Passed authentication gate and reached recommendation validation
    assert resp_ok.status_code in (200, 422)
