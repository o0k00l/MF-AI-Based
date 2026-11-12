# SIP Decision Calculation and Data Contracts

**Status:** Detailed normative contract for implementation; not a claim that current code passes it.  
**Scope:** Monthly Indian mutual-fund SIP recommendation only.  
**Authority:** `SIP_ENGINE_DECISION_REGISTER.md` and `NORMATIVE_ARCHITECTURE_SPECIFICATION.md`.  
**Implementation status:** `../IMPLEMENTATION_STATUS.md`.  
**No-hardcoding rule:** every policy parameter below is resolved from the validated effective policy/IPS. This document specifies how a value is used, not a universal value for it.

## 1. Decision request and immutable context

A decision request MUST bind:
- investor/account/household scope and explicit included/excluded asset perimeter;
- CAS/CGS source digests, embedded statement dates, parser/schema versions and reconciliation result;
- decision date, currency, monthly contribution budget and its source/confirmation;
- public risk choice and, for Custom, validated custom SAA plus independent risk ceiling;
- approved goal/horizon, liquidity/obligation inputs and authenticated active SIP mandates;
- effective policy ID, version, digest, effective interval, approver and resolved parameter set;
- engine commit, API/schema version and every source artifact digest/date/coverage/release status.

The decision context is immutable after evaluation begins. If an input changes, create a new decision ID and trace; do not mutate a prior result. A decision cannot combine source snapshots from incompatible valuation dates unless a policy-defined reconciliation method explicitly permits it.

## 2. Outcome state machine

The public outcome is one of:
- `HOLD / NO_ACTION`: global prerequisite, integrity, policy, identity, perimeter, mandate, affordability or release gate failed. Allocations are empty and the full requested budget is unallocated.
- `PARTIAL / UNALLOCATED_REMAINDER`: global gates passed, but one or more sleeves/candidates cannot absorb their routed amount under the approved constraints. Only supported allocations may be shown; the rest remains unallocated with reasons.
- `PROPOSED`: all applicable gates passed and requested budget is exactly reconciled. This remains read-only and non-executable.
- `ERROR`: malformed/contradictory input that cannot safely be evaluated. It must not be converted into a financial zero or an apparently valid HOLD plan without preserving the validation error.

Global failure is not eligible for partial recommendations. A local sleeve failure may be partial only where the effective policy explicitly permits partial proposals. No result state authorizes execution.

## 3. Risk profile and target SAA

Public risk mapping is frozen:
- Conservative → internal Tier 2 policy.
- Moderate → internal Tier 4 policy.
- Aggressive → internal Tier 6 policy.
- Custom → investor-approved SAA plus a separate maximum permitted scheme Riskometer/risk ceiling.

The risk choice selects a permitted risk boundary and approved SAA policy; it does not prescribe a fixed fund category split and does not force maximum risk. The actual contribution route is derived from verified portfolio deficits and eligible marginal opportunities.

For Custom, validate all of the following before calculation:
1. Each declared sleeve has a stable policy-defined identifier and a finite Decimal weight.
2. No weight is negative.
3. Sum of weights is exactly 100% at the policy's declared precision; any permitted normalization must be explicit and traceable, never silent.
4. The separate risk ceiling is present, valid against the authoritative Riskometer schema and approved for the investor.
5. Every requested sleeve maps unambiguously to an asset-class taxonomy and candidate category support contract.
6. Custom mandate identity, approval, effective date and digest are bound to the decision.

Missing/invalid Custom data returns HOLD. No fallback to Aggressive, Tier 6, a default SAA or a category map is permitted. Investor risk capacity and scheme Riskometer are separate dimensions; candidate scheme risk above the approved ceiling is ineligible.

## 4. Portfolio perimeter, exposure and SAA drift

### 4.1 Perimeter reconciliation

Every included asset row requires a stable asset ID, asset class, value, source reference, owner scope and valuation date. Included rows must have unique IDs and a common decision valuation date. Excluded assets and unmatched items are separately enumerated. Liabilities are separately sourced and not silently netted against asset values.

