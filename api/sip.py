"""FastAPI surface for the supported SIP recommendation workflow.

The application must be created with an explicit evidence provider. There is no
implicit repository-data fallback and no network source scraping in this API.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from services.sip_recommendation import recommend_sip

MAX_CAS_BYTES = 20 * 1024 * 1024


def create_sip_app(
    evidence_provider: Callable[..., dict[str, Any]] | None = None,
) -> FastAPI:
    """Create an isolated SIP API; provider supplies reviewed source evidence."""
    app = FastAPI(
        title="Mutual Fund SIP Decision Support API",
        version="1.0.0",
        description="Read-only SIP analysis. No orders or execution are supported.",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "sip-decision-support"}

    @app.get("/ready")
    def readiness() -> dict[str, Any]:
        """Report whether the SIP evidence dependency is configured."""
        if evidence_provider is None:
            return {
                "status": "not_ready",
                "service": "sip-decision-support",
                "checks": {"evidence_provider": "not_configured"},
                "recommendations_enabled": False,
            }
        return {
            "status": "ready_for_evidence_validation",
            "service": "sip-decision-support",
            "checks": {"evidence_provider": "configured"},
            "recommendations_enabled": True,
        }

    @app.post("/v1/sip/recommendations")
    async def create_recommendation(
        cas_file: UploadFile = File(...),
        monthly_budget_inr: float = Form(...),
        risk_profile: str = Form(...),
    ):
        if not math.isfinite(monthly_budget_inr) or monthly_budget_inr <= 0:
            return JSONResponse(status_code=422, content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": ["Monthly SIP budget must be finite and greater than zero."],
                "unallocated_budget_inr": monthly_budget_inr if math.isfinite(monthly_budget_inr) else None,
            })
        if risk_profile not in {"Conservative", "Moderate", "Aggressive", "Custom"}:
            return JSONResponse(status_code=422, content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": ["Risk profile must be Conservative, Moderate, Aggressive or Custom."],
                "unallocated_budget_inr": monthly_budget_inr,
            })
        if not (cas_file.filename or "").lower().endswith(".xlsx"):
            return JSONResponse(status_code=415, content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": ["Only an XLSX CAS statement is supported."],
                "unallocated_budget_inr": monthly_budget_inr,
            })

        payload = await cas_file.read(MAX_CAS_BYTES + 1)
        if len(payload) > MAX_CAS_BYTES:
            return JSONResponse(status_code=413, content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": ["CAS upload exceeds the 20 MiB limit."],
                "unallocated_budget_inr": monthly_budget_inr,
            })
        if not payload:
            return JSONResponse(status_code=422, content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": ["CAS upload is empty."],
                "unallocated_budget_inr": monthly_budget_inr,
            })

        if evidence_provider is None:
            return JSONResponse(content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": [
                    "No reviewed evidence provider is configured for this deployment.",
                    "The uploaded CAS was not persisted; the full budget remains unallocated.",
                ],
                "unallocated_budget_inr": monthly_budget_inr,
            })

        # Temporary storage is isolated and removed automatically after the
        # request. Never write investor statements into the repository or logs.
        with tempfile.TemporaryDirectory(prefix="sip-cas-") as temp_dir:
            cas_path = Path(temp_dir) / "uploaded-cas.xlsx"
            cas_path.write_bytes(payload)
            try:
                evidence = evidence_provider(
                    cas_path=cas_path,
                    monthly_budget_inr=monthly_budget_inr,
                    risk_profile=risk_profile,
                )
                if not isinstance(evidence, dict):
                    raise TypeError("Evidence provider must return a mapping")
                forbidden = {"cas_path", "monthly_budget_inr", "risk_profile"}
                if forbidden.intersection(evidence):
                    raise ValueError("Evidence provider attempted to override request-bound inputs")
                result = recommend_sip(
                    cas_path=cas_path,
                    monthly_budget_inr=monthly_budget_inr,
                    risk_profile=risk_profile,
                    **evidence,
                )
            except Exception as exc:
                # Do not expose exception text, local paths, source records or
                # uploaded content to the client.
                return JSONResponse(content={
                    "status": "HOLD",
                    "decision": "NO_ACTION",
                    "reasons": [f"Evidence preparation failed closed ({type(exc).__name__})."],
                    "unallocated_budget_inr": monthly_budget_inr,
                })

        return JSONResponse(content=result)

    return app


app = create_sip_app()
