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


## Additional findings from the CAS-to-SIP execution path (separate from the earlier six blockers)

### 9. CAS holdings split across folios were reconciled row-by-row — FIXED
- Previous behavior compared each CAS holding row with the aggregate transaction units for the scheme. Two folios in the same scheme could therefore be falsely marked discrepant.
- Correction: aggregate CAS units by normalized exact scheme name before comparing.
- Regression: `test_reconciliation_aggregates_same_scheme_across_multiple_folios`.

### 10. Transaction scheme matching used substring matching and first-match wins — FIXED
- Previous behavior accepted either-direction substring matches and stopped at the first match. Similar scheme names could be reconciled against the wrong transaction ledger.
- Correction: use exact normalized scheme identity only. Ambiguous or variant names remain unresolved; no fuzzy fallback.
- Regression: `test_reconciliation_does_not_use_substring_scheme_matching`.

### 11. Active transaction schemes absent from the CAS were ignored — FIXED
- Previous behavior checked each CAS holding but did not report non-zero net units in transaction schemes absent from the current CAS.
- Correction: report unmatched active transaction schemes and return PARTIALLY_RECONCILED.
- Regression: `test_reconciliation_detects_unmatched_active_transaction_scheme`.

### 12. Transaction rows and unit values were not validated — FIXED
- Previous behavior could throw on malformed row shapes or accept non-finite/negative units and unsupported transaction types into the reconciliation calculation.
- Correction: validate the transactions container, row shape, scheme, supported type and finite non-negative unit quantity. Invalid input returns an explicit invalid/read-error state.
- Regressions: malformed rows, invalid container and negative units.

### 13. A supplied but unreconciled transaction file did not gate SIP output — FIXED
- Previous behavior produced a SIP blueprint and only displayed reconciliation as a separate diagnostic.
- Correction: when a transaction file is supplied but does not reconcile, zero all SIP line amounts and withhold the entire monthly budget. A CAS-only snapshot with no transaction file remains explicitly labelled NO_TRANSACTION_FILE; it is not falsely described as reconciled.
- Regression coverage for the reconciliation states is in `tests/test_sip_cas_transaction_reconciliation.py`. An aggregator-level whole-budget integration test is still required.

### 14. Missing IPS fields silently manufactured a ₹1 lakh monthly budget and Tier 6 risk — FIXED
- Previous behavior defaulted missing config/budget/risk fields to a ₹1,00,000 monthly SIP and Tier 6. A second config read also overwrote a valid nested `ips.risk_tolerance` with a top-level-only lookup.
- Correction: require a readable config with an `ips` object, an explicit risk tier, and an explicit finite positive `ips.monthly_sip_budget`; preserve the already validated top-level or nested risk value. Lumpsum defaults to zero, not an invented ₹2 lakh.
- Integration coverage for missing/invalid IPS config remains to be added.

## Further policy/integration blockers

### 15. Three-tier risk mapping conflicts with the declared 3+1 SAA map — P0
- `core/models.py` defines Conservative 20/80, Moderate 60/40 and Aggressive 95/5.
- The SIP selector translates those labels to SEBI Tier 2, Tier 4 and Tier 6, whose checked-in SAA targets are 40/60, 75/25 and 95/5.
- The Moderate and Conservative meanings therefore differ across the two policy representations. Do not silently choose one mapping; consolidate the investor-facing 3+1 risk contract and policy before enabling recommendations.

### 16. Tier 6 IPS equity-only authorization is not wired through the aggregator — P0
- `calculate_universal_tier_split` has an explicit authorization override, but the aggregator calls the SIP blueprint without passing a verified IPS authorization value.
- Result: an investor authorization cannot reliably select the policy's 100% equity route through the end-to-end workflow.
- Required fix: define the exact IPS field and schema, validate it as a literal boolean, bind it to the approved risk profile and pass it through the complete pipeline. Do not infer authorization from the risk tier.

### 17. Candidate-universe size is global, not category-complete — P1
- The minimum 30-fund universe check is global. It does not establish that each required sleeve (large, flexi/multi, mid and small) has a sufficient, current, eligible candidate set.
- Required fix: category-level coverage gates, scheme identity deduplication, freshness checks and explicit per-sleeve NO_ACTION diagnostics before scoring.


