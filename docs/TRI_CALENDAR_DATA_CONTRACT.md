# TRI and NSE Trading Calendar Data Contract

The release gate requires the complete benchmark set defined by the effective, independently approved category-to-benchmark registry. That registry binds each supported category and exact scheme mapping to official benchmark identity, TRI series, methodology/version, effective dates and reviewer approval. Named benchmarks and scheme mappings in historical releases are examples, not a hard-coded universal list. Missing or conflicting required mappings block the affected comparison/release.

The cash-flow-matched TRI calculation requires two distinct inputs:

1. A daily historical TRI series with a SHA256 checksum over its normalized `levels` mapping.
2. A separately maintained NSE trading-session calendar at `data/policy/nse_trading_calendar.json`.

The engine does **not** generate expected sessions by counting weekdays. NSE holidays and special sessions make weekday arithmetic insufficient.

## Calendar file schema

```json
{
  "exchange": "NSE",
  "status": "VERIFIED",
  "sessions": ["2026-01-01", "2026-01-02"],
  "provenance": {
    "source_url": "https://www.nseindia.com/...",
    "source_document_sha256": "<64 hexadecimal characters>",
    "sessions_sha256": "<SHA256 of compact JSON sessions array>"
  }
}
```

Requirements:

- `sessions` must contain unique, ascending ISO `YYYY-MM-DD` dates.
- The session list must be reconciled against official NSE trading-session/holiday records before `status` is set to `VERIFIED`.
- `source_document_sha256` records the source document digest.
- `sessions_sha256` is SHA256 of `json.dumps(sessions, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8.
- The calendar must cover the entire investor cash-flow window through the requested terminal date.
- A generated weekday list, benchmark series dates, or editable `expected_trading_days` metadata is not an acceptable substitute.

## Fail-closed behaviour

If the calendar file is absent, malformed, checksum-invalid, or does not cover the investor cash-flow window, TRI XIRR/alpha is unavailable. The benchmark JSON's `expected_trading_days` and `coverage_pct` fields are descriptive only and are not used as the coverage denominator.

Daily TRI observations are required. Cash flows on non-trading dates use the preceding session's TRI close; values are not linearly interpolated or extrapolated.

The engine verifies the supplied series/calendar checksums and validates the provenance metadata shape. It does not cryptographically authenticate the source publisher; the returned audit therefore explicitly leaves source authenticity as unverified. Human source review remains a release prerequisite.


## Cross-document policy and configurability rules (binding)

This document is subordinate to `docs/SIP_ENGINE_DECISION_REGISTER.md` for settled product decisions and `docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md` for normative behaviour. Read it with `IMPLEMENTATION_STATUS.md` for implementation/acceptance status. Historical audit snapshots and remediation plans are evidence/history, not a source of current policy.

**No arbitrary hardcoding:** no allocation percentage, fund-count limit, per-fund cap, candidate-count minimum, risk mapping, score weight, score threshold, concentration limit, look-through coverage threshold, freshness/staleness duration, SIP minimum/increment, reserve period, AUM floor/ceiling, manager-tenure requirement, benchmark mapping, refresh cadence or other investment/operational threshold may be introduced as a universal code or document default merely because it is conventional or appeared in an earlier proposal. Such values must come from an approved, versioned, effective-dated policy/IPS or authoritative source, with provenance, scope, owner/reviewer and validation. If a required value is absent, invalid, stale, conflicting or out of scope, the affected decision must HOLD / NO_ACTION and preserve affected budget as unallocated. Do not silently substitute zero, a generic default, a fallback category, another category's threshold or a prior policy version.

**Source-derived facts are not policy defaults:** scheme identity, category, plan/option, benchmark, NAV, AUM, TER, holdings, issuer/sector classification, scheme lifecycle, SIP operational terms, trading sessions and disclosure dates must be acquired from authoritative, dated sources and validated for the exact scheme/security and effective period. Do not infer them from names, synthetic fixtures, LLM output or unrelated records. A source's publication cadence is observed and monitored; it is not a hard-coded assertion that evidence is fresh.

**Calculation determinism:** formulas, units, denominator, date alignment, rounding mode/scale, missing-data semantics and tie-breaking must be explicit and versioned. Financial amounts and units use Decimal arithmetic end-to-end; round only at the specified policy boundary. Every requested rupee must reconcile to allocated plus unallocated rupees exactly after the approved rounding operation.

**Configuration contract:** every configurable policy value must be present in the validated policy object used for the decision, and the decision trace must bind its policy ID/version/digest/effective date and resolved values. No hidden environment fallback or duplicated local mapping is permitted. Environment variables may identify locations, credentials or deployment wiring; they must not silently become an unreviewed investment policy.

**Examples are non-operative:** numbers, scheme names, benchmark names, dates, file names and sample JSON are illustrative unless explicitly identified as a currently approved policy/source contract. Example values must never be promoted to runtime defaults. Any fixed numeric threshold or benchmark list in a legacy section is historical/example material pending explicit approval and migration into the effective policy/source registry; it is not authority to hardcode that value.

**Conflict resolution:** apply the decision register, then the normative architecture, then the approved effective policy/IPS for investor-specific values, then authoritative source evidence for market facts. Policy cannot override source facts and source facts cannot invent policy. Record unresolved conflicts and HOLD; do not pick whichever value makes the workflow pass.
