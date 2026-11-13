import pytest
from fastapi.testclient import TestClient

from api import sip_production


def test_production_factory_requires_explicit_external_evidence_bundle(monkeypatch):
    monkeypatch.setattr(sip_production, "build_sip_evidence_provider", lambda: None)
    with pytest.raises(RuntimeError, match="MF_SIP_EVIDENCE_BUNDLE_DIR"):
        sip_production.create_production_sip_app()


def test_production_factory_injects_evidence_provider_but_keeps_release_gate(monkeypatch, tmp_path):
    import json

    provider = lambda **kwargs: {}
    monkeypatch.setattr(sip_production, "build_sip_evidence_provider", lambda: provider)
    registry_path = tmp_path / "api-key-registry.json"
    registry_path.write_text(json.dumps({
        "p" * 40: {
            "tenant_id": "production-tenant",
            "authorized_client_ids": ["production-client"],
            "rate_limit_per_minute": 60,
        }
    }), encoding="utf-8")
    monkeypatch.setenv("MF_API_KEY_REGISTRY_PATH", str(registry_path))
    app = sip_production.create_production_sip_app()
    readiness = TestClient(app).get("/ready").json()
    assert readiness["checks"]["evidence_provider"] == "configured"
    assert readiness["recommendations_enabled"] is False
    assert "research_release_approval_missing" in readiness["release_blockers"]
