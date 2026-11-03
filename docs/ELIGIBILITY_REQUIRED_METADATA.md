# Eligibility Gate Required Metadata

The active-fund eligibility engine uses fail-closed controls. A missing field must not be interpreted as zero exposure, zero concentration, a Direct plan, or a successful gate.

## Required candidate fields

| Field | Purpose | Behaviour when missing/invalid |
|---|---|---|
| `amc_name` | Exact AMC identity for concentration aggregation | Gate 1 fails |
| `aum_crore` | AUM threshold and category ceiling | Gate 2 fails |
| `top10_concentration_pct` | Top-ten issuer concentration | Gate 3 fails |
| `single_sector_weight_pct` | Sector concentration for diversified funds | Gate 3 fails |
| `sharpe_3y`, `alpha_3y` | Active-fund quantitative hurdle | Gate 4 fails |
| `downside_capture_ratio`, `upside_capture_ratio` | Capture asymmetry | Gate 5 fails |
| `riskometer_score` | SEBI riskometer tier, integer 1–6 | Gate 6 fails |
| `confidence_score` / verified provenance | Data quality | Gate 7 fails |
| `manager_tenure_years`, `track_record_years` | Manager and scheme history | Gate 8 fails |
| `allocation_pct` | Portfolio-level thematic allocation; required only for thematic/sectoral candidates | Gate 9 fails for thematic candidate |
| `is_direct` or explicit `plan` | Direct-plan mandate | Gate 10 fails |

All numeric inputs must be finite. Percentages must be within 0–100 unless a field has a more restrictive validated range.

## Required current-holding metadata

`HoldingItem.amc_name` must be populated from an authoritative scheme master. AMC names are compared exactly after case normalization; they are never guessed from the first word of a scheme name.

## Tax lot classification

The equity-oriented tax transition planner requires verified scheme-level `equity_allocation_pct` (0–100). It may be passed through `load_transactions(..., equity_allocation_by_fund=...)` keyed by exact CAS scheme name, or carried on a transaction row. Do not infer the value from the scheme name.

Non-equity/debt tax treatment is intentionally unsupported by the equity exemption planner until acquisition-date regime, instrument classification and investor-slab inputs are supplied.

## Current repository data limitation

The existing investor fund-metrics file does not contain complete AMC metadata and the CAS transaction ledger does not contain scheme equity-allocation percentages. Consequently, some candidate eligibility and tax outputs will be unavailable until those fields are sourced and reconciled. This is an intentional fail-closed result, not a data value of zero.


## SIP deployment when any required slot fails

The policy target percentages are retained for diagnosis. If any slot with a positive target amount lacks an explicitly verified Direct-plan candidate, the entire monthly budget is withheld; all item-level monthly amounts are set to zero and the sum is reported in `unallocated_budget_inr`. The engine does not redistribute the amount to remaining slots. The user interface must show requested budget, actual allocation and unallocated balance separately.