## Further SIP portfolio-accounting defects found and corrected (separate from the previously listed blockers)

### 18. High equity percentage incorrectly classified Large Cap and Multi Cap as Flexi Cap — FIXED
- File: `core/math_engine.py`, `_infer_asset_class`.
- Previous behavior: the generic `equity_pct >= 80` branch ran before the Multi Cap branch and also classified large-cap funds as Flexi Cap. A high equity allocation does not establish a scheme's SEBI category.
- Correction: use explicit category identity first (debt/hybrid/international/small/mid/multi/flexi/large); use disclosed market-cap weights only as a fallback for generic categories.
- Regression coverage: Multi Cap 95% equity remains Multi Cap; Large Cap 95% equity remains Large Cap; International Equity is preserved.

### 19. Debt Liquid holdings were omitted from the Debt SAA bucket — FIXED
- File: `core/math_engine.py`, `calculate_saa_drift_minimizer` and aggregator SAA totals.
- Previous behavior: `AssetClass.DEBT_LIQUID` fell through to Other, while the debt totals only counted `AssetClass.DEBT`.
- Correction: include both debt classes in the Debt bucket and aggregate debt value.
- Regression coverage: mixed debt-liquid/international portfolio reconciles to 50% Debt / 50% Equity without an Other bucket.

### 20. International equity was inconsistently treated as a separate non-target bucket — FIXED
- File: `core/math_engine.py`, `calculate_saa_drift_minimizer`.
- Previous behavior: International was first mapped to Equity and then had an unreachable legacy branch for International; the aggregate SAA value calculation also lacked generic `AssetClass.EQUITY`.
- Correction: classify international equity as Equity for total-portfolio Equity/Debt/Cash SAA accounting and include generic Equity holdings in the aggregate.
- Note: geographic diversification remains a separate exposure dimension; this does not erase the international sleeve from look-through reporting.

### 21. Aggregator omitted AMC identity from portfolio context passed to candidate gates — FIXED
- File: `core/math_engine.py`, `aggregate_fiduciary_facts`.
- Previous behavior: candidate AMC concentration gates require each existing holding's AMC identity, but the aggregator passed only scheme and value. This caused the diagnostic eligibility path to fail closed for every candidate due to missing AMC metadata.
- Correction: centralize the portfolio gate summary and include `amc_name` with each holding's value.
- Regression coverage: `_build_portfolio_gate_summary` retains AMC identity.

### 22. Boolean IPS budget/reserve values were accepted as numeric — FIXED
- File: `core/math_engine.py`, `_validated_ips_numeric_inputs`.
- Previous behavior: Python converts `True` to 1.0 and `False` to 0.0, so a malformed boolean SIP budget could pass numeric conversion.
- Correction: reject boolean SIP, lumpsum and emergency-month inputs before numeric conversion; preserve finite/range validation.
- Regression coverage: boolean values for each field, missing budget and non-finite budget are rejected.

## Remaining validation for these changes
- The latest GitHub commit has no reported status checks or associated workflow runs in the connector response. The new tests have been committed but are not reported as executed.
- The current test file contains 13 test functions; this is source-level coverage, not a passing test result.
- Run the focused SIP tests and full repository CI on a clean checkout before treating these corrections as validated.


### 23. Missing client SAA silently became an aggressive 95/5 target — FIXED
- File: `core/math_engine.py`, `calculate_saa_drift_minimizer`.
- Previous behavior: when the client supplied no usable equity target, the function silently substituted 95% equity / 5% debt. This could materially distort portfolio deficits and the reported SIP-to-SAA fit for a conservative or moderate investor.
- Correction: require explicit equity, debt and cash targets; validate each as finite and within 0–100 and require the three buckets to sum to 100%. An explicitly supplied 0% equity target is preserved.
- Regression coverage: missing target rejected; explicit 0/100/0 target accepted.


