# SIP Recommendation Readiness — Focused Remediation Plan

**Scope:** Fresh-money monthly SIP recommendation only.  
**Working branch:** `main` only.  
**Audit baseline:** `a2295a8f3d1ca792ea5b02bd18bf25d1091576d2` (2026-11-04).  
**Status:** NOT READY — implementation and research controls require remediation.

This document is deliberately limited to the SIP recommendation path. It does not authorize production use, execution, redemption, tax transition planning or lumpsum deployment.

## 1. SIP path in scope

The principal deterministic path is:

1. `compute_deterministic_sip_blueprint()` — validates inputs, derives SIP equity/debt routing, constructs the monthly plan and enforces whole-plan hold behaviour.
2. `select_autonomous_blueprint_funds()` — maps policy sleeves to candidate categories, runs eligibility gates and chooses a candidate.
3. `check_eligibility_gates()` — checks candidate-level identity, concentration, performance, risk, data, manager and Direct-plan evidence.
4. `compute_multi_horizon_fiduciary_score()` / `calculate_candidate_6_pillar_score()` — ranks eligible candidates.
5. `DeterministicSIPPlan` and `generate_cash_and_sip_plan()` — carry the result to the report.

## 2. Verified findings from source inspection

| ID | Severity | Finding | Consequence |
|---|---|---|---|
| SIP-001 | P0 | Selector calls `compute_multi_horizon_fiduciary_score(candidate)` without passing the candidate category or portfolio overlap. | The scorer defaults to Healthcare anchors and zero overlap, so category context and actual portfolio fit do not affect selection. |
| SIP-002 | P0 | Scoring substitutes numeric defaults for absent alpha, 1Y return, Sharpe, TER, buffer and overlap inputs. | An incomplete candidate can receive a plausible composite score instead of being rejected or marked unscorable. |
| SIP-003 | P0 | `compute_candidate_portfolio_overlap()` is not called by the SIP selection path. Its present implementation also equal-weights holdings and candidate stocks when weights are absent. | The advertised marginal portfolio benefit is not established by actual stock weights. |
| SIP-004 | P0 | `fund_universe_requirements.min_candidate_universe_size = 30` is documented in policy, but the SIP selector does not enforce it. | A very small/incomplete candidate universe can still produce a selected fund. |
| SIP-005 | P1 | `sip_allocation_policy.max_fund_allocation_pct`, `min_sip_per_fund_inr`, `sip_increment_inr`, `max_new_funds_per_12_months` and `max_core_fund_count` are configured but are not consistently enforced by the deterministic SIP construction path. | Generated SIP amounts may violate the central policy or client operational constraints. |
| SIP-006 | P1 | The candidate selector evaluates the AMC concentration gate using existing holdings, but the SIP pipeline must prove that the holding data supplied to it is complete and reconciled before treating the gate as passed. | Missing AMC attribution can cause false comfort or blanket rejection; the source/reconciliation state must be explicit. |
| SIP-007 | P1 | The six-pillar score uses fixed category anchors and rewards defensive buffer and international exposure as generic positive factors for every equity category. | Score design may favour the wrong characteristics and is not a validated category-relative fund-selection model. |
| SIP-008 | P1 | The policy's stated 30-candidate minimum, 20% per-fund cap and default sleeve targets are not yet shown to be mutually feasible. | A policy contradiction may make valid SIP construction impossible or encourage silent reallocation. |
| SIP-009 | P1 | The final plan checks missing Direct status only for positive rounded monthly amounts; the plan model does not itself enforce allocated + unallocated = requested budget or exact percentage reconciliation. | Edge cases involving small budgets, rounding or malformed plan construction need explicit invariants. |
| SIP-010 | P0 — partially fixed | Selector and SIP-plan construction now have distinct mid-cap and small-cap sleeves, with SAA-based split for established portfolios and SAA-proportional split of the starter combined mid/small budget. | The new small-cap category currently has no approved category scoring anchor, so candidates remain unscorable and the dependent plan must stay on hold until a defensible small-cap research model is approved. |

## 3. Implementation progress on `main`

**Latest repository HEAD at this update:** `e419405153b78a0570d64976ac3e4c6b8ab4889e`. The code changes below were fully CI-verified on `07c7a2f102e45952003ed59fa864c7c63e4d3450`; the later HEAD change only updates this audit document.

| Finding | Progress | Remaining work |
|---|---|---|
| SIP-001 | Partially fixed: selector passes a category-specific scoring key; unsupported categories no longer inherit Healthcare anchors. | Actual portfolio overlap is still not passed into the score; debt and unsupported thematic categories still lack a dedicated model. |
| SIP-002 | Partially fixed: alpha, 1Y return, Sharpe and TER are required; absent optional pillars are neutral rather than fabricated. | Evidence provenance/freshness must be enforced at the metric level; scoring methodology itself still needs redesign and independent validation. |
| SIP-003 | Open. | Weighted holdings look-through is not yet connected to SIP selection and its current equal-weight assumptions are not acceptable. |
| SIP-004 | Partially fixed: selector now holds all slots when the supplied universe is below the policy minimum of 30. | Category coverage, universe completeness and source freshness are not yet enforced. |
| SIP-005 | Open. | Resolve and implement per-fund cap, minimum ticket, increment, new-fund-count and core-fund-count constraints. |
| SIP-006 | Open. | Prove holdings/AMC attribution completeness and reconciliation before concentration gates can pass. |
| SIP-007 | Open. | Replace arbitrary anchors/weights with an investor-approved, benchmark-consistent research model. |
| SIP-008 | Open. | Resolve the policy contradiction between sleeve weights and the 20% per-fund cap. |
| SIP-009 | Open. | Add plan-level exact amount and percentage invariants. |
| SIP-010 | Partially fixed — P0. | Separate mid-cap and small-cap allocations are now routed as distinct slots. |

