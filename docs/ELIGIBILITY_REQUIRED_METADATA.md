# Eligibility Gate Required Metadata

The active-fund eligibility engine uses fail-closed controls. This metadata catalogue does not itself define universal eligibility thresholds, score weights, AUM floors, tenure requirements, concentration limits or freshness windows; those are resolved from the effective approved policy and exact source records. A missing field must not be interpreted as zero exposure, zero concentration, a Direct plan, or a successful gate.

## Required candidate fields

| Field | Purpose | Behaviour when missing/invalid |
|---|---|---|
| `amc_name` | Exact AMC identity for concentration aggregation | Gate 1 fails |
| `aum_crore` | Source-derived AUM input; applicable limits come from effective category policy | Missing/invalid source evidence or required policy blocks the gate |
| `top10_concentration_pct` | Top-ten issuer concentration | Gate 3 fails |
| `single_sector_weight_pct` | Sector concentration for diversified funds | Gate 3 fails |
| `sharpe_3y`, `alpha_3y` | Active-fund quantitative hurdle | Gate 4 fails |
| `downside_capture_ratio`, `upside_capture_ratio` | Capture asymmetry | Gate 5 fails |
| `riskometer_score` | Exact SEBI Riskometer classification for the scheme and effective date | Missing/invalid official evidence blocks the gate; never conflate with investor risk capacity |
| `confidence_score` / verified provenance | Data quality | Gate 7 fails |
| `manager_tenure_years`, `track_record_years` | Manager and scheme history | Gate 8 fails |
| `allocation_pct` | Portfolio-level thematic allocation; required only for thematic/sectoral candidates | Gate 9 fails for thematic candidate |
| `is_direct` or explicit `plan` | Direct-plan mandate | Gate 10 fails |

All numeric inputs must be finite and use declared units. Percentage bounds follow the field schema; any narrower bound must come from a validated field contract or effective policy, not an undocumented code constant. Riskometer values must follow the current official source schema.

## Required current-holding metadata

`HoldingItem.amc_name` must be populated from an authoritative scheme master. AMC names are compared exactly after case normalization; they are never guessed from the first word of a scheme name.

## Tax lot classification

The equity-oriented tax transition planner requires verified scheme-level `equity_allocation_pct` (0–100). It may be passed through `load_transactions(..., equity_allocation_by_fund=...)` keyed by exact CAS scheme name, or carried on a transaction row. Do not infer the value from the scheme name.

The `plan_fy_tranches()` API also requires an explicit, verified `prior_ltcg_this_fy` value. Pass zero only after confirming that no eligible LTCG has already been realized during the current financial year. The planner no longer assumes the full exemption is available when this information is missing.

Non-equity/debt tax treatment is intentionally unsupported by the equity exemption planner until acquisition-date regime, instrument classification and investor-slab inputs are supplied.

## Current repository data limitation

The existing investor fund-metrics file does not contain complete AMC metadata and the CAS transaction ledger does not contain scheme equity-allocation percentages. Consequently, some candidate eligibility and tax outputs will be unavailable until those fields are sourced and reconciled. This is an intentional fail-closed result, not a data value of zero.


## SIP deployment when any required slot fails

The policy target percentages are retained for diagnosis. If any slot with a positive target amount lacks an explicitly verified Direct-plan candidate, the entire monthly budget is withheld; all item-level monthly amounts are set to zero and the sum is reported in `unallocated_budget_inr`. The engine does not redistribute the amount to remaining slots. The user interface must show requested budget, actual allocation and unallocated balance separately.


## Cross-document policy and configurability rules (binding)

This document is subordinate to `docs/SIP_ENGINE_DECISION_REGISTER.md` for settled product decisions and `docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md` for normative behaviour. Read it with `IMPLEMENTATION_STATUS.md` for implementation/acceptance status. Historical audit snapshots and remediation plans are evidence/history, not a source of current policy.

**No arbitrary hardcoding:** no allocation percentage, fund-count limit, per-fund cap, candidate-count minimum, risk mapping, score weight, score threshold, concentration limit, look-through coverage threshold, freshness/staleness duration, SIP minimum/increment, reserve period, AUM floor/ceiling, manager-tenure requirement, benchmark mapping, refresh cadence or other investment/operational threshold may be introduced as a universal code or document default merely because it is conventional or appeared in an earlier proposal. Such values must come from an approved, versioned, effective-dated policy/IPS or authoritative source, with provenance, scope, owner/reviewer and validation. If a required value is absent, invalid, stale, conflicting or out of scope, the affected decision must HOLD / NO_ACTION and preserve affected budget as unallocated. Do not silently substitute zero, a generic default, a fallback category, another category's threshold or a prior policy version.

**Source-derived facts are not policy defaults:** scheme identity, category, plan/option, benchmark, NAV, AUM, TER, holdings, issuer/sector classification, scheme lifecycle, SIP operational terms, trading sessions and disclosure dates must be acquired from authoritative, dated sources and validated for the exact scheme/security and effective period. Do not infer them from names, synthetic fixtures, LLM output or unrelated records. A source's publication cadence is observed and monitored; it is not a hard-coded assertion that evidence is fresh.

**Calculation determinism:** formulas, units, denominator, date alignment, rounding mode/scale, missing-data semantics and tie-breaking must be explicit and versioned. Financial amounts and units use Decimal arithmetic end-to-end; round only at the specified policy boundary. Every requested rupee must reconcile to allocated plus unallocated rupees exactly after the approved rounding operation.

**Configuration contract:** every configurable policy value must be present in the validated policy object used for the decision, and the decision trace must bind its policy ID/version/digest/effective date and resolved values. No hidden environment fallback or duplicated local mapping is permitted. Environment variables may identify locations, credentials or deployment wiring; they must not silently become an unreviewed investment policy.

**Examples are non-operative:** numbers, scheme names, benchmark names, dates, file names and sample JSON are illustrative unless explicitly identified as a currently approved policy/source contract. Example values must never be promoted to runtime defaults. Any fixed numeric threshold or benchmark list in a legacy section is historical/example material pending explicit approval and migration into the effective policy/source registry; it is not authority to hardcode that value.

**Conflict resolution:** apply the decision register, then the normative architecture, then the approved effective policy/IPS for investor-specific values, then authoritative source evidence for market facts. Policy cannot override source facts and source facts cannot invent policy. Record unresolved conflicts and HOLD; do not pick whichever value makes the workflow pass.
