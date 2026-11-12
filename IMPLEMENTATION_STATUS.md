# SIP Engine Implementation Status

**Master tracker:** [#144 — SIP-only engine](https://github.com/o0k00l/MF-AI-Based/issues/144)  
**End-to-end acceptance:** [#145](https://github.com/o0k00l/MF-AI-Based/issues/145)  
**Normative architecture:** [v2.1.0](docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md)  
**Decision register:** [SIP_ENGINE_DECISION_REGISTER.md](docs/SIP_ENGINE_DECISION_REGISTER.md)  
**Working branch:** `main` only  
**Updated:** 2026-11-12

This is a verified progress index, not a production approval. "Open" means acceptance is not yet demonstrated; it does not mean no code exists. No module is complete merely because a unit test or a commit exists.

**Status authority and semantics:** this file is the sole implementation-status index for the normative requirements. The architecture specification defines what must be true; the decision register defines which product decisions are fixed. Neither document's normative wording or a `Fixed` decision means the code is complete. Status entries below must be changed only when the corresponding acceptance evidence is verified on `main`; passing a component test or Action alone is insufficient. Where a requirement is only partly implemented, keep it `Partial/open` and state the remaining acceptance evidence.

## 1. Frozen product scope

Current delivery is monthly Indian mutual-fund SIP recommendation only. Lumpsum/STP, tax/exit-load, redemption, switching, ETF recurring-purchase routing without verified operational support, and trade execution are excluded.

Public risk contract:
- Conservative → internal Tier 2
- Moderate → internal Tier 4
- Aggressive → internal Tier 6
- Custom → validated SAA totaling 100% + separate risk ceiling

Investor risk capacity and scheme Riskometer are distinct. Portfolio deficits, holdings-level overlap and marginal exposure determine incremental SIP routing. Numeric caps/minimums/increments/fund counts are effective only through the validated policy/IPS, not hardcoded universal rules.

## 2. Workstream status

The statuses below describe acceptance, not whether files or partial code exist. `Open` / `Partial/open` means the stated acceptance criteria have not yet been fully demonstrated. Do not infer closure from the normative traceability matrix in the architecture specification.

| Workstream | Issues | Status | Required evidence to close |
|---|---|---|---|
| Normative scope and policy governance | #39, #50 | Baseline documented; runtime reconciliation open | Architecture/decision register reconciled to code, policy, tests and report; one effective policy object/digest |
| Canonical investor UI/API workflow | #37, #22 | Open | Upload → mandate → reconcile → recommendation/report through one production backend; authenticated API and no duplicate UI logic |
| CAS/CGS integrity and source identity | #107, #52 | Partial/open | Malformed values rejected before cache; structural validity separate from authenticated publisher |
| Active SIP mandate classification | #106 | Partial/open | Authenticated/current mandate evidence; purchases/text patterns not treated as mandates |
| Portfolio perimeter and affordability | #23, #31 | Open | Explicit included/excluded assets, valuation dates, source-backed cash/obligations/reserve; no missing-as-zero or universal reserve default |
| Decimal money contract | #55 | Partial/open | Decimal-only INR/units through ingestion, calculations, routing and serialization; exact budget reconciliation |
| Engine-owned bootstrap and promotion | #121 | Partial/open | Clean bootstrap; manifest-aware runtime path resolution; real adapter orchestration; data-derived validation; signed promotion and atomic rollback |
| Public financial-data acquisition | #110 | Partial/open | AMFI/AMC source adapters; original bytes/digests; dates, freshness, category coverage, cross-source identity reconciliation and last-known-good refresh |
| Candidate universe and exact scheme identity | #16, #84 | Open | Indian market discovery; per-category coverage; exact scheme/plan/option/ISIN/benchmark; provenance for held metrics, aliases and disclosures |
| Category research and scoring | #41 | Open | Approved category-specific benchmark/TRI methodology, multiple rolling horizons, downside/consistency/cost/liquidity metrics, independent review |
| Portfolio look-through and marginal exposure | #26 | Partial/open | Stable security master; strict identity resolution; stock/issuer/sector/market-cap/theme aggregation; verified coverage; before/after marginal exposure |
| Risk model and incremental SIP routing | #24 | Partial/open | 3+1 public risk contract; Custom SAA/risk ceiling end-to-end; post-contribution denominator; no forced category allocation |
| Operational SIP feasibility | #34 | Partial/open | Current scheme lifecycle, subscription, minimum/frequency/cut-off; effective constraints jointly feasible; no silent redistribution |
| Recommendation lifecycle | #33 | Open | Immutable trace versions; stale/changed portfolio triggers review; no automatic SIP changes or execution |
| Privacy and external AI boundary | #44 | Partial/open | PII minimisation, consent, no sensitive prompts/cache; AI optional/free-only/narrative-only |
| Owner-operated security remediation | #17, #18 | Open / owner action | Credential rotation and Git-history/artifact purge; main protection, required checks and independent release approval |
| End-to-end SIP acceptance | #145 | Not demonstrated | Actual production API/UI journey; positive TEST_ONLY path and fail-closed cases; exact evidence and policy trace |

### Parked / excluded issues

- #120 — lumpsum workflow, closed as not planned for this SIP release.
- #21 — tax/legal/exit-load work remains open but parked outside the SIP release; related APIs stay disabled.

## 3. GitHub Actions contract

| Workflow | Purpose | Required for SIP code changes? |
|---|---|---|
| `CI` | Full repository regression, P0 invariants, provenance, policy validation, dependency-lock consistency and TRI fixture integrity. Push validation is restricted to `main`; manual dispatch is available. | Yes |
| `Security` | Hash-locked dependency audit and SBOM. | Yes for release; configure as required repository check where supported |
| `SIP acceptance regression` | Focused existing SIP, CAS, portfolio, evidence, policy, privacy, benchmark and API tests on relevant changes. | Yes |
| `Optional free AI provider smoke test` | Manual-only live synthetic prompt check; not a financial decision dependency. | No |
| `SIP production release gate` | Exact-main-commit check, lock/dependency checks, P0/full tests, policy/privacy checks, SBOM and signed TRI release evidence in protected production environment. | Release only |

A dedicated scheduled/live market-data refresh Action is intentionally **not** enabled yet. The repository does not yet expose a verified production acquisition command that safely builds the complete fund universe. In particular, `scripts/update_funds.py` and `scripts/create_fund_metrics.py` synthesize identifiers/exposures from CAS scheme names and must not be used as production acquisition. Add a scheduled acquisition workflow only after #110/#121 provide a source-backed, non-synthetic CLI with safe output and rollback semantics.

The SIP workflow currently runs deterministic component regressions. It is **not** the end-to-end acceptance test until #145's actual production-path test is implemented and added to the workflow.

## 4. Main-branch and issue discipline

- Work only on `main`; focused commits reference issue numbers.
- No parallel/long-lived branches or merge clutter.
- The `workinprogress` label has been removed from open issues; the `open` label now reflects their state.
- Child issues remain open until their own acceptance evidence is demonstrated and relevant Actions pass on the exact commit.
- GitHub branch protection and independent release approvals require repository-owner settings; workflow YAML cannot configure those settings.
- Do not close or mark done from a green unit-test suite alone.

## 5. Baseline and verification boundary

The workflow run links below are historical evidence only. For a current green/red claim, inspect the latest run for the exact current `main` commit; never carry forward an earlier green result as proof for a later commit.

Before the tracker/Actions corrections, the existing CI and Security workflows passed on commit `0cfbd00408a2ed012af4e1cc62ebbcaa96d98ac4` (CI run [43180628314](https://github.com/o0k00l/MF-AI-Based/actions/runs/43180628314), Security run [43180628283](https://github.com/o0k00l/MF-AI-Based/actions/runs/43180628283)). Those runs are historical baseline evidence and do not validate the later documentation/workflow commits.

The new/updated workflows must run on the resulting commits before their checks can be called green. Even then, fixture tests do not establish live source coverage, authenticated daily TRI, independent NSE calendar, research approval, or production authorization.

**Current release status: NOT APPROVED FOR PRODUCTION.**


## Cross-document policy and configurability rules (binding)

This document is subordinate to `docs/SIP_ENGINE_DECISION_REGISTER.md` for settled product decisions and `docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md` for normative behaviour. Read it with `IMPLEMENTATION_STATUS.md` for implementation/acceptance status. Historical audit snapshots and remediation plans are evidence/history, not a source of current policy.

**No arbitrary hardcoding:** no allocation percentage, fund-count limit, per-fund cap, candidate-count minimum, risk mapping, score weight, score threshold, concentration limit, look-through coverage threshold, freshness/staleness duration, SIP minimum/increment, reserve period, AUM floor/ceiling, manager-tenure requirement, benchmark mapping, refresh cadence or other investment/operational threshold may be introduced as a universal code or document default merely because it is conventional or appeared in an earlier proposal. Such values must come from an approved, versioned, effective-dated policy/IPS or authoritative source, with provenance, scope, owner/reviewer and validation. If a required value is absent, invalid, stale, conflicting or out of scope, the affected decision must HOLD / NO_ACTION and preserve affected budget as unallocated. Do not silently substitute zero, a generic default, a fallback category, another category's threshold or a prior policy version.

**Source-derived facts are not policy defaults:** scheme identity, category, plan/option, benchmark, NAV, AUM, TER, holdings, issuer/sector classification, scheme lifecycle, SIP operational terms, trading sessions and disclosure dates must be acquired from authoritative, dated sources and validated for the exact scheme/security and effective period. Do not infer them from names, synthetic fixtures, LLM output or unrelated records. A source's publication cadence is observed and monitored; it is not a hard-coded assertion that evidence is fresh.

**Calculation determinism:** formulas, units, denominator, date alignment, rounding mode/scale, missing-data semantics and tie-breaking must be explicit and versioned. Financial amounts and units use Decimal arithmetic end-to-end; round only at the specified policy boundary. Every requested rupee must reconcile to allocated plus unallocated rupees exactly after the approved rounding operation.

**Configuration contract:** every configurable policy value must be present in the validated policy object used for the decision, and the decision trace must bind its policy ID/version/digest/effective date and resolved values. No hidden environment fallback or duplicated local mapping is permitted. Environment variables may identify locations, credentials or deployment wiring; they must not silently become an unreviewed investment policy.

**Examples are non-operative:** numbers, scheme names, benchmark names, dates, file names and sample JSON are illustrative unless explicitly identified as a currently approved policy/source contract. Example values must never be promoted to runtime defaults. Any fixed numeric threshold or benchmark list in a legacy section is historical/example material pending explicit approval and migration into the effective policy/source registry; it is not authority to hardcode that value.

**Conflict resolution:** apply the decision register, then the normative architecture, then the approved effective policy/IPS for investor-specific values, then authoritative source evidence for market facts. Policy cannot override source facts and source facts cannot invent policy. Record unresolved conflicts and HOLD; do not pick whichever value makes the workflow pass.


## 6. Detailed specification and observed conformance gaps

The detailed normative calculation/data/API contract is [SIP_DECISION_CALCULATION_AND_DATA_CONTRACTS.md](docs/SIP_DECISION_CALCULATION_AND_DATA_CONTRACTS.md). It documents the calculation contracts, illustrative arithmetic, acceptance scenarios and source-inspected implementation gaps. Its existence does not close any workstream. In particular, the documented gaps around post-contribution routing, default parameters, look-through tolerances, candidate minimums, local risk/sleeve maps, fund-discovery inference/fallbacks, policy fallback values, float budget ingress, engine-owned research acquisition and external evidence-bundle dependence remain OPEN until fixed in code and independently verified on the current main commit. No test changes are authorized by this documentation work.

## 8. Code corrections — 2026-11-12

The following corrections are now present on main (verified source revision: 8ec155d7ad49c5ccbf80a38e8932c9e29fb9904f). These are implementation changes, not a declaration of workstream closure:

- SIP routing now derives post-contribution INR gaps from the P+B perimeter and applies the tolerance on that same base. Unfillable sleeve shares and rounding residue remain unallocated.
- The production routing increment comes from the validated allocation policy. The primitive no longer embeds a numeric increment default.
- Candidate allocation rejects missing or invalid source-backed scheme minimums instead of substituting the general policy minimum.
- SIP API budget input, CAS portfolio totals/sleeves, routing and candidate/issuer overlap value-weighting use Decimal INR arithmetic; API INR amounts serialize as decimal strings.
- Screening policy now governs look-through coverage and constituent-weight reconciliation. Missing investor risk profile fails closed without suppressing diagnostics for the other eligibility gates.
- Public 3+1 risk mapping and SEBI Tier 1–6 profile mapping are policy-owned and consumed by the service/model/math engine. Custom risk ceiling is explicit; the implicit Tier 6 default was removed.
- Legacy candidate concentration controls no longer provide implicit numeric caps; classified caps require explicit policy limits.

**Verification boundary:** Exact HEAD 8ec155d has green GitHub Actions: full repository CI passed (**1,275 passed, 34 skipped**), SIP acceptance regression passed, and Security passed. The skipped tests include explicitly gated private-CAS integration, tax/exit-load (intentionally disabled), and thematic issuer-taxonomy validation (not yet implemented). These results validate the current automated suite only; they do not certify live data coverage, positive-path research/TRI release, independent NSE calendar, reviewer approval, or production readiness. Do not mark #24, #50 or #55 closed until their remaining acceptance and end-to-end issue #145 are demonstrated.

**Still open:** source-specific disclosure/evidence freshness (the current disclosure-age default still needs a policy-bound source-specific contract); complete external-asset/liability perimeter and liquidity evidence; full holdings-level issuer/sector/market-cap/theme before/after controls and trace binding; candidate-universe autonomous discovery; research/TRI/NSE calendar independent release gates; reviewer approval; and the production UI/API acceptance workflow.