### 24. CAS-to-metrics fuzzy matching could attach another scheme's exposures — FIXED IN CODE; EXECUTION NOT YET VERIFIED
- File: `core/math_engine.py`, `_find_matching_metric` and `load_holdings_from_cas_excel`.
- Previous behavior: token-overlap similarity selected the best-scoring metrics record at a 50% threshold. Similar scheme names could therefore inherit another scheme's category, market-cap split and metrics.
- Correction: match only exact normalized identity or an explicit reviewed alias; ambiguous matches remain unresolved. An unmatched CAS scheme now raises a validation error rather than defaulting to 100% equity. Missing market-cap exposure fields also withhold portfolio-aware SIP analysis.
- Regression coverage added for fuzzy-match rejection, exact identity, reviewed alias and ambiguous-name rejection in `tests/test_sip_portfolio_overlap.py`.
- Commit sequence: `310a91d` (code), `02fd3f0` (tests).
- Limitation: tests have not yet been executed; scheme-master/ISIN-first matching remains a follow-up improvement. Reviewed aliases are still a controlled manual bridge for source naming differences.


### 25. Investor-facing 3-tier SAA disagreed with SIP engine risk mapping — FIXED IN CODE; EXECUTION NOT YET VERIFIED
- File: `core/models.py`, `SAA_POLICY_MAP`.
- Previous values were Conservative 20/80, Moderate 60/40, Aggressive 95/5, while the SIP engine mapped those labels to SEBI Tier 2, Tier 4 and Tier 6 profiles in `asset_allocation.json` (40/60, 75/25, 95/5).
- This meant different parts of the application could display or calculate materially different target allocations for the same investor risk label.
- Correction: the shared 3-tier map now matches the SIP engine's approved profile mapping: Conservative 40/60, Moderate 75/25, Aggressive 95/5. Custom remains explicit and separately approved.
- Regression tests added for all three mappings and 100% reconciliation in `tests/test_sip_portfolio_overlap.py`.
- Commits: `1780600` (code), `a508cc1` (tests).
- Limitation: tests have not yet been executed. This aligns the SAA values; it does not itself prove that every API/UI route passes the same normalized risk label.


### 26. Tier 6 equity-only SIP authorization was not passed from IPS into the SIP engine — FIXED IN CODE; EXECUTION NOT YET VERIFIED
- File: `core/math_engine.py`, IPS validation and `aggregate_fiduciary_facts` SIP call.
- Previous behaviour: the low-level split calculator supported explicit Tier 6 equity-only routing, but the portfolio aggregator never forwarded the investor's authorization. An authorized client therefore remained on the default strategic equity/debt split.
- Correction: the aggregator now reads `ips.equity_only_sip_authorized`, requires a real boolean, permits `true` only for SEBI Tier 6, and passes the validated value to `compute_deterministic_sip_blueprint`. Missing authorization remains false.
- Regression tests cover default-off, explicit Tier 6 authorization, non-boolean rejection and non-Tier-6 rejection.
- Commits: `743e812` (code), `815f31e` (tests).
- Limitation: tests have not been executed. This is an authorization wiring fix, not an endorsement of 100% equity for any particular investor; the IPS and suitability review must still justify it.


### 27. Candidate scoring accepted negative or out-of-range pillar weights — FIXED IN CODE; EXECUTION NOT YET VERIFIED
- File: `core/candidate_scoring.py`, `ScoringWeights.validate`.
- Previous behaviour: validation checked only that weights summed to 1.0. Negative weights and weights above 100% could pass, allowing a scoring configuration to reward a penalty pillar or invert the intended objective.
- Correction: every weight must now be finite and within [0, 1], and the total must still equal 1.0.
- Regression coverage: negative, over-1 and non-finite weight rejection in `tests/test_sip_candidate_scoring_safety.py`.

### 28. Negative 1Y returns were not penalized in the alpha/return pillar — FIXED IN CODE; EXECUTION NOT YET VERIFIED
- File: `core/candidate_scoring.py`, `calculate_candidate_6_pillar_score`.
- Previous behaviour: when 1Y return was zero or negative, the scorer substituted the alpha score for the return score. A fund with a poor/negative 1Y return could therefore receive the same return contribution as a fund with positive alpha.
- Correction: score the observed 1Y return against the category return anchors, including zero and negative observations.
- Regression coverage: negative 1Y return is scored at the bottom of the Flexi Cap return range in `tests/test_sip_candidate_scoring_safety.py`.

