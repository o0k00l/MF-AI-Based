import pytest
from fastapi.testclient import TestClient

from api import sip_production


def test_production_factory_requires_explicit_external_evidence_bundle(monkeypatch):
    monkeypatch.setattr(sip_production, "build_sip_evidence_provider", lambda: None)
    with pytest.raises(RuntimeError, match="MF_SIP_EVIDENCE_BUNDLE_DIR"):
        sip_production.create_production_sip_app()


def test_production_factory_injects_evidence_provider_but_keeps_release_gate(monkeypatch):
    provider = lambda **kwargs: {}
    monkeypatch.setattr(sip_production, "build_sip_evidence_provider", lambda: provider)
    app = sip_production.create_production_sip_app()
    readiness = TestClient(app).get("/ready").json()
    assert readiness["checks"]["evidence_provider"] == "configured"
    assert readiness["recommendations_enabled"] is False
    assert "research_release_approval_missing" in readiness["release_blockers"]
