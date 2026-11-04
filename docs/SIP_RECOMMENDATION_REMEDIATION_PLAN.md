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
| SIP-001 | P0 | Category-aware scoring and evidence-backed portfolio overlap are now wired into selection. | Category-specific methodology still needs benchmark-consistent independent validation; unsupported debt/thematic categories must remain unscorable. |
| SIP-002 | P0 | Scoring substitutes numeric defaults for absent alpha, 1Y return, Sharpe, TER, buffer and overlap inputs. | An incomplete candidate can receive a plausible composite score instead of being rejected or marked unscorable. |
| SIP-003 | P0 | SIP selector now calls `compute_candidate_portfolio_overlap()` using explicit constituent weights and value-weighted existing holdings. | Upstream CAS/fund data ingestion does not yet populate and attest complete constituent weights; missing evidence correctly blocks candidate ranking. |
| SIP-004 | P0 | Selector now holds all slots when the supplied universe is below the configured minimum of 30. | Category coverage, universe completeness, deduplication and source freshness are not yet enforced. |
| SIP-005 | P1 | The deterministic SIP path now enforces the per-fund allocation cap, minimum ticket, increment and maximum active core-fund count as whole-plan fail-closed controls. The 12-month new-fund introduction limit remains unenforced because the input contract has no verified rolling-12-month introduction history. | Operational violations withhold the full budget; the new-fund limit cannot be truthfully evaluated until dated introduction history is supplied. |
| SIP-006 | P1 | The candidate selector evaluates the AMC concentration gate using existing holdings, but the SIP pipeline must prove that the holding data supplied to it is complete and reconciled before treating the gate as passed. | Missing AMC attribution can cause false comfort or blanket rejection; the source/reconciliation state must be explicit. |
| SIP-007 | P1 | The six-pillar score uses fixed category anchors and rewards defensive buffer and international exposure as generic positive factors for every equity category. | Score design may favour the wrong characteristics and is not a validated category-relative fund-selection model. |
| SIP-008 | P1 | The policy's stated 30-candidate minimum, 20% per-fund cap and default sleeve targets are not yet shown to be mutually feasible. | A policy contradiction may make valid SIP construction impossible or encourage silent reallocation. |
| SIP-009 | P1 | `DeterministicSIPPlan` now validates finite/non-negative amounts, allocated + unallocated budget reconciliation, percentage bounds and item-percentage reconciliation. | Runtime test suite must confirm all existing construction paths satisfy the stricter contract; sub-paise/cent rounding tolerance remains 0.01 INR and 0.11 percentage points. |
| SIP-010 | P0 — partially fixed | Selector and SIP-plan construction now have distinct mid-cap and small-cap sleeves, with SAA-based split for established portfolios and SAA-proportional split of the starter combined mid/small budget. | The new small-cap category currently has no approved category scoring anchor, so candidates remain unscorable and the dependent plan must stay on hold until a defensible small-cap research model is approved. |

## 3. Implementation progress on `main`

**Latest repository HEAD at this update:** `e419405153b78a0570d64976ac3e4c6b8ab4889e`. The code changes below were fully CI-verified on `07c7a2f102e45952003ed59fa864c7c63e4d3450`; the later HEAD change only updates this audit document.

| Finding | Progress | Remaining work |
|---|---|---|
| SIP-001 | Partially fixed: selector passes category-specific scoring context and evidence-backed portfolio overlap. | Category research methodology still needs benchmark-consistent validation; unsupported debt/thematic categories remain unscorable. |
| SIP-002 | Partially fixed: alpha, 1Y return, Sharpe and TER are required; absent optional pillars are neutral rather than fabricated. | Evidence provenance/freshness must be enforced at the metric level; scoring methodology itself still needs redesign and independent validation. |
| SIP-003 | Partially implemented in code: SIP selection now passes candidate-to-portfolio overlap into scoring using explicit constituent weights and current holding values. Missing/partial evidence returns UNKNOWN and excludes the candidate; it is never treated as zero. | The ingestion/data-provider path does not yet populate and attest complete constituent weights for CAS holdings and candidate funds. Integration with real factsheet/portfolio disclosures, security identifiers, effective dates and coverage reconciliation remains open. |
| SIP-004 | Partially fixed: selector now holds all slots when the supplied universe is below the policy minimum of 30. | Category coverage, universe completeness and source freshness are not yet enforced. |
| SIP-005 | Partially implemented; not closed. | Four controls are enforced. Add a verified rolling-12-month fund-introduction history contract before enforcing the remaining limit. |
| SIP-006 | Open. | Prove holdings/AMC attribution completeness and reconciliation before concentration gates can pass. |
| SIP-007 | Open. | Replace arbitrary anchors/weights with an investor-approved, benchmark-consistent research model. |
| SIP-008 | Open; now fail-closed. | The one-fund-per-sleeve construction can exceed the 20% per-fund cap. It now withholds the whole SIP rather than silently violating the cap; multi-fund sleeve construction or a formally approved policy change is still required. |
| SIP-009 | Implemented in model. | Added plan-level budget and percentage invariants; CI validation pending for all callers. |
| SIP-010 | Partially fixed — P0. | Separate mid-cap and small-cap allocations are now routed as distinct slots. |