### 29. Candidate metrics loader silently converted missing/corrupt evidence into an empty universe — FIXED IN CODE; EXECUTION NOT YET VERIFIED
- File: `core/candidate_scoring.py`, `FiduciaryFundSelector._load_metrics`.
- Previous behaviour: a missing file, malformed JSON or schema problem returned an empty dictionary. Downstream code then failed later or behaved as if no candidates existed, obscuring the actual evidence failure.
- Correction: missing evidence raises `FileNotFoundError`; malformed JSON/schema, empty universe, invalid records and duplicate identities raise explicit `ValueError`.
- Regression coverage: missing file, invalid JSON, empty universe and duplicate identity in `tests/test_sip_candidate_scoring_safety.py`.

### 30. Legacy Flexi selector contains hard-coded scheme facts and fallback performance/AUM values — OPEN, HIGH RISK
- File: `core/candidate_scoring.py`, `FiduciaryFundSelector.score_flexi_cap_candidates`.
- Observed behaviour: the legacy selector names two fixed funds and embeds scheme labels, folio references, equity/debt exposures, international exposure narratives, AUM/TER/alpha/Sharpe fallback values and fixed recommendation verdicts.
- Risk: stale or absent source metrics can be presented as current candidate facts; it is not a scalable category-level candidate selector. Remove this legacy hard-coding or make every field source-bound and identity-verified before using it for SIP recommendations.
- Not changed in this pass because the replacement needs a confirmed canonical candidate schema and callers.

### 31. Missing portfolio-overlap evidence receives a neutral score — OPEN, HIGH RISK
- File: `core/candidate_scoring.py`, `calculate_candidate_6_pillar_score`.
- Observed behaviour: if neither portfolio overlap nor candidate overlap is supplied, the MPB/overlap pillar receives 50/100 rather than withholding a portfolio-aware score.
- Risk: a candidate may be ranked without evidence of its marginal diversification benefit. A portfolio-aware SIP route should require overlap coverage or explicitly mark the score provisional and ineligible for recommendation.
- Not changed in this pass to avoid breaking non-portfolio scoring consumers without first separating standalone fund scoring from SIP portfolio scoring.

### 32. Category scoring anchors do not cover the full scheme/category universe — OPEN, MEDIUM-HIGH
- File: `core/candidate_scoring.py`, `CATEGORY_BENCHMARK_ANCHORS`.
- Observed behaviour: only Healthcare, Flexi Cap, Mid Cap and Large Cap anchors are defined. Other categories supported elsewhere in the engine (including Small Cap, Multi Cap, Debt, Hybrid and International) cannot be scored by this function and are rejected.
- Risk: category coverage can be incomplete even if the overall candidate universe is large. A category-specific benchmark and scoring policy must be approved before those categories are eligible.
- Not changed pending policy-owned benchmark anchors; do not fill missing categories with another category's anchors.

### 33. Scoring normalizer accepted malformed/non-finite metric values — FIXED IN CODE; EXECUTION NOT YET VERIFIED
- File: `core/candidate_scoring.py`, `normalize_metric`.
- Correction: reject boolean, non-numeric and non-finite values/bounds, and reversed bounds instead of producing misleading normalized scores.
- Regression coverage: NaN, infinity, booleans and reversed bounds in `tests/test_sip_candidate_scoring_safety.py`.


## New scoring findings brought into the portfolio SIP delivery (#40 / #41)

### 31. Missing overlap cannot receive a neutral composite score — IMPLEMENTED, CI PENDING
- The scoring function now has an explicit `portfolio_aware=True` mode.
- Portfolio-aware scoring requires reviewer-attested overlap source bytes and matching SHA-256, stable candidate identity, a current evidence date, a measured overlap percentage and at least 99.5% constituent look-through coverage.
- Missing overlap raises an unavailable-evidence error. It is not converted to a neutral 50-point pillar. Verified zero overlap remains a valid, separately tested observation.
- Standalone score diagnostics retain their historical neutral explanatory fallback but are explicitly distinct from portfolio-aware SIP scoring. They cannot be treated as portfolio-aware ranking.
- The provider contract also requires `score_scope=PORTFOLIO_AWARE`, `missing_overlap_policy=BLOCK_SCORE`, verified overlap status/coverage and a source reference. Existing SIP overlap calculations continue to block candidates when look-through is missing.

