# SIP Portfolio-Aware Readiness Audit

**Scope:** SIP recommendation only. This audit is separate from TRI provenance and benchmark-release work.

**Current disposition:** NOT READY. Keep SIP recommendations in HOLD / NO ACTION until the blockers below are resolved and verified against one exact commit. The code is decision-support only; this audit does not authorize investment actions.

## Verified implementation defects

### 1. Equity overlap was diluted by debt and cash in the portfolio denominator — FIXED
- File: `core/math_engine.py`
- Function: `compute_candidate_portfolio_overlap`
- Previous behavior: aggregated equity-stock exposure was divided by total portfolio value. Debt/cash therefore diluted the reported stock overlap.
- Correction: normalize portfolio constituent exposures by total equity exposure only. Debt-only holdings do not require stock-level equity disclosures and do not dilute overlap.
- Selector guard: only positive-equity holdings require verified look-through status.
- Regression coverage: `tests/test_sip_portfolio_overlap.py`.
- Commit: `e2348dacc07a7539f15da701c7733c4deb92b21e`.

### 2. Secondary candidate filter accepted an overlap limit but did not enforce it — FIXED
- File: `core/eligibility.py`
- Function: `filter_candidates`
- Previous behavior: `max_overlap_limit_pct` was accepted but unused.
- Correction: calculate value-weighted constituent overlap and withhold a candidate when either side lacks verified, adequately covered look-through data or overlap exceeds the supplied limit.
- Regression coverage: `tests/test_sip_portfolio_overlap.py`.
- Commit: `703cc6fe1d87441ac3bdacd9c688d5e1c8912d58`.

## Major blockers still open

### 3. The 20% per-fund cap conflicts with the actual one-fund-per-sleeve blueprint — P0
- Files: `data/policy/asset_allocation.json`, `core/math_engine.py`
- The operational validator applies `max_fund_allocation_pct=20` to each SIP line.
- The starter policy routes 60% of the equity SIP to the Flexi-cap sleeve; the blueprint currently assigns that sleeve to one fund, so the 60% line breaches the 20% cap.
- Tier 6 established portfolios also create single-sleeve allocations above 20% (approximately 21–27% in the current policy).
- Result: otherwise valid plans can be converted to all-budget NO ACTION. Do not silently raise the cap or bypass it. Resolve the product rule explicitly: either permit a documented sleeve-level exception, or support multiple separately eligible funds within a sleeve and allocate each line under the cap.

### 4. The 12-month new-fund limit is declared but not enforced — P0
- Policy: `sip_allocation_policy.max_new_funds_per_12_months`.
- The operational validator reads the fund-allocation cap, minimum ticket, increment and maximum core count, but does not read the new-fund limit.
- The SIP blueprint does not receive a reconciled 12-month scheme-introduction history to enforce the rule.
- Required fix: source-backed new-scheme history, stable scheme-family identity, and explicit same-scheme Regular-to-Direct migration treatment before candidate selection.

### 5. CAS-to-metrics matching can choose an ambiguous fuzzy name match — P0
- File: `core/math_engine.py`
- Function: `_find_matching_metric`
- The fallback uses token-overlap similarity and selects the highest score once it crosses a threshold. It does not require a minimum gap over the runner-up or independently confirm the selected scheme ID/ISIN.
- Risk: a CAS holding can inherit another scheme's category, market-cap split, expense ratio or metrics.
- Required fix: exact scheme identity (scheme ID/ISIN) first; reviewed alias only as an explicit mapping; ambiguous name-only matches must remain unresolved and block portfolio-aware SIP calculation.

### 6. An unmatched CAS scheme is silently assumed to be 100% equity — P0
- File: `core/math_engine.py`
- Function: `load_holdings_from_cas_excel`
- When metrics are not matched, current defaults include category `Equity`, equity weight 100%, debt 0%, and a fallback asset-class inference.
- Risk: an unmatched debt, hybrid or international scheme can distort total equity, debt, sleeve deficits and SIP routing.
- Required fix: represent exposure classification as UNKNOWN with source status; any unknown material holding must block SAA-gap and SIP routing until reconciled. Do not replace missing classification with equity.

### 7. Custom risk is not wired through the SIP selector — P0
- File: `core/math_engine.py`
- Function: `select_autonomous_blueprint_funds`
- The selector explicitly raises for `RiskTier.CUSTOM`; the custom SAA model exists in `core/models.py`, but the SIP selector accepts only the six SEBI tier integers / three named enum profiles.
- The policy JSON also contains six behavioural profiles while the public model exposes a 3-tier-plus-custom interface. The translation contract is not unified.
- Required fix: pass a validated custom SAA/risk policy through allocation, suitability gates and sleeve selection; reject incomplete custom policies. Never silently map Custom to Aggressive/Tier 6.

### 8. SIP selection is not yet a complete end-to-end client workflow — P0
- README states the legacy Streamlit dashboard is retired and root `app.py` is a retirement notice.
- Candidate loading depends on an externally supplied `fund_metrics.json`; the repository documents no production default evidence provider.
- Required fix: implement a replacement read-only workflow that validates CAS + CGS/transaction history + candidate universe + portfolio disclosures + mandate inputs, emits a structured readiness report, and keeps the entire budget unallocated on any required-data failure.

## Validation still required

- Run the complete test suite and CI on the latest `main` commit after the SIP changes. Current GitHub status response for the latest test commit did not expose any status checks; no passing CI claim is made here.
- Add integration tests for CAS identity ambiguity, unknown asset classification, 20% cap feasibility, new-fund history, custom risk, stale disclosures, and whole-budget reconciliation.
- Verify all positive allocations reconcile to the requested monthly budget, minimum ₹1,000 ticket, ₹500 increment, maximum six core funds, per-fund cap, and new-fund limit simultaneously.
- Keep recommendation output HOLD / NO ACTION until candidate universe and all required portfolio evidence are authenticated and complete.
