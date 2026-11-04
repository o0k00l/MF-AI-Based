# Indian Mutual-Fund Decision-Support Engine

A Python codebase for analysing Indian mutual-fund portfolios, testing investment-policy rules, reconciling investor-provided data and generating non-executable decision-support reports.

**Release status: NOT APPROVED FOR PRODUCTION.**  
**Execution: disabled.** All plans must remain non-actionable and subject to investor mandate and qualified human review.

This repository contains no intended client portfolio records. Client data must be supplied locally through `MF_CLIENT_DATA_DIR`.

## Design principles

- **Evidence before recommendation:** Every fund metric, scheme identity, portfolio constituent, benchmark observation and tax classification requires source, date, coverage and integrity metadata.
- **Fail closed:** Missing, stale, conflicting or incomplete required data leads to NO ACTION / HOLD. The system must not invent funds, scheme names, tax categories, yields or portfolio exposures.
- **Separate policy concepts:** Strategic asset allocation (SAA), new-SIP routing, current portfolio exposures and authorized satellite allocations are different inputs and must not be substituted for one another.
- **Whole-plan gating:** If a required positive-allocation sleeve lacks a verified Direct-plan candidate, the entire budget remains unallocated. Do not partially invest or silently redistribute it.
- **Tax-lot awareness:** Acquisition date, transfer date, current NAV, scheme-specific exit load and statutory classification must be validated independently for each lot.
- **Benchmark discipline:** Matched TRI alpha is unavailable unless daily authenticated TRI observations and an independently sourced exchange-session calendar cover the full investor cash-flow window.
- **No execution authority:** The engine produces analysis and conditional scenarios only. It does not place trades or authorize mandates.

## Provisional starter-portfolio heuristic

The current policy uses a 60% Flexi-cap / 40% Mid-Small-cap equity split when AUM is below ₹5 lakh or the monthly SIP is below ₹15,000. These thresholds and weights live in `data/policy/asset_allocation.json` and are classified as a provisional research heuristic—not a statutory rule or universal recommendation. The default thematic allocation remains zero.

## Main components

| Component | Responsibility |
|---|---|
| `core/math_engine.py` | Deterministic calculations, SAA/SIP policy handling, benchmark calculations and plan construction |
| `core/eligibility.py` | Candidate-universe ingestion and binary eligibility checks |
| `core/fund_classifier.py` | Scheme/category identification and passive alternatives |
| `tax/transition_planner.py` | Legacy CAS lot parsing only; all tax, exit-load, transition and switch-advice entry points are disabled pending independent approval |
| `data/policy/asset_allocation.json` | Central SAA and new-SIP policy |
| `data/policy/tax_rules.json` | Provisional reference data only; not approved for investor-facing tax calculations or advice |
| `data/policy/benchmark_tri_series*.json` | TRI fixtures for integrity and algorithm tests, not verified performance claims |
| `verify_tri_provenance.py` | Fixture checksum and benchmark release-eligibility checks |
| `advisor.py` | Explicit external client-data path resolver for controlled tooling |\n| `advisor_lean.py`, `legacy/advisor_lean_cli.py`, `ui/app.py` | Retired/disabled entry points; do not use for investor reports or recommendations |

## Dashboard status

The legacy Streamlit dashboard is retired and intentionally disabled. Its former client-discovery and planning flows used an obsolete in-repository data layout and are not supported. The root `app.py` entry point displays a retirement notice only; it does not load client data or generate recommendations. Do not re-enable the old UI until a replacement has explicit external-data isolation, read-only behavior, and dedicated integration tests.

## Private client data setup

Use a directory outside the repository containing the locally verified source inputs:

```text
private-data/
  client-portfolio/
    config.json
    fund_metrics.json
    fund_aliases.json
    transactions.json
    statements/
      cas_detailed_report_*.xlsx
```

Linux/macOS:

```bash
export MF_CLIENT_DATA_DIR="$HOME/private-data/client-portfolio"
```

Windows PowerShell:

```powershell
$env:MF_CLIENT_DATA_DIR = "$HOME\private-data\client-portfolio"
```

