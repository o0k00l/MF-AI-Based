# AI Provider and SIP Deployment Audit

**Audit date:** 2026-11-04  
**Audited ref:** `main`  
**Scope:** AI provider adapters, the supported SIP API boundary, and checked-in deployment entry points.

## Findings

### AI provider integration

- `core/ai_engine.py` is a narrative-generation adapter. It is not imported or called by `api/sip.py` or `services/sip_recommendation.py`.
- Requesty and OpenRouter use their OpenAI-compatible chat-completions endpoints. Their candidate models now come only from the authenticated live catalogue; no hard-coded model IDs are injected when discovery fails.
- Requesty catalogue discovery is authenticated at `/v1/models`. Its current 403 is an account/key permission failure until Requesty confirms otherwise.
- OpenRouter catalogue discovery is authenticated at `/api/v1/models`. Its current 401 is an authentication failure until the key is corrected.
- Gemini is disabled from the runtime provider chain and removed from the supported settings UI because the available API model catalogue does not prove zero-cost usage.
- Model discovery cache entries are scoped to a one-way fingerprint of the API key, expire after one hour, and never store the raw key. Each adapter attempts at most five discovered models.
- Provider failures retain safe status/code/model metadata; raw provider response bodies and credentials are not included in the smoke-test output.

### SIP application wiring

- `app.py` launches the retired Streamlit dashboard; the README explicitly says that dashboard is disabled and the repository is not approved for production.
- `api/sip.py` exposes the FastAPI application as `api.sip:app`, but the module-level application is created with `evidence_provider=None`.
- With no explicitly injected evidence provider, the SIP API intentionally returns `HOLD / NO_ACTION` and leaves the complete budget unallocated.
- `services/sip_recommendation.py` requires original source bytes for the scheme master and each scheme-level disclosure, exact scheme identity, complete constituent coverage, an as-of date and a source-verified candidate universe. It suppresses provisional allocations even after deterministic calculation until the independent benchmark/research release gate is approved.
- Existing API tests explicitly verify the default HOLD boundary and the temporary-CAS lifecycle.

## Decision

**Do not wire AI provider credentials into the SIP evidence-provider slot.** LLM availability is not source evidence and cannot establish scheme identity, portfolio constituents, benchmark TRI authenticity, candidate eligibility or release approval.

The current repository has no reviewed production evidence-provider factory to inject into `create_sip_app`. The checked-in module-level app is therefore permanently HOLD-only until an approved factory is implemented and explicitly injected. Adding a generic environment-variable import or pointing the SIP API at `core.ai_engine.call_llm` would weaken the evidence boundary and create a false impression of production readiness.

## Required prerequisites before API deployment

1. Implement and independently review a deterministic evidence-provider factory that supplies the exact required source documents and metadata.
2. Add an explicit deployment entry point that constructs the SIP app with that factory; never silently fall back to repository-local or synthetic evidence.
3. Add integration tests using synthetic fixtures that prove exact scheme-ID matching, source-byte integrity, disclosure freshness/coverage, candidate-universe completeness and full-budget HOLD on any failed gate.
4. Keep the benchmark/research release gate blocked until authenticated daily TRI data and an independently verified exchange-session calendar pass.
5. Configure the hosting platform's start command, health check, secrets and access controls only after the supported API deployment target is selected and documented.
6. Approve production release against the exact commit and the repository's `PRODUCTION_RELEASE_CHECKLIST.md`.

## Verification boundary

The latest recorded live provider run (run ID `41781807609`, commit `33bbd71c95d7f970a6fbf4e78bd184845e9882bc`) failed with Requesty 403, OpenRouter 401 and Gemini 400. The free-only adapter changes do not prove the credentials are valid. The latest live run (run ID `41783857358`, commit `99475790453c8e985820b9eeb914a400dc823e97`) failed with Requesty 403 and OpenRouter 401. Both enabled provider credentials need provider-side verification. Gemini is disabled pending authoritative zero-cost verification.