A perimeter-complete assertion must be supported by an authorized attestation identifying the perimeter, attester, timestamp and statement. CAS-only data supports only a mutual-fund-only view; it cannot be represented as complete household wealth. Missing external cash, EPF/PPF/NPS, direct equity, debt or liabilities is UNKNOWN, not zero. If the investor elects a limited perimeter, the output must label it and policy must explicitly permit the requested analysis on that limited basis.

### 4.2 Sleeve mapping

Each asset and holding maps to exactly one SAA sleeve through a versioned taxonomy. Ambiguous, unmapped or multiply mapped value blocks total SAA calculation. The sum of classified sleeve values may be less than the total perimeter only where the remainder is explicitly classified (for example, cash, other or excluded); it may never exceed the reconciled total.

### 4.3 Current exposure and drift

For sleeve (i):
- (V_i): verified current value in INR.
- (P): reconciled value of the included portfolio perimeter in INR.
- (T_i): approved target weight as a percentage.
- (C_i = 100 	imes V_i/P): current weight percentage.
- (D_i = C_i - T_i): drift in percentage points.
- (	au_i): approved tolerance for that sleeve, resolved from effective policy.

An underweight exists only where (D_i < -	au_i); overweight exists only where (D_i > 	au_i). A zero target is valid. A sleeve at zero target is not a contribution destination. Do not infer missing sleeve values as zero unless the perimeter and classification evidence affirmatively establish a zero balance.

**Worked arithmetic example (illustrative only):** with (P=₹10,00,000), (V_A=₹3,00,000), (T_A=40%), current weight is 30% and drift is −10 percentage points. Whether this is actionable depends on the effective (	au_A), eligibility and portfolio perimeter; the example does not prescribe a tolerance.

## 5. Incremental SIP routing

### 5.1 Required inputs

Monthly budget (B), portfolio value (P), verified sleeve values (V_i), target weights (T_i), approved sleeve tolerance (	au_i), effective rounding rule/increment, and the set of sleeves that have at least one fully eligible and operationally feasible candidate. Every input is required; caller defaults are forbidden.

### 5.2 Post-contribution gap

The target value after investing the full requested contribution is (T_i(P+B)/100). The sleeve's positive post-contribution shortfall is:

[
G_i = max(0, T_i(P+B)/100 - V_i - 	au_i(P+B)/100)
]

The tolerance term is applied in currency against the post-contribution perimeter denominator. If policy specifies a different tolerance basis, it must define that basis and formula explicitly in its versioned contract; the engine cannot choose a basis ad hoc.

For sleeves with (G_i=0), route zero. For positive gaps, the provisional sleeve share is (R_i=B 	imes G_i/sum_j G_j). This is a proportional routing rule, not a guarantee that the final post-SIP portfolio exactly equals target SAA.

### 5.3 Eligibility, unfillable sleeves and rounding

A sleeve is routable only when it has at least one candidate passing every mandatory evidence, eligibility, portfolio overlap, risk, category research and operational feasibility gate. An unfillable sleeve retains its provisional share as unallocated. No cross-sleeve redistribution is allowed unless the effective IPS explicitly authorizes it and specifies the redistribution algorithm.

Round each sleeve's provisional amount down to the approved SIP increment. The difference remains unallocated in that sleeve. Do not push rounding residue to another sleeve or fund. The rounding increment is a required policy value; it is not universally ₹1, ₹100, ₹500 or any other constant.

At the end:
- (A=sum_i A_i) (allocated INR)
- (U=B-A) (unallocated INR)
- invariant: (A+U=B), exactly in Decimal.
- (U_i) records each sleeve's unallocated portion; (sum_i U_i=U).
- Post-contribution invested denominator is (P+A); post-contribution perimeter denominator is (P+B) when unallocated cash remains inside the declared perimeter. Report both distinctly. Do not label (P+A) as the total post-contribution household perimeter when (U>0).