Never commit CAS statements, folio identifiers, investor identity, goals, budgets, bank balances, tax details, holdings, transaction histories, portfolio metrics or reports containing client information. Synthetic data belongs in tests only. See [SECURITY_DATA_HANDLING.md](SECURITY_DATA_HANDLING.md) for the client-data boundary and history-purge procedure.

**History warning:** Removing client files from the current tree does not delete them from earlier Git commits or clones. A history purge and access/exposure review remain separate release prerequisites.

## Running checks

Use a clean checkout and install the reviewed hash-locked dependencies:

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip check
pip-audit -r requirements.lock
python -m pytest test_p0_fiduciary_invariants.py -v
python -m pytest tests/test_p0_correctness_regressions.py -v
python validate_final_logics.py
python verify_tri_provenance.py
```

`requirements.txt` is the human-maintained input constraints file; use `requirements.lock` for reproducible installs. The Security workflow verifies the hash-locked install, `pip check` and `pip-audit`. See `DEPENDENCY_LOCKING.md`. The tag release workflow refuses to proceed unless the lock and authenticated daily TRI/calendar evidence pass.

Inspect the complete GitHub Actions run for the exact commit under review. A test result from a previous commit does not validate the current one. Skipped tests must be explained; they must not be counted as passing.

For local reports, provide complete verified client data through `MF_CLIENT_DATA_DIR`. Missing data must remain missing; do not construct synthetic client portfolios to produce a report.

## Allocation and thematic policy

The central policy separates SAA targets from new-SIP allocation. Tier 6 / Very High permits a 100% equity new-SIP route only when the explicit IPS authorization is supplied. A stability buffer must not bypass that authorization. Thematic/sectoral exposure is not an additional default core sleeve: a positive thematic satellite must be expressly authorized and carved out of the equity budget.

The precise values and boundaries are maintained in `data/policy/asset_allocation.json`. Do not copy them into a second implementation or README table.

## Tax treatment

Tax classification is deliberately unavailable in the current release. Public APIs for equity-oriented, specified-mutual-fund, Section 198, Section 50AA and Section 76 classification; FIFO tax maturation; lot-level exit-load calculation; tax-rate lookup; and tax-aware transition/redemption planning all fail closed pending independent legal review and verified scheme/plan/lot evidence.

Transaction parsing may be used only for controlled data preparation. It does not authenticate statutory treatment or authorize a sale. Synthetic tests validate the fail-closed boundary and selected data-integrity helpers; they do not establish that a statutory interpretation is legally correct or that a real scheme qualifies.

## Benchmark status

The checked-in TRI files are provisional test fixtures. Monthly or interpolated values are not daily TRI observations. Benchmark alpha is **BLOCKED** until official daily TRI observations, source-document hashes and an independently verified NSE session calendar are supplied and reconciled.

A matching checksum verifies the integrity of a local file against its stated checksum. It does not authenticate the publisher, establish that the series is the correct TRI, or prove that the observations are complete.

## Production release gates

The detailed, auditable release criteria are maintained in [PRODUCTION_RELEASE_CHECKLIST.md](PRODUCTION_RELEASE_CHECKLIST.md). Client-data exposure and GitHub branch-control remediation are documented in [SECURITY_DATA_HANDLING.md](SECURITY_DATA_HANDLING.md).

Production approval requires all of the following against one exact release commit:

1. All P0 and correctness regression suites pass, with no unexplained skips.
2. The complete candidate universe is source-backed, current and independently reconciled.
3. All allocation outputs reconcile to authoritative policy and every missing slot fails closed.
4. Tax logic has current statutory review and evidence-backed scheme classification.
5. Benchmark data and the independent NSE calendar pass authenticity, coverage and cash-flow reconciliation checks.
6. Private data is absent from tracked files, Git history, artifacts and logs.
7. The full workflow runs from a clean checkout with reproducibly locked dependencies.
8. `main` is protected by required CI checks, and release approval is independent of the implementation author.

Until those gates are evidenced, this is a development-stage decision-support prototype, not a production fiduciary recommendation engine.
