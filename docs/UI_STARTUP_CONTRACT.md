# Canonical Application Startup Contract & UI Boundary

This specification defines the authoritative application startup contract and entry-point responsibilities for the repository.

## 1. Scope & Role of Entry Points

The repository maintains two entry points with distinct, non-overlapping roles:

1. **Root Launcher (`app.py`)**:
   - Canonical CLI invocation point for local development environments.
   - Executes: `python app.py` (which internally delegates to `streamlit run ui/app.py`).
   - Does NOT implement financial calculations, client ingestion, or planning logic.

2. **Streamlit Application (`ui/app.py`)**:
   - The UI entry point executed by Streamlit.
   - Enforces the legacy-dashboard retirement safety boundary.
   - Renders a read-only retirement notice explaining that legacy unvalidated planning flows are retired.
   - Guarantees that no portfolio data is ingested, no orders are generated, and no recommendations are emitted.

## 2. Invariants & Safety Constraints

- **No Duplicated Financial Logic**: All financial math, eligibility screening, allocation, and SAA calculations reside strictly in the core engine modules (`core/math_engine.py`, `core/eligibility.py`, `core/portfolio_sip_controls.py`) and services (`services/sip_recommendation.py`). The UI never implements or duplicates calculation routines.
- **Fail-Closed Boundary**: The former interactive dashboard depended on retired in-repository client file structures and unverified planning flows. It remains retired until an independently reviewed, external-only, read-only UI is implemented.
- **Production API Boundary**: For production decision support, the canonical entry point is `api/sip.py` via FastAPI (`uvicorn api.sip:app`), consuming validated evidence bundles without UI interactivity.

## 3. Contributor & Operator Verification

Tests verifying this contract are maintained in `tests/test_ui_retirement.py`.


## Cross-document policy and configurability rules (binding)

This document is subordinate to `docs/SIP_ENGINE_DECISION_REGISTER.md` for settled product decisions and `docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md` for normative behaviour. Read it with `IMPLEMENTATION_STATUS.md` for implementation/acceptance status. Historical audit snapshots and remediation plans are evidence/history, not a source of current policy.

**No arbitrary hardcoding:** no allocation percentage, fund-count limit, per-fund cap, candidate-count minimum, risk mapping, score weight, score threshold, concentration limit, look-through coverage threshold, freshness/staleness duration, SIP minimum/increment, reserve period, AUM floor/ceiling, manager-tenure requirement, benchmark mapping, refresh cadence or other investment/operational threshold may be introduced as a universal code or document default merely because it is conventional or appeared in an earlier proposal. Such values must come from an approved, versioned, effective-dated policy/IPS or authoritative source, with provenance, scope, owner/reviewer and validation. If a required value is absent, invalid, stale, conflicting or out of scope, the affected decision must HOLD / NO_ACTION and preserve affected budget as unallocated. Do not silently substitute zero, a generic default, a fallback category, another category's threshold or a prior policy version.

**Source-derived facts are not policy defaults:** scheme identity, category, plan/option, benchmark, NAV, AUM, TER, holdings, issuer/sector classification, scheme lifecycle, SIP operational terms, trading sessions and disclosure dates must be acquired from authoritative, dated sources and validated for the exact scheme/security and effective period. Do not infer them from names, synthetic fixtures, LLM output or unrelated records. A source's publication cadence is observed and monitored; it is not a hard-coded assertion that evidence is fresh.

**Calculation determinism:** formulas, units, denominator, date alignment, rounding mode/scale, missing-data semantics and tie-breaking must be explicit and versioned. Financial amounts and units use Decimal arithmetic end-to-end; round only at the specified policy boundary. Every requested rupee must reconcile to allocated plus unallocated rupees exactly after the approved rounding operation.

**Configuration contract:** every configurable policy value must be present in the validated policy object used for the decision, and the decision trace must bind its policy ID/version/digest/effective date and resolved values. No hidden environment fallback or duplicated local mapping is permitted. Environment variables may identify locations, credentials or deployment wiring; they must not silently become an unreviewed investment policy.

**Examples are non-operative:** numbers, scheme names, benchmark names, dates, file names and sample JSON are illustrative unless explicitly identified as a currently approved policy/source contract. Example values must never be promoted to runtime defaults. Any fixed numeric threshold or benchmark list in a legacy section is historical/example material pending explicit approval and migration into the effective policy/source registry; it is not authority to hardcode that value.

**Conflict resolution:** apply the decision register, then the normative architecture, then the approved effective policy/IPS for investor-specific values, then authoritative source evidence for market facts. Policy cannot override source facts and source facts cannot invent policy. Record unresolved conflicts and HOLD; do not pick whichever value makes the workflow pass.
