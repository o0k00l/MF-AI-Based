# Portfolio-aware SIP control primitives

This module adds a deterministic, fail-closed foundation for portfolio-level SIP analysis. It is a reusable calculation layer, not a production recommendation release and not yet wired into the public SIP API.

## Implemented in this tranche

| Control | Function | Safety behavior |
|---|---|---|
| Total-portfolio perimeter | `reconcile_total_portfolio` | Requires explicit perimeter-complete attestation, source references, owner scope and a common valuation date; otherwise HOLD/error |
| SAA drift | `calculate_saa_drift` | Requires exact sleeve match and approved target weights summing to 100% |
| Incremental SIP routing | `route_incremental_sip` | Routes only to eligible underweight sleeves; rounding remainder and unfillable budget stay unallocated |
| Eligibility before scoring | `screen_candidates_before_scoring` | Requires exact scheme identity, dated evidence, evidence reference and PASS for every mandatory gate |
| Look-through aggregation | `calculate_lookthrough_exposure` | Portfolio-weights issuer exposures and returns HOLD below caller-supplied approved coverage |
| Decision trace | `build_decision_trace` | Hashes a versioned source/policy/engine/decision record deterministically |
| Goal suitability inputs | `validate_goal_mandate` | Requires approved goal, target date, target amount, liabilities, source and approved horizon policy |
| Liquidity reserve | `assess_liquidity_and_sip_surplus` | Separates verified cash reserve/obligations from recurring monthly income surplus; missing/stale evidence holds |
| Affordability stress | `stress_test_sip_affordability` | Runs only caller-supplied income/expense shock scenarios; no assumed income growth |
| Scheme operations | `validate_scheme_operational_feasibility` | Requires current scheme status, exact identity, minimum SIP and evidence for exit load, lock-in and subscription status

## Important boundaries

- This code does not authenticate an evidence publisher or independently attest that a declared portfolio perimeter is complete.
- The caller must supply the approved SAA, tolerance, evidence-freshness limit, look-through threshold and candidate eligibility gates. No new investment-policy threshold is invented here.
- A portfolio perimeter marked complete is an explicit upstream attestation, not a conclusion inferred from CAS data.
- Candidate screening returns eligible identifiers only; it does not rank funds or create a positive recommendation. Candidate-specific eligibility and SIP routing are not yet integrated into the API.
- Look-through outputs are exposure calculations only. Candidate incremental exposure and concentration policy still require a separate approved policy integration.
- Automated scheduling/notification and CAS ingestion remain future work; the current lifecycle helper only evaluates supplied dates/events and state transitions.
- `calculate_saa_drift`, `calculate_lookthrough_exposure` and `build_decision_trace` are now used by the live `services/sip_recommendation.py` path and returned as CAS-only diagnostics by `POST /v1/sip/recommendations`. The API still returns HOLD / NO_ACTION and does not route budget because external assets, cash, liabilities, CAS valuation date, client IPS and research/TRI release gates are not yet reconciled.
- No orders, switches, redemptions or broker actions are generated.

## Validation

Run:

```bash
python -m pytest tests/test_portfolio_sip_controls.py -q
```

The tests use synthetic fixtures only and do not validate any real investor portfolio or live fund data.


## Cross-document policy and configurability rules (binding)

This document is subordinate to `docs/SIP_ENGINE_DECISION_REGISTER.md` for settled product decisions and `docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md` for normative behaviour. Read it with `IMPLEMENTATION_STATUS.md` for implementation/acceptance status. Historical audit snapshots and remediation plans are evidence/history, not a source of current policy.

**No arbitrary hardcoding:** no allocation percentage, fund-count limit, per-fund cap, candidate-count minimum, risk mapping, score weight, score threshold, concentration limit, look-through coverage threshold, freshness/staleness duration, SIP minimum/increment, reserve period, AUM floor/ceiling, manager-tenure requirement, benchmark mapping, refresh cadence or other investment/operational threshold may be introduced as a universal code or document default merely because it is conventional or appeared in an earlier proposal. Such values must come from an approved, versioned, effective-dated policy/IPS or authoritative source, with provenance, scope, owner/reviewer and validation. If a required value is absent, invalid, stale, conflicting or out of scope, the affected decision must HOLD / NO_ACTION and preserve affected budget as unallocated. Do not silently substitute zero, a generic default, a fallback category, another category's threshold or a prior policy version.

**Source-derived facts are not policy defaults:** scheme identity, category, plan/option, benchmark, NAV, AUM, TER, holdings, issuer/sector classification, scheme lifecycle, SIP operational terms, trading sessions and disclosure dates must be acquired from authoritative, dated sources and validated for the exact scheme/security and effective period. Do not infer them from names, synthetic fixtures, LLM output or unrelated records. A source's publication cadence is observed and monitored; it is not a hard-coded assertion that evidence is fresh.

**Calculation determinism:** formulas, units, denominator, date alignment, rounding mode/scale, missing-data semantics and tie-breaking must be explicit and versioned. Financial amounts and units use Decimal arithmetic end-to-end; round only at the specified policy boundary. Every requested rupee must reconcile to allocated plus unallocated rupees exactly after the approved rounding operation.

**Configuration contract:** every configurable policy value must be present in the validated policy object used for the decision, and the decision trace must bind its policy ID/version/digest/effective date and resolved values. No hidden environment fallback or duplicated local mapping is permitted. Environment variables may identify locations, credentials or deployment wiring; they must not silently become an unreviewed investment policy.

**Examples are non-operative:** numbers, scheme names, benchmark names, dates, file names and sample JSON are illustrative unless explicitly identified as a currently approved policy/source contract. Example values must never be promoted to runtime defaults. Any fixed numeric threshold or benchmark list in a legacy section is historical/example material pending explicit approval and migration into the effective policy/source registry; it is not authority to hardcode that value.

**Conflict resolution:** apply the decision register, then the normative architecture, then the approved effective policy/IPS for investor-specific values, then authoritative source evidence for market facts. Policy cannot override source facts and source facts cannot invent policy. Record unresolved conflicts and HOLD; do not pick whichever value makes the workflow pass.
