# Production Deployment Guide

## Overview

This document describes the production deployment requirements for the Mutual Fund SIP Decision Support API.

**Current Status**: NOT APPROVED FOR PRODUCTION - See `PRODUCTION_RELEASE_CHECKLIST.md` for gate status.

The API is a **read-only decision-support engine** with the following characteristics:
- No broker, registrar, or payment execution integration
- All recommendations are `HOLD` / `NO_ACTION` until independent TRI/research release approval
- AI narrative providers are optional and non-authoritative (deterministic calculations are independent)
- Evidence-based: requires externally mounted, reviewed SIP evidence bundle

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Load Balancer / Ingress                    │
│                     (TLS termination, WAF)                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SIP API (FastAPI + Uvicorn)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ /v1/sip/     │  │ /health      │  │ /ready               │  │
│  │ recommendations     │ (liveness)   │  │ (readiness)        │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│         │                                      │                │
│         ▼                                      ▼                │
│  ┌──────────────────────┐             ┌──────────────────┐     │
│  │ Evidence Provider    │             │ Reviewer Trust   │     │
│  │ (mounted bundle)     │             │ Registry         │     │
│  └──────────────────────┘             └──────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              External Evidence Bundle (Read-Only)               │
│  - scheme_master.json (verified, dated, digest)                 │
│  - fund_metrics.json (verified, dated, digest)                  │
│  - fund_aliases.json (verified, dated, digest)                  │
│  - portfolio_disclosures/ (per-scheme, verified, dated)         │
│  - candidate_universe.json (verified, dated, digest)            │
│  - reviewer_approvals/ (detached signatures)                    │
└─────────────────────────────────────────────────────────────────┘
```

## Required Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MF_SIP_EVIDENCE_BUNDLE_DIR` | **Yes** | Path to externally mounted, reviewed SIP evidence bundle. Must contain verified scheme_master, fund_metrics, fund_aliases, portfolio_disclosures, candidate_universe with digests and reviewer metadata. |
| `MF_API_REQUIRE_AUTH` | **Yes** | Set to `true` for production. Enforces API-key authentication. |
| `MF_DEPLOYMENT_ENVIRONMENT` | No | Deployment environment label (e.g., `production`, `staging`). Default: `production`. |
| `MF_AI_CACHE_DIR` | No | Optional cache directory for AI model catalogues. Must be outside the application root. |
| `AI_TIMEOUT_SECONDS` | No | Timeout for AI provider calls. Default: `10`. |
| `REQUESTY_API_KEY` | Optional | For AI narrative provider (Requesty). Must be zero-cost verified. |
| `OPENROUTER_API_KEY` | Optional | For AI narrative provider (OpenRouter). Must be zero-cost verified. |### Evidence Bundle Requirements

The MF_SIP_EVIDENCE_BUNDLE_DIR must contain a **reviewed, externally sourced** evidence bundle with:

`
evidence_bundle/
├── scheme_master.json              # Verified scheme master with digest
├── scheme_master_source_bytes      # Original source bytes for verification
├── fund_metrics.json               # Verified fund metrics with digest
├── fund_metrics_source_bytes       # Original source bytes
├── fund_aliases.json               # Verified fund aliases with digest
├── fund_aliases_source_bytes       # Original source bytes
├── candidate_universe.json         # Verified candidate universe with digest
├── candidate_universe_source_bytes # Original source bytes
├── candidate_score_source_bytes    # Candidate scoring evidence
├── category_anchor_source_bytes    # Category anchor evidence
├── portfolio_context_source_bytes  # Portfolio context evidence
├── portfolio_disclosures/          # Per-scheme portfolio disclosures
│   ├── SCHEME-ID-1.json
│   ├── SCHEME-ID-1_source_bytes
│   └── ...
└── reviewer_approvals/             # Detached reviewer approval envelopes
    └── *.sig
`