**Illustrative example:** (B=₹10,000); provisional sleeve shares are ₹6,000 and ₹4,000. If the first sleeve is eligible and the second is not, allocate at most ₹6,000 to the first and retain ₹4,000 unallocated in the second. If the first sleeve's approved increment is ₹500 and its rounded amount is ₹5,750, the additional ₹250 also remains unallocated. Final allocation ₹5,750 + unallocated ₹4,250 = requested ₹10,000. These amounts only illustrate arithmetic.

### 5.4 Candidate-to-fund allocation

The fund allocator receives only candidates that have already passed hard eligibility and portfolio gates. Each candidate record must include stable scheme identity, sleeve, eligibility status, overlap/concentration status, operational status, rank score and its source/methodology/as-of evidence, scheme minimum SIP and required policy parameters.

The effective minimum ticket is the greater of policy minimum and authoritative scheme minimum, rounded upward to the policy increment. A candidate cannot be selected if the sleeve budget cannot support its minimum. If a maximum fund count or other cap is configured, it must come from policy and be jointly feasible with sleeve budgets and scheme minimums. If not configured, do not invent one.

Ranking is deterministic only after the approved scoring methodology is resolved. The tie-break contract must be explicit in the methodology version and included in the decision trace. Unselected candidates and all rejected candidates receive machine-readable reason codes. Any amount that cannot be assigned without breaching constraints remains unallocated.

**Implementation note:** current `allocate_candidate_sip` uses score-descending order, sleeve and candidate ID tie-breaks, prioritizes one candidate per active sleeve, and then fills remaining slots. This is a code observation, not a policy approval. Its `max_funds`, minimum ticket, increment and score-age parameters must be policy-bound; do not accept hidden defaults.

## 6. Holdings look-through and marginal exposure

### 6.1 Scheme look-through

For holding (h) with market value (M_h), disclosed coverage (q_h%), and constituent weight (w_{h,s}%) for stable security identifier (s), covered value is (M_hq_h/100). Security exposure contributed by that holding is (M_hw_{h,s}/100). Aggregate by canonical security identifier across all holdings. Portfolio-level coverage is (sum_h M_hq_h/sum_h M_h), not a simple average of fund coverage percentages.

All security identifiers must resolve through the dated security master. Unknown identifiers, invalid weights, incompatible disclosure dates or missing coverage block the affected look-through decision. Missing look-through is UNKNOWN, never zero exposure or zero overlap. Equity overlap denominator excludes debt/cash; disclose the exact denominator and coverage basis.

### 6.2 Candidate marginal exposure

Compute existing exposure and proposed exposure separately:
- Existing issuer/security exposure from all verified current holdings.
- Proposed exposure from the candidate's verified current disclosure multiplied by the proposed allocation.
- Post-SIP exposure = existing + proposed.
- Recompute sector, market-cap and theme aggregations from dated issuer classifications.
- Compare each post-SIP aggregate with the effective policy limit for that dimension and investor mandate.

Do not infer theme membership or market-cap classification from company name. Missing classification for any material issuer returns HOLD for the affected control. Multi-theme membership must follow a policy-defined attribution method to avoid double counting; absent method, do not sum overlapping theme percentages as if mutually exclusive.

Pairwise fund overlap, issuer concentration, sector concentration, market-cap mix and thematic concentration are different metrics. They must not be collapsed into one “diversification score”. The decision trace stores the exact metric, denominator, source, date, coverage and limit used.

## 7. Fund discovery, identity, eligibility and research scoring

### 7.1 Engine-owned universe

The engine discovers schemes from authoritative scheme masters and source feeds. The investor may name schemes for comparison but cannot provide or maintain the engine's candidate universe. Discovery is not eligibility and scheme-master presence is not proof of research completeness.

Every discovered scheme is keyed by authoritative scheme code/ID and bound to AMC, category, plan, option, ISIN where available, benchmark, lifecycle and effective dates. Fuzzy name matches may generate review candidates but cannot become verified identity. Category cannot be inferred from scheme-name keywords. Plan cannot default to Direct. Missing attributes remain missing and block affected eligibility.

### 7.2 Evidence completeness

