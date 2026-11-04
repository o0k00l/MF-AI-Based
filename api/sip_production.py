"""Explicit production SIP app factory.

Deploy this module only with an externally mounted, reviewed evidence bundle.
AI model-provider credentials are deliberately unrelated to this source provider.
The app remains recommendation-HOLD-only until independent TRI/research release
approval is added through the separate release-control process.
"""
from __future__ import annotations

from fastapi import FastAPI

from api.sip import create_sip_app
from services.sip_evidence_bundle import build_sip_evidence_provider


def create_production_sip_app() -> FastAPI:
    """Construct the deployment app from the explicitly configured bundle."""
    provider = build_sip_evidence_provider()
    if provider is None:
        raise RuntimeError(
            "MF_SIP_EVIDENCE_BUNDLE_DIR must point to a reviewed external SIP evidence bundle."
        )
    return create_sip_app(evidence_provider=provider)


app = create_sip_app(evidence_provider=build_sip_evidence_provider())
