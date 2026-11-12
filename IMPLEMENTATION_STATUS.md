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
| Normative scope and policy governance | #39, #50 | Normative documents exist; #50 threshold centralisation implemented; independent approval and residual digest/bundle binding remain | Independent signed baseline approval; caller-supplied policy tampering rejected; one validated policy snapshot/digest bound across screening, allocation and final trace |
| Canonical investor UI/API workflow | #37, #22 | API auth/client-scope/rate-limit primitives present; canonical SIP UI and deployment hardening remain | One clean-checkout investor UI calls the authenticated production API; distributed limits, timeout and deployment controls verified |
| CAS/CGS integrity and source identity | #107, #52 | Core CAS cache safeguards implemented; bypasses/CGS publisher authentication remain | Remove caller opt-outs from strict staging; exact digest path; CGS parity and authenticated publisher evidence |
| Active SIP mandate classification | #106 | Classifier/regressions implemented; production authentication binding remains | Only authenticated current mandates count in service/report; bind owner, folio, scheme, amount/frequency/status and evidence dates |
| Portfolio perimeter and affordability | #23, #31 | Decimal reconciliation/liquidity primitives exist; active service integration and authenticated external evidence remain | Complete or explicitly MF-only perimeter; source-authenticated assets/liabilities/cash-flow; no legacy reserve/missing-as-zero fallback |
| Decimal money contract | #55 | SIP budget/routing and core holding fields use Decimal; legacy ingestion/cache/report paths remain | No float round-trip in SIP production path; exact source precision, units/NAV handling, digest/reconciliation and allocated+unallocated equality |
| Engine-owned bootstrap and promotion | #121 | Bootstrap and signed promotion primitives exist; full source orchestration/validation remains partial | Clean install autonomously acquires complete required source set; exact record validation, manifest, TEST_ONLY isolation, atomic promotion/rollback |
| Public financial-data acquisition | #110 | AMFI NAV and scheme-master acquisition foundation exists; complete market data refresh absent | Approved adapters for complete universe, metrics, disclosures, TRI/calendar; source-specific provenance, category coverage, atomic refresh and rollback |
| Candidate universe and exact scheme identity | #16, #84 | Evidence contract and overlap primitives present; full market coverage/alias provenance absent | Category-complete autonomous discovery; record-level exact identity; authenticated aliases/metrics; strict constituent security-ID reconciliation |
| Category research and scoring | #41 | Versioned anchor artifact exists; TRI fixture remains explicitly provisional | Independently signed/reproduced category anchors; authenticated daily TRI/calendar; source-bound score and final trace |
| Portfolio look-through and marginal exposure | #26 | Weighted stock-overlap and issuer controls partly exist; full security identity/dimensions/integration remain | Stable verified security/issuer IDs; stock/issuer/sector/market-cap/theme/scheme before-after exposure in final decision trace |
| Risk model and incremental SIP routing | #24 | Standard risk mapping and post-contribution routing implemented; positive Custom service path remains | Propagate validated Custom SAA/risk ceiling through eligibility, selection and routing; integrate complete portfolio perimeter |
| Operational SIP feasibility | #34 | Feasibility primitives/tests exist; authoritative operational terms and service integration remain | Dated AMC/RTA lifecycle/SIP terms; joint feasibility before positive allocation; explicit infeasible/unallocated output |
| Recommendation lifecycle | #33 | Privacy-minimal DRAFT digest persistence exists; review/monitoring state machine absent | Append-only DRAFT/REVIEWED/SUPERSEDED/WITHDRAWN; policy-driven re-review; no execution or mandate changes |
| Privacy and external AI boundary | #44 | Partial/open | PII minimisation, consent, no sensitive prompts/cache; AI optional/free-only/narrative-only |
| Owner-operated security remediation | #17, #18 | Open / owner action | Credential rotation and Git-history/artifact purge; main protection, required checks and independent release approval |
| End-to-end SIP acceptance | #145 | Not demonstrated | Actual production API/UI journey; positive TEST_ONLY path and fail-closed cases; exact evidence and policy trace |

### Parked / excluded issues

- #120 — lumpsum workflow, closed as not planned for this SIP release.
- #21 — tax/legal/exit-load work remains open but parked outside the SIP release; related APIs stay disabled.

## 2A. Issue-by-issue reconciliation