For each candidate and each required evidence dimension, retain publisher, source URL/locator, raw-byte digest, retrieval time, publication/effective/as-of dates, parser/schema version, normalized digest, coverage, freshness policy ID, verification/reviewer status and exact scheme/security binding. A source artifact may support only fields it actually contains. AMFI NAV feed does not establish holdings, TER, benchmark, manager tenure or risk metrics.

Universe coverage is measured separately for each supported category and field. Do not hide a missing category behind a global candidate count. Third-party catalogues can aid discovery but do not become authoritative facts without independent verification.

### 7.3 Eligibility before scoring

Hard gates run before scoring. Required policy parameters are loaded from the same validated effective policy object and digest used for the decision. A missing metric, stale source, unknown category, unresolved identity or absent required threshold blocks the candidate; no neutral imputation, numeric default or synthetic substitution.

Investor risk ceiling is compared with the scheme's official Riskometer classification. Riskometer is not a proxy for investor capacity. Direct Growth eligibility requires exact authoritative plan and option evidence.

### 7.4 Scoring contract

The approved scoring policy must define, per supported category:
- benchmark identity and official TRI series;
- observation frequency, date alignment and missing-session treatment;
- return horizons and minimum history requirements;
- rolling-window construction and minimum valid observations;
- annualisation, volatility, downside capture, drawdown and risk-adjusted formulae;
- cost inputs and effective dates;
- peer/category normalization, winsorisation and outlier handling;
- component weights, missing-data behaviour, minimum evidence coverage and tie-breaks;
- passive versus active methodology and category exclusions;
- policy version, reviewer approval and effective dates.

No score may be produced by substituting missing alpha, Sharpe, returns, TER, risk, overlap or liquidity with zero, a category mean or a favourable neutral value unless the approved methodology explicitly defines and justifies that treatment. A candidate with incomplete required inputs is unscorable/ineligible, not low-confidence-but-rankable. The score is not itself a recommendation: portfolio marginal impact and suitability remain independent gates.

## 8. Liquidity, affordability and obligations

Verified cash, approved reserve target, near-term obligations, monthly net income, essential expenses and debt service are separate sourced inputs. Missing values are UNKNOWN, not zero. Each input carries its own source reference, valuation/as-of date and effective freshness policy.

The current primitive's arithmetic is:
- deployable cash = max(0, verified cash − approved reserve target − near-term obligations);
- monthly surplus = max(0, monthly net income − essential monthly expenses − monthly debt service);
- proposed SIP is affordable only when cash is not below reserve plus obligations and proposed monthly SIP does not exceed monthly surplus.

A one-time cash stock is not a recurring monthly income stream. Do not cap a monthly SIP by deployable cash or infer recurring affordability from a balance. Stress scenarios must be explicitly supplied by approved policy/investor mandate and are scenarios, not forecasts. A missing stress policy or missing required input blocks any claim that stress-tested affordability passed.

The freshness-age parameter itself must be resolved from the effective evidence policy for each input; a single hard-coded maximum age is prohibited.

## 9. Scheme operational feasibility

The exact scheme identity, lifecycle status, subscription availability, SIP frequencies, minimum instalment, applicable cut-off/processing terms and effective dates must be verified from current authoritative AMC/RTA evidence. A fund's existence or NAV publication does not prove it currently accepts the requested SIP instruction.

Compare the requested amount and frequency with the current scheme-specific terms and the investor's selected schedule. Missing, stale or contradictory operational evidence blocks that candidate. The engine does not submit an instruction and must not describe feasibility as execution confirmation.

## 10. TRI, benchmark and calendar contract

Category-to-benchmark mapping is sourced from an independently approved, versioned registry. The TRI series must match the benchmark identity, source publisher, methodology and effective period. Daily observations must be authenticated/reviewed, complete for required sessions and immutable by digest. The exchange calendar is a separate authoritative dataset; weekdays are not a substitute for trading sessions.

