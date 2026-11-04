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

from services.sip_evidence_contract import validate_evidence_provider_payload
from services.sip_evidence_bundle import build_sip_evidence_provider
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
        """Report dependency configuration, never recommendation eligibility."""
        if evidence_provider is None:
            return {
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
        return {
            "status": "ready_for_evidence_validation",
            "service": "sip-decision-support",
            "checks": {"evidence_provider": "configured"},
            "evidence_validation_available": True,
            # Provider configuration is not evidence validation. The service
            # remains HOLD-only until independent release gates are approved.
            "recommendations_enabled": False,
            "release_blockers": [
                "authenticated_daily_tri_unavailable",
                "independent_nse_calendar_unavailable",
                "research_release_approval_missing",
            ],
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
                evidence = validate_evidence_provider_payload(evidence)
                # The validated provider envelope also carries provenance-only
                # fields used at this boundary. Pass only the service's explicit
                # input contract; never forward the envelope wholesale.
                result = recommend_sip(
                    cas_path=cas_path,
                    metrics_path=evidence["metrics_path"],
                    aliases_path=evidence["aliases_path"],
                    monthly_budget_inr=monthly_budget_inr,
                    risk_profile=risk_profile,
                    scheme_master=evidence["scheme_master"],
                    scheme_master_source_bytes=evidence["scheme_master_source_bytes"],
                    portfolio_disclosures_by_scheme_id=evidence["portfolio_disclosures_by_scheme_id"],
                    portfolio_disclosure_source_bytes_by_scheme_id=evidence["portfolio_disclosure_source_bytes_by_scheme_id"],
                    disclosure_as_of_date=evidence["disclosure_as_of_date"],
                    candidate_universe=evidence["candidate_universe"],
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


app = create_sip_app(evidence_provider=build_sip_evidence_provider())
