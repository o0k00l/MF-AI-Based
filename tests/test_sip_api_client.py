"""Unit tests for services/sip_api_client.py ensuring integration between UI and API."""
from __future__ import annotations

import io
from datetime import date
from openpyxl import Workbook

from services.sip_api_client import get_api_health, get_api_readiness, request_sip_recommendations


def _sample_cas_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["To Date", date.today().strftime("%d-%b-%Y")])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["HDFC Flexi Cap Fund Direct Growth", "FOLIO-1", 100000.0, 125000.0, 100.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_api_health_check():
    health = get_api_health()
    assert health.get("status") == "ok"
    assert health.get("service") == "sip-decision-support"


def test_api_readiness_check():
    ready = get_api_readiness()
    assert ready.get("service") == "sip-decision-support"
    assert "release_blockers" in ready


def test_request_sip_recommendations_fail_closed_contract():
    cas_bytes = _sample_cas_bytes()
    resp = request_sip_recommendations(
        cas_bytes=cas_bytes,
        monthly_budget_inr=20000.0,
        risk_profile="Aggressive",
    )
    assert resp.get("status") == "HOLD"
    assert resp.get("decision") == "NO_ACTION"
    assert resp.get("unallocated_budget_inr") == 20000.0
    assert len(resp.get("reasons", [])) > 0