Cash-flow-matched benchmark calculations use external investor cash flows only, map each flow to the approved exchange session rule, and use the approved TRI level at the corresponding session. Switch/STP/reinvestment internal flows are excluded from portfolio-level external cash flows. Missing benchmark sessions, unresolved cash-flow dates or unapproved calendar versions block alpha release. Benchmark return is not computed from NAV data or a proxy benchmark.

## 11. CAS, transactions and active SIP mandates

CAS parsing must preserve source bytes/digest, embedded statement date, registrar claim and independent publisher authentication as distinct facts. Invalid numeric cells, non-finite amounts, duplicate/conflicting rows, unit/value inconsistencies and unsupported transaction types must fail before cache materialization. Do not coerce malformed cells to zero.

A transaction row labelled purchase/SIP is not proof of a currently active mandate. Active SIP status requires a current authenticated mandate or explicit investor confirmation, with scheme/folio/account binding, amount, frequency, start/end/next due dates, status, source and verification timestamp. Cancelled, expired, paused, one-time and future-dated rows are not counted as active recurring commitments. Ambiguity is UNKNOWN and blocks affordability/commitment reconciliation.

## 12. Decimal, rounding and serialization

All INR amounts, units, NAVs, weights used in money arithmetic and derived allocations use Decimal from parsing through output. Binary-float INR ingress is rejected at the active SIP client, service and deterministic-engine boundaries; API form budgets are parsed as Decimal. A float is permitted only for explicitly non-monetary ratios, rates or statistical solver inputs, and such conversions must never feed back into money accounting.

**Precision and rounding rules:** (1) INR values are quantized to paise at the validated model/API boundary using ROUND_HALF_UP; do not round intermediate aggregates or calculations. (2) SIP sleeve amounts are rounded only at the policy-declared SIP increment, with all residue retained as unallocated. (3) Units and NAV are quantities/prices, not INR totals: preserve their source Decimal precision on CAS ingestion and do not quantize them to arbitrary 3/4 decimal places. Derived NAV retains the Decimal division result internally. (4) Allocated plus unallocated SIP amounts must equal the requested paise-quantized budget exactly; a one-paise discrepancy is a validation failure.

Serialize Decimal values as canonical decimal strings or a schema-approved numeric representation that preserves exactness. Reject NaN, Infinity, booleans-as-numbers, empty strings and locale-formatted values unless a parser contract explicitly normalizes them before validation. The decision trace records raw and rounded values, rounding rule, and reconciliation proof.

## 13. Decision trace and explanation

Every result—including HOLD—must carry a trace with decision ID, timestamp, engine commit, policy identity/digest, schema versions, investor perimeter, statement and mandate references, source digests/dates/coverage, resolved parameters, calculation inputs/outputs, gate results, candidate rejection reasons, sleeve and fund allocations, unallocated amounts and final state.

Hash canonical JSON using the specified canonicalization algorithm. A hash proves integrity of the record, not truth or publisher authenticity of source data. Narrative generation may explain the trace but may not alter or omit adverse reasons. PII and raw CAS contents must not be sent to AI providers or included in public logs.

## 14. API and UI contract

The canonical API owns parsing, validation, policy resolution, financial calculations and decision state. The UI submits user facts and files, displays the backend result and exposes actionable HOLD reasons; it must not recalculate SAA, overlap, scoring or allocations.

Request validation distinguishes malformed input (4xx validation response) from valid-but-not-ready decision (structured HOLD/NO_ACTION response). Response schema must always include decision state, reasons, requested/allocated/unallocated amounts, portfolio perimeter label, valuation/as-of dates, policy/evidence trace references and non-execution notice. Error responses must not leak file paths, secrets, PII or stack traces.

No positive SIP result is releasable through a UI/API path until authentication, authorization, tenant isolation, upload limits, privacy controls, audit logging, evidence readiness and end-to-end acceptance are demonstrated on the exact main commit.

## 15. Worked end-to-end example (illustrative, not policy)