**Mid/small sleeve implementation:** commits `2526d25`, `b23ace6`, `6ad94d2`, `38a8fcd`, `9de9147` and `b16049e` add separate Mid Cap and Small Cap selector slots, pass them into SIP plan construction, preserve the starter combined mid/small policy while splitting by SAA proportions, and require fail-closed verification for each positively weighted sleeve. The selector unit test uses a stub scorer to verify category routing; it does **not** validate a real small-cap scoring model. The current scoring anchor table has no `Small Cap` entry, intentionally preventing a live small-cap ranking from being invented. The production SIP therefore remains blocked for any mandate with a positive small-cap target until the benchmark-consistent small-cap research model is validated.

**CI evidence:** `509b934` — full suite 138 passed / 31 skipped; fiduciary invariants passed; correctness regressions passed; policy/static validation passed; dependency lock and benchmark-fixture integrity checks passed. Earlier baseline `07c7a2f` had the same full-suite count before the sleeve split. This is software verification, not research or production approval.

**Portfolio look-through implementation:** commits `fe3cfa2`, `4b4e841`, `41de051` and `c8c9f41` add explicit constituent-weight fields to `HoldingItem`, replace equal-weight overlap assumptions with value-weighted constituent overlap, pass the result into candidate scoring, and fail closed for missing/partial constituent evidence. The implementation is only usable when the upstream candidate and holding data contain complete, source-verified constituent maps (`constituent_weights` plus `constituent_weights_coverage_pct`). The current repository ingestion path has not yet been shown to populate these fields from current official fund portfolio disclosures. This closes the silent-zero defect, not the end-to-end data integration requirement.

**Investor risk profile handling:** the standard `RiskTier` values are mapped explicitly to the current six-level SAA policy (Conservative → Tier 2, Moderate → Tier 4, Aggressive → Tier 6). `Custom` now fails closed in fund selection rather than inheriting Tier 6. `AssetAllocationTarget` now rejects negative/out-of-range, non-finite or non-reconciling custom equity/debt/cash weights; a valid custom SAA must total 100%. Commits `e2299bd`, `6f025d7` and `77854f7` implement the selector fail-closed behaviour and custom-SAA validation. This does not complete the 3+1 public SIP contract: `compute_deterministic_sip_blueprint()` still accepts the legacy six-level `risk_tier` input, parses it as a SEBI-style tier, and does not accept/use a custom SAA. Investor suitability and fund Riskometer ceiling remain conflated in parts of the SIP path; this must be separated before recommendations can be released.

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


**SIP plan reconciliation implementation:** commits `2551127`, `ed63c0b` and `d15be2d` add model-level checks that all monetary values and allocation percentages are finite and non-negative, percentage fields stay within bounds, item percentages reconcile to equity + debt SIP percentages, and allocated plus explicitly unallocated monthly amounts reconcile to the requested budget. Regression cases cover mismatch, valid full hold/unallocated budget, and non-finite budget values. This is not proof of full end-to-end feasibility: fund caps, minimum tickets, increments and category-level SAA compatibility remain separate open controls.

**SIP-005 implementation note (commits `a94803e` and `3a7413f`):** positive SIP lines are checked against the configured per-fund percentage cap, minimum rupee ticket, rupee increment and maximum core-fund count. Any violation withholds the entire monthly budget and sets all line amounts to zero; no rejected amount is redistributed. The `max_new_funds_per_12_months` control is deliberately not guessed from current holdings: the present request contract does not provide a verified dated history of new-fund introductions. SIP-008 remains open because current one-fund-per-sleeve sizing can exceed the 20% cap; the system now blocks such a plan instead of silently breaching policy.