The GitHub child issues have been updated with a dated **Current implementation reconciliation — 2026-11-12** section. Each section separates (a) code/tests already present, (b) the precise remaining defect or acceptance gap, and (c) work that must not be repeated. The authoritative task-level details are in the linked issue bodies; this index is intentionally a summary. #50 was renamed and narrowed: central policy loading/validation and rejection of per-call threshold overrides are implemented; only caller-policy digest verification, immutable effective-policy bundle binding and active-policy governance remain. #107 strict validation/envelope/atomic cache replacement is implemented, but caller opt-outs and digest canonicalisation remain. #106 transaction classifier regressions are implemented, but production use of authenticated mandate evidence remains. #52 CAS detected-publisher labelling is no longer authentication; CGS parity and actual publisher authentication remain. #22 API auth/client scope/rate-limit primitives exist; deployment hardening and canonical UI are still required.

**Do not treat the parked #21 tax/legal work or owner-operated #17/#18 administration tasks as the first application-code batch.**

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

The detailed normative calculation/data/API contract is [SIP_DECISION_CALCULATION_AND_DATA_CONTRACTS.md](docs/SIP_DECISION_CALCULATION_AND_DATA_CONTRACTS.md). It documents formulas, input/output semantics, worked examples, acceptance scenarios and code-conformance status. The implementation gaps for post-contribution routing, routing increment source, look-through thresholds, candidate scheme minimums, public risk mappings, Custom risk ceiling, missing investor risk profile, concentration defaults and SIP API Decimal budget ingress have been corrected on main and are covered by regression tests. The remaining gaps are listed in §8 and remain open until their acceptance evidence is demonstrated.

## 8. Code corrections — 2026-11-12

The following corrections are now present on main (code revision: `8ec155d7ad49c5ccbf80a38e8932c9e29fb9904f`; issue/status reconciliation revision: `aff00e2338fce6c07ca34c4cb7a128659993efc0`). These are implementation changes, not a declaration of workstream closure:

- SIP routing now derives post-contribution INR gaps from the P+B perimeter and applies the tolerance on that same base. Unfillable sleeve shares and rounding residue remain unallocated.
- The production routing increment comes from the validated allocation policy. The primitive no longer embeds a numeric increment default.
- Candidate allocation rejects missing or invalid source-backed scheme minimums instead of substituting the general policy minimum.
- SIP API budget input, CAS portfolio totals/sleeves, routing and candidate/issuer overlap value-weighting use Decimal INR arithmetic; API INR amounts serialize as decimal strings.
- Screening policy now governs look-through coverage and constituent-weight reconciliation. Missing investor risk profile fails closed without suppressing diagnostics for the other eligibility gates.
- Public 3+1 risk mapping and SEBI Tier 1–6 profile mapping are policy-owned and consumed by the service/model/math engine. Custom risk ceiling is explicit; the implicit Tier 6 default was removed.
- Legacy candidate concentration controls no longer provide implicit numeric caps; classified caps require explicit policy limits.

**Verification boundary (checked 2026-11-12):** Current main revision `8e81caf168b9481b49d8262bc8e5affa42e0b94a` has green CI (run [43222167137](https://github.com/o0k00l/MF-AI-Based/actions/runs/43222167137)) and Security (run [43222167186](https://github.com/o0k00l/MF-AI-Based/actions/runs/43222167186)). SIP acceptance regression passed on code revision `8ec155d7ad49c5ccbf80a38e8932c9e29fb9904f` (run [43218392925](https://github.com/o0k00l/MF-AI-Based/actions/runs/43218392925)); later commits through `8e81caf` were documentation/issue-tracker updates. Full repository CI passed (**1,275 passed, 34 skipped**) on `8ec155d`. The SIP acceptance regression has not been rerun on the exact current main SHA. The skipped tests include explicitly gated private-CAS integration, tax/exit-load (intentionally disabled), and thematic issuer-taxonomy validation (not yet implemented). These results validate the current automated suite only; they do not certify live data coverage, positive-path research/TRI release, independent NSE calendar, reviewer approval, or production readiness. #50's original central-threshold remediation is implemented; keep it open only for the narrowed residuals recorded in the issue: independently verified effective-policy digest and immutable policy-bundle binding across the full decision. Do not mark #24, #50 or #55 closed until their respective remaining acceptance and end-to-end issue #145 are demonstrated.

**Still open:** source-specific disclosure/evidence freshness (the current disclosure-age default still needs a policy-bound source-specific contract); complete external-asset/liability perimeter and liquidity evidence; full holdings-level issuer/sector/market-cap/theme before/after controls and trace binding; candidate-universe autonomous discovery; research/TRI/NSE calendar independent release gates; reviewer approval; and the production UI/API acceptance workflow.
