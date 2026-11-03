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
| `tax/transition_planner.py` | CAS lot ingestion, FIFO reconstruction and tax-aware transition planning |
| `data/policy/asset_allocation.json` | Central SAA and new-SIP policy |
| `data/policy/tax_rules.json` | Date-versioned tax rule data; statutory review remains mandatory |
| `data/policy/benchmark_tri_series*.json` | TRI fixtures for integrity and algorithm tests, not verified performance claims |
| `verify_tri_provenance.py` | Fixture checksum and benchmark release-eligibility checks |
| `advisor.py`, `advisor_lean.py` | Local-data report entry points; not trade-execution tools |

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

Never commit CAS statements, folio identifiers, investor identity, goals, budgets, bank balances, tax details, holdings, transaction histories, portfolio metrics or reports containing client information. Synthetic data belongs in tests only. See [data/lalit_portfolio/README.md](data/lalit_portfolio/README.md) and [SECURITY_DATA_HANDLING.md](SECURITY_DATA_HANDLING.md).

**History warning:** Removing client files from the current tree does not delete them from earlier Git commits or clones. A history purge and access/exposure review remain separate release prerequisites.

## Running checks

Use a clean checkout and the pinned dependencies from `requirements.txt`:

```bash
python -m pip install -r requirements.txt
python -m pytest test_p0_fiduciary_invariants.py -v
python -m pytest tests/test_p0_correctness_regressions.py -v
python validate_final_logics.py
python verify_tri_provenance.py
```

Inspect the complete GitHub Actions run for the exact commit under review. A test result from a previous commit does not validate the current one. Skipped tests must be explained; they must not be counted as passing.

For local reports, provide complete verified client data through `MF_CLIENT_DATA_DIR`. Missing data must remain missing; do not construct synthetic client portfolios to produce a report.

## Allocation and thematic policy

The central policy separates SAA targets from new-SIP allocation. Tier 6 / Very High permits a 100% equity new-SIP route only when the explicit IPS authorization is supplied. A stability buffer must not bypass that authorization. Thematic/sectoral exposure is not an additional default core sleeve: a positive thematic satellite must be expressly authorized and carved out of the equity budget.

The precise values and boundaries are maintained in `data/policy/asset_allocation.json`. Do not copy them into a second implementation or README table.

## Tax treatment

The code keeps equity-oriented classification separate from specified-mutual-fund and market-linked-debenture classification. Effective date, acquisition date, transfer date, scheme structure and the legally prescribed observation method all matter.

The automated tests use synthetic fixtures to exercise calculations and boundaries. Synthetic fixtures do not prove that a statutory interpretation is legally correct or that a real scheme qualifies. Obtain current legal review and independently authenticated scheme-composition evidence before any tax treatment is relied upon.

The equity-only transition planner does not currently provide a complete tax engine for every non-equity asset class. It must refuse unsupported classifications rather than applying equity exemption assumptions.

## Benchmark status

The checked-in TRI files are provisional test fixtures. Monthly or interpolated values are not daily TRI observations. Benchmark alpha is **BLOCKED** until official daily TRI observations, source-document hashes and an independently verified NSE session calendar are supplied and reconciled.

A matching checksum verifies the integrity of a local file against its stated checksum. It does not authenticate the publisher, establish that the series is the correct TRI, or prove that the observations are complete.

## Production release gates

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