Assume an explicitly declared portfolio perimeter of ₹10,00,000 and a confirmed monthly SIP budget of ₹10,000. The effective investor policy provides a target SAA, sleeve tolerances, approved rounding increment and candidate constraints. The engine:
1. validates CAS and reconciles the declared perimeter;
2. resolves holdings and active mandates;
3. obtains current source-backed metrics and look-through for the supported candidate universe;
4. calculates current exposure and post-contribution sleeve gaps using the formulas above;
5. identifies eligible underweight sleeves;
6. routes budget proportionally to positive gaps;
7. keeps ineligible-sleeve and rounding residue unallocated;
8. allocates each sleeve budget only among candidates passing evidence, eligibility, overlap and operational checks;
9. validates liquidity/affordability;
10. emits a trace-bound read-only proposal or HOLD.

No specific fund, percentage, score, threshold, candidate count or minimum ticket is prescribed by this example. If the target policy, source evidence, or any required approval is absent, the expected result is HOLD / NO_ACTION with ₹10,000 unallocated.

## 16. Current code conformance gaps observed during specification

The following are observed in the current main source and must remain open until fixed and re-verified. This section is not an exhaustive code audit.

| Area | Observed implementation behaviour | Required correction / acceptance |
|---|---|---|
| SAA routing | Implemented on current main: `route_incremental_sip` calculates post-contribution INR gaps using (P+B), applies the policy tolerance to that denominator, and preserves unfillable sleeve shares as unallocated. Regression expectations were updated for the changed calculation. | Keep issue open until exact-main full CI and remaining SIP acceptance gates pass. |
| Routing parameter | Implemented on current main: the production service passes the validated `sip_allocation_policy.sip_increment_inr`; the primitive resolves an omitted value from the authoritative allocation policy and fails closed if unavailable. | Verify the policy digest is retained in the final decision trace. |
| Look-through | Implemented on current main: required coverage and constituent-weight reconciliation tolerance are loaded from the validated `fund_screening.json` policy; eligibility and legacy overlap checks consume the same policy values. | Confirm policy version/digest is bound in all active overlap decision traces. |
| Look-through | It aggregates issuer exposure, but does not itself produce pairwise fund overlap, marginal post-SIP exposure or sector/market-cap/theme results. | Keep those as distinct calculated controls; wire all required controls into recommendation orchestration and trace. |
| Risk normalization | Public risk profile mappings and Custom risk ceilings were previously duplicated or defaulted in runtime code. | Public Conservative/Moderate/Aggressive mapping is now stored in versioned allocation policy and consumed by the service, SAA model and math engine. Custom requires an independent explicit risk ceiling; no implicit Tier 6 fallback. | Verify policy cross-consistency and exact-main tests. |
| INR arithmetic | Active SIP pipeline previously had float budget ingress, CAS unit/NAV truncation and a one-paise SIP reconciliation tolerance. | Active SIP client/service/engine now require Decimal, integer or decimal-text budget/AUM inputs; CAS INR totals and routing remain Decimal; units/NAV preserve source precision; SIP allocated + unallocated reconciliation is exact; JSON plan serialization uses Decimal strings. | Exact-main regression and full CI evidence required; legacy tax/CGS and retired dashboard money paths remain outside the active SIP calculation contract and must not be wired back into production without Decimal migration. |
| Liquidity | `assess_liquidity_and_sip_surplus` accepts one `max_evidence_age_days` for all inputs. | Resolve source-specific freshness rules from policy/evidence contract; reject missing rules. |
| Candidate allocator | Implemented on current main: a missing or malformed candidate-specific scheme SIP minimum is rejected; it is no longer substituted with the general policy minimum. | Keep selection priority/tie-break policy and source evidence binding under review. |
| Candidate allocator | Current selection reserves one viable candidate per active sleeve, then fills score order, and sorts ties by sleeve/candidate ID. | Make selection priority and tie-break a versioned approved methodology, not implicit code behaviour. |
| Eligibility | `core/eligibility.py` documents fixed numeric hurdles in its function docstring and converts policy values to float in parts of the filter. | Remove stale numeric descriptions; keep thresholds in validated policy and preserve Decimal precision for financial/percentage math. |
| Risk profile | `services/sip_recommendation.py` contains local risk-to-policy and asset-class-to-sleeve maps. | Centralize in one validated policy/taxonomy object; reject missing/duplicate maps. |
| Fund discovery | `services/fiduciary_engine.py` falls back to embedded market nominations, infers categories from scheme-name text and defaults missing plan type to Direct. | Remove all such fallbacks/inferences; source-backed identity/category/plan required. |
| SAA policy | `services/fiduciary_engine.py` uses numeric fallback values while reading policy fields; `asset_allocation.json` currently contains legacy profile targets and fund caps/minimums. | Validate policy schema and effective approval; missing fields must fail, not use embedded fallback values. Reconcile legacy values against the frozen 3+1 risk contract before they can govern SIP. |
| Acquisition | `services/engine_fund_data.py` acquires AMFI NAV/scheme data but marks the result `ACQUIRED_UNVERIFIED`; it does not supply complete research/holdings/benchmark evidence. | Build and independently review source adapters and coverage for each supported category; do not promote NAV-only data to candidate eligibility. |
| Evidence provider | `services/sip_evidence_bundle.py` consumes an externally prepared candidate universe bundle. | Treat as an interim provider adapter only; production target requires engine-owned discovery, with the external bundle limited to independently reviewed source/release evidence, not investor-authored universe or final scores. |
| Production API | `api/sip_production.py` requires the external evidence bundle; app remains HOLD-only pending independent research/TRI release approval. | Replace bundle dependency only after engine-owned acquisition/research release controls are implemented; retain fail-closed behaviour meanwhile. |
| Money types | Active SIP budget boundary previously accepted generic numeric values; deterministic engine annotations advertised float budget/AUM. | `services.sip_recommendation.py`, `core/math_engine.compute_deterministic_sip_blueprint`, and `services.sip_api_client.py` now reject binary-float budget/AUM ingress and accept Decimal, integer or decimal text. | Exact-main SIP/CI verification must remain green. |

