# SIP Engine Implementation Status

**Master tracker:** [#144 — SIP-only engine](https://github.com/o0k00l/MF-AI-Based/issues/144)  
**End-to-end acceptance:** [#145](https://github.com/o0k00l/MF-AI-Based/issues/145)  
**Normative architecture:** [v2.1.0](docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md)  
**Decision register:** [SIP_ENGINE_DECISION_REGISTER.md](docs/SIP_ENGINE_DECISION_REGISTER.md)  
**Working branch:** `main` only  
**Updated:** 2026-11-12

This is a verified progress index, not a production approval. "Open" means acceptance is not yet demonstrated; it does not mean no code exists. No module is complete merely because a unit test or a commit exists.

## 1. Frozen product scope

Current delivery is monthly Indian mutual-fund SIP recommendation only. Lumpsum/STP, tax/exit-load, redemption, switching, ETF recurring-purchase routing without verified operational support, and trade execution are excluded.

Public risk contract:
- Conservative → internal Tier 2
- Moderate → internal Tier 4
- Aggressive → internal Tier 6
- Custom → validated SAA totaling 100% + separate risk ceiling

Investor risk capacity and scheme Riskometer are distinct. Portfolio deficits, holdings-level overlap and marginal exposure determine incremental SIP routing. Numeric caps/minimums/increments/fund counts are effective only through the validated policy/IPS, not hardcoded universal rules.

## 2. Workstream status

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

Before the tracker/Actions corrections, the existing CI and Security workflows passed on commit `0cfbd00408a2ed012af4e1cc62ebbcaa96d98ac4` (CI run [43180628314](https://github.com/o0k00l/MF-AI-Based/actions/runs/43180628314), Security run [43180628283](https://github.com/o0k00l/MF-AI-Based/actions/runs/43180628283)). Those runs are historical baseline evidence and do not validate the later documentation/workflow commits.

The new/updated workflows must run on the resulting commits before their checks can be called green. Even then, fixture tests do not establish live source coverage, authenticated daily TRI, independent NSE calendar, research approval, or production authorization.

**Current release status: NOT APPROVED FOR PRODUCTION.**
