# Fiduciary Wealth Engine — Verification and Release Status

**Report date:** 2026-11-04  
**Branch:** `main`  
**Release decision:** **NOT APPROVED FOR PRODUCTION**  
**Permitted operating mode:** Read-only research and synthetic-test development only  
**Execution authority:** None. The application must not place, stage, or transmit investment orders.

> This report supersedes earlier verification claims in this file. Historical portfolio values, client identifiers, folio details, tax calculations and recommendation tables have been removed. Do not restore client-specific information to tracked documentation.

## 1. Current release position

No production approval is granted by this report. A green unit-test run alone is not sufficient for a fiduciary decision-support system. The following evidence must all be available for the exact release commit:

| Gate | Required evidence | Current assessment |
|---|---|---|
| P0 invariant tests | Complete test run, no unexplained skips | Passed on verified `main` SHA `9d9b14b1856c52731555ba2a215a9c272dfdd71e` (CI run `41710708849`) |
| Correctness regressions | Complete test run and passing property/boundary tests | Regression suite passed on current SHA (CI run `41710708849`); broader property/boundary coverage remains incomplete |
| Universal policy validation | All checks run against the authoritative policy, no contradictory hardcoded values | Passed on current SHA (CI run `41710708849`) |
| Tax classification | Versioned statutory rules, verified source documents, scheme structure, acquisition/transfer dates and complete observation evidence | Provisional; not tax-advice ready |
| Benchmark alpha | Authenticated daily TRI observations and independently sourced NSE session calendar | **Blocked** |
| Portfolio look-through | Dated scheme constituents, identifiers, cash/derivative treatment and independently reconciled weights | Not established |
| Client-data protection | Private data excluded from the working tree and historical Git objects purged | Working-tree cleanup performed; history purge not established |
| Reproducible build | Locked dependencies, clean checkout, deterministic release artifact | Hash-locked install, `pip check`, `pip-audit` and clean-checkout tests passed on current SHA; deterministic release artifact not established |
| Release controls | Protected `main`, mandatory status checks and controlled release approval | Not established; branch protection was not enabled at last inspection |

## 2. Verification evidence for current `main`

Latest fully verified `main` at report preparation: `9d9b14b1856c52731555ba2a215a9c272dfdd71e`.

- CI run `41710708849` completed successfully with all six jobs: dependency-lock consistency, P0 fiduciary invariants, correctness regressions, full repository test suite, policy/static validation (including compileall, PDF export and clean-checkout privacy tests), and TRI fixture integrity / expected fail-closed release gate.
- Security run `41710709237` completed successfully: hash-locked dependency installation, `pip check`, `pip-audit`, CycloneDX SBOM generation and artifact retention. The retained SBOM artifact digest is `sha256:90046db4e58d882f5cca9f0ecc6012b1567563cef153559ef0c713ef09d89003`.
- These runs establish that the listed automated jobs passed on that SHA. They do not establish legal correctness, production data readiness, complete property-test coverage, independent security review, or production approval.

## 3. Non-negotiable safety controls

1. Missing, stale, conflicting or incomplete financial inputs must produce a structured unavailable / NO ACTION state. They must never be replaced with fabricated values, scheme names, exposure estimates or inferred tax classifications.
2. An allocation target is not a fund recommendation. A selected fund requires a current, complete, source-backed candidate record and every applicable eligibility gate.
3. Any missing required slot blocks the whole deployment proposal. Funds must not be silently redistributed into another slot.
4. The investor's mandate is an independent release gate. A HOLD mandate makes every recommendation non-actionable.
5. Tax and benchmark calculations are only as reliable as the underlying source evidence. A checksum proves file integrity, not source authenticity or data correctness.

## 4. Statutory tax evidence

The code distinguishes equity-oriented classification from specified-mutual-fund classification and uses different effective-date regimes. This does not, by itself, establish legal correctness.

A release requires legal review of the applicable Act, Rules and CBDT materials, and evidence for each scheme and relevant financial year. In particular:

- Section 198 equity-oriented status requires the prescribed monthly opening/closing calculation and the correct direct-fund or qualifying fund-of-funds test.
- Original Section 50AA uses its applicable domestic-equity definition and the relevant acquisition/transfer dates.
- Section 76 applies from its commencement date and requires the applicable debt/money-market or fund-of-funds test, using the prescribed annual-average daily closing evidence.
- Market-linked debentures must be identified as instruments; they must not be represented as mutual-fund units.
- The tax planner rejects point-in-time percentages and wrong-financial-year evidence. Its current reviewer-attestation fields are provisional workflow controls only; they do not authenticate source documents. Tax-advice release remains blocked until a trusted source-authentication pipeline and independent adviser approval exist.

Synthetic fixtures test arithmetic and edge conditions only. They are not statutory source evidence.

## 5. Benchmark and performance evidence

The benchmark subsystem is **not release-eligible** until it has:

- official historical daily Total Return Index observations for each selected benchmark;
- source document URL, retrieval date, file digest and index identifier;
- an independently verified NSE trading-session calendar covering the full cash-flow window;
- exact handling of non-trading-day cash flows, terminal valuation, dividends, switches and STPs;
- independently reconciled investor cash flows and an independent XIRR calculation.

Monthly observations interpolated to daily dates are not daily TRI data. They must never be used to claim matched benchmark alpha or rank funds.

## 6. Client-data handling

Client-specific configuration, CAS statements, transaction ledgers, folio identifiers, tax information and portfolio metrics belong outside version control. Use a local directory supplied through `MF_CLIENT_DATA_DIR`. Commit only schemas, empty examples and synthetic test fixtures.

Removing files from the current branch does **not** remove their contents from earlier Git commits, clones, caches or downloaded artifacts. Historical Git objects still require a controlled history rewrite and a post-rewrite exposure review. Treat previously committed information as exposed to every party who had repository access during that period.

## 7. Production release checklist

The release owner must attach evidence for all of the following before approval:

- [ ] Current `main` SHA and clean, reproducible checkout
- [ ] P0 invariant tests passing
- [ ] Correctness regression tests passing
- [ ] Property-based and boundary tests passing
- [ ] Universal policy checks passing
- [ ] Full tax/legal review with source evidence
- [ ] Benchmark provenance and coverage gate passing
- [ ] Candidate universe completeness and constituent look-through reconciliation
- [ ] Full workflow exercised on an authorized private client dataset
- [ ] Every output carries the mandate state and non-executable status
- [ ] No client information in tracked files, artifacts, logs or Git history
- [ ] Dependency lockfile and security/dependency review
- [ ] Protected branch and mandatory status checks enabled
- [ ] Independent reviewer approval and release sign-off

**Final decision:** Until every applicable gate is evidenced against the same release commit, this repository is a development-stage decision-support prototype, not a production fiduciary recommendation engine.