Each JSON file must include:
- source_document_sha256: SHA-256 of original source
- 
ormalized_*_sha256: SHA-256 of normalized content
- source_retrieved_at: ISO 8601 retrieval timestamp
- 
eviewer_attested: Boolean reviewer attestation
content = """## Deployment Platforms

### Option 1: Cloud Run (Google Cloud) - Recommended

```yaml
# cloudrun.yaml
service: sip-decision-support
region: asia-south1  # Mumbai
cpu: 2
memory: 2Gi
min-instances: 1
max-instances: 10
concurrency: 80
timeout: 300s

env:
  - name: MF_SIP_EVIDENCE_BUNDLE_DIR
    value: /evidence_bundle
  - name: MF_API_REQUIRE_AUTH
    value: "true"
  - name: MF_DEPLOYMENT_ENVIRONMENT
    value: production

volumes:
  - name: evidence-bundle
    secret: sip-evidence-bundle

volume-mounts:
  - name: evidence-bundle
    mount-path: /evidence_bundle
```

**Advantages**: Serverless, auto-scaling, built-in HTTPS, secret integration, pay-per-use.

### Option 2: Fly.io

```toml
# fly.toml
app = "sip-decision-support"
primary_region = "bom"

[build]
  dockerfile = "Dockerfile"

[env]
  MF_API_REQUIRE_AUTH = "true"
  MF_DEPLOYMENT_ENVIRONMENT = "production"

[mounts]
  source = "evidence_bundle"
  destination = "/evidence_bundle"

[processes]
  app = "uvicorn api.sip_production:create_production_sip_app --factory --host 0.0.0.0 --port 8080 --workers 2"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = false
  min_machines_running = 1
```

**Advantages**: Global Anycast, simple secrets, persistent volumes, straightforward pricing.
"""content = """### Option 4: Kubernetes (EKS/GKE/AKS)

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sip-decision-support
spec:
  replicas: 3
  selector:
    matchLabels:
      app: sip-decision-support
  template:
    metadata:
      labels:
        app: sip-decision-support
    spec:
      containers:
        - name: api
          image: your-registry/sip-decision-support:latest
          ports:
            - containerPort: 8000
          env:
            - name: MF_API_REQUIRE_AUTH
              value: "true"
            - name: MF_DEPLOYMENT_ENVIRONMENT
              value: production
            - name: MF_SIP_EVIDENCE_BUNDLE_DIR
              value: /evidence_bundle
          volumeMounts:
            - name: evidence-bundle
              mountPath: /evidence_bundle
              readOnly: true
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
      volumes:
        - name: evidence-bundle
          secret:
            secretName: sip-evidence-bundle
```

## Health & Readiness Endpoints

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| GET /health | Liveness probe | {\"status\": \"ok\", \"service\": \"sip-decision-support\"} |
| GET /ready | Readiness probe | {\"status\": \"ready\", \"checks\": {\"evidence_provider\": \"configured\"}} or not_ready |
| GET /v1/deployment/status | Deployment info | {\"deployment_environment\": \"production\", \"auth_enforced\": true, \"quota_management_active\": true, \"evidence_configured\": true, \"reviewer_registry_configured\": true} |

**Important**: /ready returns not_ready if evidence provider is not configured. This prevents traffic routing to incomplete deployments.

## Security Configuration

### API Authentication

Production deployments must enable authentication:

```python
# In production, use create_production_sip_app() which enforces auth
from api.sip_production import create_production_sip_app
app = create_production_sip_app()
```

API key registry format:
```python
api_key_registry = {
    \"tenant-api-key-1\": {
        \"tenant_id\": \"tenant-alpha\",
        \"rate_limit_per_minute\": 30,
    },
    \"tenant-api-key-2\": {
        \"tenant_id\": \"tenant-beta\",
        \"rate_limit_per_minute\": 60,
    },
}
```

### Rate Limiting

- Per-tenant, per-minute sliding window
- Returns 429 Too Many Requests with retry_after_seconds
- Quota exceeded response includes structured reason

### Security Headers (Automatic)

All responses include:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Strict-Transport-Security: max-age=31536000; includeSubDomains

### Upload Limits

- Maximum CAS file size: 20 MiB (MAX_CAS_BYTES = 20 * 1024 * 1024)
- Enforced at middleware level before processing

### TLS

- TLS termination at load balancer/ingress
- Application runs HTTP internally (behind trusted proxy)
- HSTS header enforces HTTPS for clients
"""content = """## Logging & Observability

### Structured Logging

Configure JSON logging for production:

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            \"timestamp\": self.formatTime(record),
            \"level\": record.levelname,
            \"logger\": record.name,
            \"message\": record.getMessage(),
            \"module\": record.module,
            \"function\": record.funcName,
            \"line\": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key not in {\"name\", \"msg\", \"args\", \"created\", \"filename\", \"funcName\",
                          \"levelname\", \"levelno\", \"lineno\", \"module\", \"msecs\",
                          \"message\", \"pathname\", \"process\", \"processName\", \"thread\",
                          \"threadName\", \"exc_info\", \"exc_text\", \"stack_info\"}:
                log_entry[key] = value
        return json.dumps(log_entry)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
```

### Log Redaction

Never log:
- API keys or secrets
- Investor PII (names, PAN, folio numbers, account numbers)
- Raw CAS file contents
- Portfolio values (unless explicitly required for audit)
- AI provider prompts/responses

### Metrics

Recommended metrics to export (Prometheus format):
- sip_requests_total{endpoint, status, tenant}
- sip_request_duration_seconds{endpoint}
- sip_rate_limit_exceeded_total{tenant}
- sip_evidence_bundle_status{status}
- sip_recommendation_status{status}

## AI Provider Configuration (Optional)

AI providers are optional and non-authoritative. Deterministic SIP calculations do not require AI.

### Requesty (Primary)

```bash
# Required: zero-cost models only
REQUESTY_API_KEY=sk-xxx
```

### OpenRouter (Fallback)

```bash
# Required: only :free models or explicit zero pricing
OPENROUTER_API_KEY=sk-xxx
```

### Gemini (Disabled)

Gemini is disabled by policy. Do not enable without verifiable zero-cost pricing metadata.

### Provider Smoke Test

Run manually before deployment:
```bash
export REQUESTY_API_KEY=...
export OPENROUTER_API_KEY=...
python scripts/smoke_test_ai_providers.py
```

CI workflow: .github/workflows/ai-provider-integration.yml (manual trigger)

## Deployment Checklist

### Pre-Deployment
- [ ] Evidence bundle reviewed, mounted, and verified at MF_SIP_EVIDENCE_BUNDLE_DIR
- [ ] Reviewer trust registry configured with valid public keys
- [ ] API key registry configured with tenant IDs and rate limits
- [ ] GitHub Actions secrets configured (REQUESTY_API_KEY, OPENROUTER_API_KEY)
- [ ] AI provider smoke test passes (if AI narrative enabled)
- [ ] Dependency vulnerability scan clean (pip-audit)
- [ ] All CI tests pass on target commit SHA
- [ ] Security review completed (secret scanning, SBOM review)

### Deployment
- [ ] Docker image built and scanned
- [ ] Image deployed to target platform
- [ ] Health checks passing (/health, /ready)
- [ ] Deployment status endpoint returns auth_enforced: true
- [ ] TLS certificate valid and configured
- [ ] DNS configured and propagating

### Post-Deployment
- [ ] Smoke test: POST /v1/sip/recommendations with valid API key returns 200/422 (not 401)
- [ ] Rate limiting verified (exceed quota -> 429)
- [ ] Evidence bundle accessible (check /v1/deployment/status)
- [ ] Logging verified (JSON format, no secrets)
- [ ] Monitoring alerts configured

## Rollback Procedure

1. Identify last known-good image tag
2. Deploy previous image version
3. Verify health checks
4. Validate evidence bundle mount
5. Confirm API key registry loaded

## Operational Ownership

| Role | Responsibility |
|------|----------------|
| Platform Engineer | Infrastructure, scaling, TLS, secrets |
| Security Engineer | Secret rotation, vulnerability scanning, access review |
| Data Engineer | Evidence bundle refresh, digest verification, reviewer coordination |
| Product Owner | Release approval, feature flags, SLA definition |

## Support & Escalation

- Primary: Platform Engineering on-call
- Secondary: Security Engineering (for auth/secret issues)
- Data: Data Engineering (for evidence bundle issues)

---

**Document Version**: 1.0
**Last Updated**: 2026-11-12
**Review Cycle**: Before each production deployment
"""