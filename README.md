# Indian Mutual-Fund Decision-Support Engine

A Python codebase for analysing Indian mutual-fund portfolios, testing investment-policy rules, reconciling investor-provided data and generating non-executable decision-support reports.

**Release status: NOT APPROVED FOR PRODUCTION.**  
**Execution: disabled.** All plans must remain non-actionable and subject to investor mandate and qualified human review.

This repository contains no intended client portfolio records. Client data must be supplied locally through `MF_CLIENT_DATA_DIR`.

## Design principles

- **Evidence before recommendation:** Every fund metric, scheme identity, portfolio constituent, benchmark observation and tax classification requires source, date, coverage and integrity metadata.
- **Fail closed:** Missing, stale, conflicting or incomplete required data leads to NO ACTION / HOLD. The system must not invent funds, scheme names, tax categories, yields or portfolio exposures.
- **Traceability integrity:** Decision hashes use RFC 8785/JCS canonical UTF-8 bytes plus SHA-256, with a versioned hash contract. Exact Decimal money values remain JSON strings to avoid precision loss.
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

## Application startup and dashboard status

The only supported Streamlit startup command is:

```bash
python app.py
# or, for a managed Streamlit deployment:
streamlit run app.py
```

Both commands target the root `app.py` launcher. It displays a readiness/retirement notice and deliberately does not import or execute `ui/app.py`. The legacy Streamlit dashboard and its planning pages are not a supported investor workflow. `ui/app.py` is itself a disabled retirement notice, so launching it directly cannot expose the legacy dashboard. Do not re-enable it as a shortcut.

The API can be started separately for controlled development with:

```bash
python app.py --api
```

The API is read-only decision support; production recommendations remain blocked until the evidence and independent release gates pass. The canonical investor-facing SIP UI is not yet implemented or approved. No portfolio upload, fund selection, allocation, recommendation, switch, redemption or execution flow is exposed by the root app. Do not re-enable the old UI until a replacement has explicit external-data isolation, session/privacy controls, backend-only financial decisions and end-to-end acceptance tests.

## Investor inputs and engine-owned public data

Investors must not create or maintain internal engine files such as `config.json`, `fund_metrics.json` or `fund_aliases.json`. Those are engine-owned artifacts, not onboarding inputs.

The investor-specific directory contains only the source documents and mandate facts needed for that investor, for example:

```text
private-data/
  client-portfolio/
    investor_mandate.json
    statements/
      cas_detailed_report_*.xlsx
```

Set the private investor directory only for tooling that explicitly requests it:

```bash
export MF_CLIENT_DATA_DIR="$HOME/private-data/client-portfolio"
```

Engine-owned public datasets use a separate directory and refresh command:

```bash
export MF_ENGINE_DATA_DIR="$HOME/.local/share/mf-engine/datasets"
python refresh_fund_data.py status
python refresh_fund_data.py refresh
python refresh_fund_data.py status
```

**Current capability boundary:** the implemented public adapter currently acquires the AMFI NAVAll feed and builds a NAV-only scheme-code snapshot. Its status remains `ACQUIRED_UNVERIFIED`; it is not a complete scheme master, approved fund-metrics set or decision-ready evidence bundle. It must not be used to produce positive SIP recommendations. Full source acquisition, identity reconciliation and independent promotion remain open under #110, #16, #84 and #121.

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

The retired legacy report path is not a supported investor workflow. Do not use `MF_CLIENT_DATA_DIR` to supply fund metrics, aliases or other engine-owned market data. Missing public evidence remains unavailable; synthetic client portfolios are test-only.

## Allocation and thematic policy

The central policy separates SAA targets from new-SIP allocation. Tier 6 / Very High permits a 100% equity new-SIP route only when the explicit IPS authorization is supplied. A stability buffer must not bypass that authorization. Thematic/sectoral exposure is not an additional default core sleeve: a positive thematic satellite must be expressly authorized and carved out of the equity budget.

The precise values and boundaries are maintained in `data/policy/asset_allocation.json`. Do not copy them into a second implementation or README table.

## Tax treatment

Tax classification is deliberately unavailable in the current release. Public APIs for equity-oriented, specified-mutual-fund, Section 198, Section 50AA and Section 76 classification; FIFO tax maturation; lot-level exit-load calculation; tax-rate lookup; and tax-aware transition/redemption planning all fail closed pending independent legal review and verified scheme/plan/lot evidence.

Transaction parsing may be used only for controlled data preparation. It does not authenticate statutory treatment or authorize a sale. Synthetic tests validate the fail-closed boundary and selected data-integrity helpers; they do not establish that a statutory interpretation is legally correct or that a real scheme qualifies.

## Benchmark status

The checked-in TRI files are provisional test fixtures. Monthly or interpolated values are not daily TRI observations. Benchmark alpha is **BLOCKED** until official daily TRI observations, source-document hashes and an independently verified NSE session calendar are supplied and reconciled.

A matching checksum verifies the integrity of a local file against its stated checksum. It does not authenticate the publisher, establish that the series is the correct TRI, or prove that the observations are complete.

## Retired legacy CAS dashboard

The former Streamlit dashboard and its portfolio-planning pages are retired. They are not the supported SIP recommendation workflow and must not be used to generate investor reports or decisions. The canonical SIP journey is tracked under #145. CAS structural parsing does not authenticate the publisher; see [Statement Publisher Provenance Contract](docs/STATEMENT_PUBLISHER_PROVENANCE.md).

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


### CAS publisher review (optional independent attestation)

The SIP upload endpoint structurally validates the exact CAS workbook bytes. Structural validity does not authenticate the publisher. Production/staging default to requiring a signed review before the SIP provider receives the CAS; without one, the route returns HOLD with the full budget unallocated. Test/development/local modes may process a structurally valid CAS only as explicitly `UNVERIFIED`, which is included in the decision trace. For independent publisher verification, configure the separately administered `STATEMENT_PUBLISHER_TRUST_REGISTRY_JSON` Ed25519 reviewer trust root and submit a signed `statement_publisher_approval_json` envelope bound to the exact uploaded-byte SHA-256. See [Statement Publisher Provenance Contract](docs/STATEMENT_PUBLISHER_PROVENANCE.md). Only public reviewer keys belong in the runtime trust registry; never put private reviewer keys in app settings or upload requests.