### 32. Category-specific scoring anchors must be complete and approved — IMPLEMENTED, CI PENDING
- Standalone scoring no longer falls back to Healthcare 1Y-return bounds when a category anchor is missing. The category must have all seven metric bounds or scoring fails closed.
- The current legacy map contains a complete set only for Healthcare; Flexi Cap, Mid Cap and Large Cap lack their own `ret1y` anchor and are now unavailable through the standalone map until those values are independently approved.
- Portfolio-aware scoring accepts a category-specific anchor set only when the supplied evidence is reviewer-attested and source-byte hashed, current, exact-category matched, benchmark-identified and versioned. All seven finite/increasing bounds are required.
- The provider contract requires exact category, benchmark, original anchor-source digest, reviewer, effective date and policy version to match each scored candidate. Unsupported categories cannot borrow anchors or use generic defaults.
- No new numeric category thresholds were invented in this change. Independent review of the actual anchor values and ranking methodology remains a release prerequisite.


## Cross-document policy and configurability rules (binding)

This document is subordinate to `docs/SIP_ENGINE_DECISION_REGISTER.md` for settled product decisions and `docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md` for normative behaviour. Read it with `IMPLEMENTATION_STATUS.md` for implementation/acceptance status. Historical audit snapshots and remediation plans are evidence/history, not a source of current policy.

**No arbitrary hardcoding:** no allocation percentage, fund-count limit, per-fund cap, candidate-count minimum, risk mapping, score weight, score threshold, concentration limit, look-through coverage threshold, freshness/staleness duration, SIP minimum/increment, reserve period, AUM floor/ceiling, manager-tenure requirement, benchmark mapping, refresh cadence or other investment/operational threshold may be introduced as a universal code or document default merely because it is conventional or appeared in an earlier proposal. Such values must come from an approved, versioned, effective-dated policy/IPS or authoritative source, with provenance, scope, owner/reviewer and validation. If a required value is absent, invalid, stale, conflicting or out of scope, the affected decision must HOLD / NO_ACTION and preserve affected budget as unallocated. Do not silently substitute zero, a generic default, a fallback category, another category's threshold or a prior policy version.

**Source-derived facts are not policy defaults:** scheme identity, category, plan/option, benchmark, NAV, AUM, TER, holdings, issuer/sector classification, scheme lifecycle, SIP operational terms, trading sessions and disclosure dates must be acquired from authoritative, dated sources and validated for the exact scheme/security and effective period. Do not infer them from names, synthetic fixtures, LLM output or unrelated records. A source's publication cadence is observed and monitored; it is not a hard-coded assertion that evidence is fresh.

**Calculation determinism:** formulas, units, denominator, date alignment, rounding mode/scale, missing-data semantics and tie-breaking must be explicit and versioned. Financial amounts and units use Decimal arithmetic end-to-end; round only at the specified policy boundary. Every requested rupee must reconcile to allocated plus unallocated rupees exactly after the approved rounding operation.

**Configuration contract:** every configurable policy value must be present in the validated policy object used for the decision, and the decision trace must bind its policy ID/version/digest/effective date and resolved values. No hidden environment fallback or duplicated local mapping is permitted. Environment variables may identify locations, credentials or deployment wiring; they must not silently become an unreviewed investment policy.

**Examples are non-operative:** numbers, scheme names, benchmark names, dates, file names and sample JSON are illustrative unless explicitly identified as a currently approved policy/source contract. Example values must never be promoted to runtime defaults. Any fixed numeric threshold or benchmark list in a legacy section is historical/example material pending explicit approval and migration into the effective policy/source registry; it is not authority to hardcode that value.

**Conflict resolution:** apply the decision register, then the normative architecture, then the approved effective policy/IPS for investor-specific values, then authoritative source evidence for market facts. Policy cannot override source facts and source facts cannot invent policy. Record unresolved conflicts and HOLD; do not pick whichever value makes the workflow pass.
