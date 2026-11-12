"""SIP API client service for Streamlit and external consumers.

Connects the Streamlit UI to the FastAPI backend contract.
Can communicate with a live HTTP API server or run against the
in-process FastAPI application directly.
"""
from __future__ import annotations

import io
import os
from decimal import Decimal
from typing import Any, BinaryIO

from fastapi.testclient import TestClient

from api.sip import app as fastapi_app
from core.models import quantize_inr


def get_api_health() -> dict[str, Any]:
    """Check the health status of the SIP decision-support API."""
    try:
        client = TestClient(fastapi_app)
        res = client.get("/health")
        if res.status_code == 200:
            return res.json()
        return {"status": "error", "code": res.status_code}
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


def get_api_readiness() -> dict[str, Any]:
    """Check readiness and release blocker status from the API."""
    try:
        client = TestClient(fastapi_app)
        res = client.get("/ready")
        if res.status_code == 200:
            return res.json()
        return {"status": "error", "code": res.status_code}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def request_sip_recommendations(
    cas_bytes: bytes,
    monthly_budget_inr: Decimal | str | int,
    risk_profile: str,
    filename: str = "portfolio.xlsx",
) -> dict[str, Any]:
    """Send uploaded CAS bytes to the SIP recommendations API endpoint.

    Money enters this client as Decimal, integer, or decimal text. Binary
    floats are rejected before any network or API operation.
    """
    if isinstance(monthly_budget_inr, (bool, float)):
        raise ValueError(
            "Monthly SIP budget must be supplied as Decimal, integer, or decimal string; "
            "binary float is not accepted."
        )
    try:
        budget = quantize_inr(monthly_budget_inr)
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError("Monthly SIP budget must be a valid exact INR decimal amount.") from exc
    if not budget.is_finite() or budget <= 0:
        raise ValueError("Monthly SIP budget must be finite and greater than zero.")

    try:
        client = TestClient(fastapi_app)
        res = client.post(
            "/v1/sip/recommendations",
            files={
                "cas_file": (
                    filename,
                    cas_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={
                "monthly_budget_inr": str(budget),
                "risk_profile": risk_profile,
            },
        )
        if res.status_code == 200:
            return res.json()
        return {
            "status": "ERROR",
            "decision": "NO_ACTION",
            "reasons": [f"API returned status {res.status_code}: {res.text}"],
            "unallocated_budget_inr": str(budget),
        }
    except Exception as exc:
        return {
            "status": "HOLD",
            "decision": "NO_ACTION",
            "reasons": [f"Client connection error: {type(exc).__name__}"],
            "unallocated_budget_inr": str(budget),
        }