**Mid/small sleeve implementation:** commits `2526d25`, `b23ace6`, `6ad94d2`, `38a8fcd`, `9de9147` and `b16049e` add separate Mid Cap and Small Cap selector slots, pass them into SIP plan construction, preserve the starter combined mid/small policy while splitting by SAA proportions, and require fail-closed verification for each positively weighted sleeve. The selector unit test uses a stub scorer to verify category routing; it does **not** validate a real small-cap scoring model. The current scoring anchor table has no `Small Cap` entry, intentionally preventing a live small-cap ranking from being invented. The production SIP therefore remains blocked for any mandate with a positive small-cap target until the benchmark-consistent small-cap research model is validated.

**CI evidence:** `07c7a2f` — full suite 138 passed / 31 skipped; fiduciary invariants 15 passed / 1 skipped; correctness regressions 77 passed / 30 skipped. This is software verification, not research or production approval.

## 4. Non-negotiable SIP acceptance criteria

A SIP recommendation may be marked research-ready only when all of the following are demonstrated:

- Investor mandate, horizon, goals, risk capacity, cash-flow budget and required IPS authorizations are present and internally consistent.
- Existing holdings and transactions reconcile to the authoritative CAS/ledger snapshot; holdings, scheme identities, AMC, plan, ISIN and asset-class mappings are verified.
- Candidate universe is complete for the declared scope, category-balanced, dated and provenance-backed. The policy minimum is enforced, not merely documented.
- Eligibility is a hard pre-ranking gate. Missing, stale, conflicting or unsupported evidence cannot be converted to a passing value.
- Ranking uses correct category/benchmark identity, consistent observation periods, source-backed metrics and a documented scoring model with sensitivity analysis.
- Portfolio overlap and sector/factor exposure use actual constituent weights and reconciled portfolio weights. Unknown coverage is UNKNOWN, not zero.
- Fund selection explains why the selected candidate is better suited than eligible alternatives and identifies the trade-offs. A numerical score alone is insufficient.
- SIP routing separates strategic asset allocation from fresh-cash routing, applies explicit IPS overrides, and never silently redistributes an unfilled sleeve.
- Per-fund, category, AMC, thematic, minimum-ticket, increment and new-fund-count constraints are either enforced or explicitly marked not applicable with a reason.
- Monthly amounts reconcile exactly: allocated + unallocated = requested monthly budget. Percentages reconcile to the routed equity/debt budgets within a documented rounding tolerance.
- Any positive allocation to a missing, unverified or failed candidate blocks the entire dependent proposal or leaves that sleeve explicitly unallocated, according to policy.
- Output distinguishes VERIFIED, PROVISIONAL, MISSING, STALE, CONFLICTING and UNAVAILABLE evidence; all proposals remain non-executable until separate approval.
- Regression, property and boundary tests cover risk tiers, starter/established portfolios, zero/small budgets, rounding, missing slots, incomplete universes, stale data, duplicate identities and policy contradictions.

## 5. Remediation sequence

1. **P0 — Correct scoring inputs and evidence semantics:** remove silent defaults; pass the actual category; prohibit unsupported zero-overlap assumptions; return an explicit unscorable/NO_ACTION state when required metrics are absent.
2. **P0 — Enforce candidate-universe completeness:** validate the declared universe scope, minimum size, category coverage, duplicate identities and source freshness before selection.
3. **P0 — Establish real portfolio look-through:** define weighted constituent and sector/factor data contracts; reconcile holdings coverage; block fit scoring when coverage is insufficient.
4. **P0 — Validate ranking methodology:** replace arbitrary anchors/weights with a documented, benchmark-consistent, category-specific model; test rank stability and sensitivity.
5. **P1 — Enforce SIP allocation constraints:** resolve contradictions among fund caps, sleeve weights, minimum SIP, increments and new-fund limits; implement deterministic constrained allocation with explicit unallocated residual.
6. **P1 — Strengthen plan invariants and report traceability:** exact amount reconciliation, allocation percentages, evidence lineage, candidate rejection matrix and reproducible decision hash.
7. **Release gate:** run the full test suite and targeted synthetic/private-data integration tests on one exact `main` commit; independent review remains required.

## 6. Change discipline

- All changes are committed directly to `main`; do not create feature branches.
- One issue or tightly coupled issue group per commit.
- Add regression tests before or with each behavioural fix.
- Do not change unrelated tax, redemption, lumpsum, UI or general production-readiness work.
- Do not weaken fail-closed behaviour to make a SIP appear.
- A passing test suite is necessary but does not establish investment merit or legal/compliance approval.

## 7. Current conclusion

The SIP code has a deterministic allocation builder, eligibility checks and a report path, but the current ranking path does not yet use the promised category and portfolio-fit context, policy constraints are not fully enforced, and universe/constituent evidence requirements are not complete. Therefore it is **not ready to issue actionable or production SIP recommendations**.
