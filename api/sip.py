"""FastAPI surface for the supported SIP recommendation workflow.

The application must be created with an explicit evidence provider. There is no
implicit repository-data fallback and no network source scraping in this API.
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any, Callable

from services.sip_reviewer_approval import load_sip_reviewer_trust_registry

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse

from services.sip_evidence_contract import validate_evidence_provider_payload
from services.sip_evidence_bundle import build_sip_evidence_provider
from services.sip_recommendation import recommend_sip

MAX_CAS_BYTES = 20 * 1024 * 1024


def create_sip_app(
    evidence_provider: Callable[..., dict[str, Any]] | None = None,
    api_key_registry: dict[str, dict[str, Any]] | None = None,
    require_auth: bool | None = None,
) -> FastAPI:
    """Create an isolated SIP API; provider supplies reviewed source evidence."""
    import os
    if evidence_provider is None and os.environ.get("MF_SIP_EVIDENCE_BUNDLE_DIR"):
        try:
            evidence_provider = build_sip_evidence_provider()
        except Exception:
            evidence_provider = None
    try:
        reviewer_trust_registry = load_sip_reviewer_trust_registry() if evidence_provider is not None else None
    except (OSError, ValueError):
        reviewer_trust_registry = None

    import os
    if require_auth is None:
        auth_enabled = bool(api_key_registry) or os.environ.get("MF_API_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")
    else:
        auth_enabled = require_auth

    import time
    tenant_request_counts: dict[str, list[float]] = {}

    app = FastAPI(
        title="Mutual Fund SIP Decision Support API",
        version="1.0.0",
        description="Read-only SIP analysis. No orders or execution are supported.",
    )

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.get("/v1/deployment/status")
    def deployment_status() -> dict[str, Any]:
        env_mode = os.environ.get("MF_DEPLOYMENT_ENVIRONMENT", "production").lower()
        return {
            "deployment_environment": env_mode,
            "auth_enforced": auth_enabled,
            "quota_management_active": api_key_registry is not None,
            "evidence_configured": evidence_provider is not None,
            "reviewer_registry_configured": reviewer_trust_registry is not None,
        }

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
        if reviewer_trust_registry is None:
            return {
                "status": "not_ready",
                "service": "sip-decision-support",
                "checks": {"evidence_provider": "configured", "independent_reviewer_trust_registry": "missing_or_invalid"},
                "evidence_validation_available": False,
                "recommendations_enabled": False,
                "release_blockers": [
                    "independent_reviewer_trust_registry_unavailable",
                    "authenticated_daily_tri_unavailable",
                    "independent_nse_calendar_unavailable",
                    "research_release_approval_missing",
                ],
            }
        return {
            "status": "ready_for_evidence_validation",
            "service": "sip-decision-support",
            "checks": {"evidence_provider": "configured", "independent_reviewer_trust_registry": "configured"},
            "evidence_validation_available": True,
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
        portfolio_context_json: str | None = Form(None),
        x_api_key: str | None = Header(None, alias="X-API-Key"),
        authorization: str | None = Header(None, alias="Authorization"),
        x_client_id: str | None = Header(None, alias="X-Client-Id"),
    ):
        if auth_enabled:
            token = None
            if x_api_key:
                token = x_api_key.strip()
            elif authorization and authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()

            if not token:
                return JSONResponse(status_code=401, content={
                    "status": "HOLD",
                    "decision": "NO_ACTION",
                    "reasons": ["Authentication required: Valid X-API-Key or Authorization Bearer token must be provided."],
                })

            if api_key_registry is not None:
                if token not in api_key_registry:
                    return JSONResponse(status_code=401, content={
                        "status": "HOLD",
                        "decision": "NO_ACTION",
                        "reasons": ["Invalid or revoked API key."],
                    })
                key_info = api_key_registry[token]
                tenant_id = key_info.get("tenant_id", token)
                allowed_clients = key_info.get("authorized_client_ids", [])
                if x_client_id and allowed_clients and x_client_id not in allowed_clients:
                    return JSONResponse(status_code=403, content={
                        "status": "HOLD",
                        "decision": "NO_ACTION",
                        "reasons": [f"Forbidden: Client ID '{x_client_id}' is not within the authorized scope of this credential."],
                    })
                # Tenant Quota & Rate Limit Enforcement
                rate_limit = key_info.get("rate_limit_per_minute", 60)
                now_ts = time.time()
                window = 60.0
                timestamps = tenant_request_counts.setdefault(tenant_id, [])
                tenant_request_counts[tenant_id] = [t for t in timestamps if now_ts - t < window]
                if len(tenant_request_counts[tenant_id]) >= rate_limit:
                    return JSONResponse(status_code=429, content={
                        "status": "HOLD",
                        "decision": "NO_ACTION",
                        "reasons": [f"Tenant quota exceeded: rate limit of {rate_limit} requests/minute reached."],
                        "retry_after_seconds": int(window - (now_ts - tenant_request_counts[tenant_id][0])) + 1,
                    })
                tenant_request_counts[tenant_id].append(now_ts)
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
                "reasons": [
                    "This SIP endpoint currently supports Conservative, Moderate, Aggressive and Custom profiles only.",
                ],
                "unallocated_budget_inr": monthly_budget_inr,
            })
        if not (cas_file.filename or "").lower().endswith(".xlsx"):
            return JSONResponse(status_code=415, content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": ["Only an XLSX CAS statement is supported."],
                "unallocated_budget_inr": monthly_budget_inr,
            })

        portfolio_context = None
        if portfolio_context_json is not None:
            if len(portfolio_context_json.encode("utf-8")) > 256 * 1024:
                return JSONResponse(status_code=413, content={
                    "status": "HOLD", "decision": "NO_ACTION",
                    "reasons": ["Portfolio context exceeds the 256 KiB limit."],
                    "unallocated_budget_inr": monthly_budget_inr,
                })
            try:
                portfolio_context = json.loads(portfolio_context_json)
                if not isinstance(portfolio_context, dict):
                    raise ValueError("portfolio context must be an object")
            except (json.JSONDecodeError, ValueError):
                return JSONResponse(status_code=422, content={
                    "status": "HOLD", "decision": "NO_ACTION",
                    "reasons": ["Portfolio context must be a valid JSON object."],
                    "unallocated_budget_inr": monthly_budget_inr,
                })

        custom_saa_target_obj = None
        if risk_profile == "Custom":
            target_data = None
            if portfolio_context and isinstance(portfolio_context, dict):
                target_data = portfolio_context.get("custom_saa_target")
            if not target_data:
                return JSONResponse(status_code=422, content={
                    "status": "HOLD",
                    "decision": "NO_ACTION",
                    "reasons": [
                        "Custom SAA is not implemented without a reviewed client IPS mandate; valid custom_saa_target is required in portfolio context.",
                    ],
                    "unallocated_budget_inr": monthly_budget_inr,
                })
            from core.models import AssetAllocationTarget
            try:
                custom_saa_target_obj = AssetAllocationTarget(**target_data)
            except Exception as exc:
                return JSONResponse(status_code=422, content={
                    "status": "HOLD",
                    "decision": "NO_ACTION",
                    "reasons": [
                        f"Invalid custom_saa_target schema: {exc}",
                    ],
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

        if reviewer_trust_registry is None:
            return JSONResponse(content={
                "status": "HOLD",
                "decision": "NO_ACTION",
                "reasons": [
                    "Independent reviewer trust registry is missing or invalid; signed SIP evidence cannot be authenticated.",
                    "The full budget remains unallocated.",
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
                evidence = validate_evidence_provider_payload(
                    evidence, trust_registry=reviewer_trust_registry,
                    require_reviewer_signature=True,
                )
                # The validated provider envelope also carries provenance-only
                # fields used at this boundary. Pass only the service's explicit
                # input contract; never forward the envelope wholesale.
                service_inputs = {
                    "cas_path": cas_path,
                    "metrics_path": evidence["metrics_path"],
                    "aliases_path": evidence["aliases_path"],
                    "monthly_budget_inr": monthly_budget_inr,
                    "risk_profile": risk_profile,
                    "scheme_master": evidence["scheme_master"],
                    "scheme_master_source_bytes": evidence["scheme_master_source_bytes"],
                    "portfolio_disclosures_by_scheme_id": evidence["portfolio_disclosures_by_scheme_id"],
                    "portfolio_disclosure_source_bytes_by_scheme_id": evidence["portfolio_disclosure_source_bytes_by_scheme_id"],
                    "disclosure_as_of_date": evidence["disclosure_as_of_date"],
                    "candidate_universe": evidence["candidate_universe"],
                }
                for provenance_field in (
                    "metrics_source_bytes",
                    "candidate_universe_source_bytes",
                    "candidate_score_source_bytes",
                    "category_anchor_source_bytes",
                    "portfolio_context_source_bytes",
                ):
                    if provenance_field in evidence:
                        service_inputs[provenance_field] = evidence[provenance_field]
                metrics_metadata = evidence.get("metrics_source_metadata")
                if isinstance(metrics_metadata, dict):
                    service_inputs["metrics_normalized_sha256"] = metrics_metadata.get(
                        "normalized_metrics_sha256"
                    )
                candidate_metadata = evidence.get("candidate_universe_source")
                if isinstance(candidate_metadata, dict):
                    service_inputs["candidate_universe_normalized_sha256"] = candidate_metadata.get(
                        "normalized_candidate_universe_sha256"
                    )
                provider_portfolio_context = evidence.get("portfolio_context")
                if provider_portfolio_context is not None:
                    provider_portfolio_context["evidence_attested_by_provider"] = True
                    provider_portfolio_context["_source_bundle_sha256"] = evidence[
                        "portfolio_context_source_metadata"
                    ]["source_document_sha256"]
                    service_inputs["portfolio_context"] = provider_portfolio_context
                elif portfolio_context is not None:
                    # Client declarations are useful for scenario diagnostics,
                    # but cannot attest source authenticity or perimeter completeness.
                    portfolio_context["_client_supplied_unverified"] = True
                    service_inputs["portfolio_context"] = portfolio_context
                if custom_saa_target_obj is not None:
                    service_inputs["custom_saa_target"] = custom_saa_target_obj
                result = recommend_sip(**service_inputs)
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