Do not mark these gaps fixed from documentation, commits or unit tests alone. Each correction requires a linked issue, code diff, focused tests (without weakening existing tests), current-main verification and end-to-end evidence.

## 17. Acceptance scenarios required

1. Missing/invalid Custom SAA or risk ceiling → HOLD; no Tier 6 fallback.
2. Missing external assets with CAS-only upload → explicitly limited MF-only analysis or HOLD; never complete total-portfolio claim.
3. Active SIP text/purchase row without authenticated mandate → not counted as active commitment.
4. Unknown security ID or incomplete look-through → UNKNOWN/HOLD; never zero overlap.
5. Zero target sleeve → zero routed amount; no category quota.
6. Unfillable underweight sleeve → its budget remains unallocated; no redistribution.
7. Post-contribution gap and denominator → expected exact Decimal values for every sleeve.
8. Scheme minimum missing/stale → candidate rejected; no policy-minimum substitution for unknown scheme terms.
9. Missing scoring input/benchmark/TRI/calendar → candidate unscorable or release HOLD.
10. Missing source-specific freshness policy → HOLD.
11. SIP constraints jointly infeasible → no positive allocation; full or affected budget unallocated per global/local failure rules.
12. Decimal rounding residue → exact allocated + unallocated equality.
13. Malformed/non-finite CAS amount → rejected before cache creation.
14. Changed CAS, policy, disclosure, benchmark or engine commit → new trace/hash; no reuse of stale result.
15. API/UI positive path → same backend result and no duplicated UI calculation; unauthenticated/unauthorized requests rejected.
16. AI provider absent, paid-only, rate-limited or unavailable → deterministic financial decision unchanged; narrative omitted or marked unavailable.

## 18. Document change control

Any change to formulas, data semantics, policy resolution, risk mapping, tie-breaks, status transitions or API schema requires:
- a decision-register entry or explicit amendment to an existing decision;
- a versioned schema/policy/methodology change with effective date and reviewer;
- migration/compatibility notes for persisted evidence;
- acceptance scenarios covering changed and failure behaviour;
- implementation-status update only after verification on current `main`.

No test may be weakened, deleted or rewritten merely to obtain a passing release gate.
