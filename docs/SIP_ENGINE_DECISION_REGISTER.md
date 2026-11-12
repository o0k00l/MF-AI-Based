# SIP Engine Decision Register

**Decision baseline:** 2026-11-12  
**Authority:** Product and engineering decisions consolidated from the user's prior MF-AI-Based discussions.  
**Normative specification:** [NORMATIVE_ARCHITECTURE_SPECIFICATION.md](NORMATIVE_ARCHITECTURE_SPECIFICATION.md)  
**Master delivery issue:** [#144](https://github.com/o0k00l/MF-AI-Based/issues/144)  
**End-to-end acceptance:** [#145](https://github.com/o0k00l/MF-AI-Based/issues/145)

This register is the decision source of truth. Older audit notes and issue descriptions remain useful evidence of defects, but they do not override the decisions below. If code or another document conflicts, record the conflict as an implementation defect; do not silently reinterpret this register.

## A. Product scope and authority

| ID | Decision | Status |
|---|---|---|
| D-001 | Current product delivery is **monthly mutual-fund SIP recommendation only**. | Fixed |
| D-002 | Lumpsum deployment, STP, redemption, switching, tax optimisation, exit-load/tax transition advice and trade execution are outside this delivery. Existing unrelated modules may remain in the repository but must not be surfaced as supported SIP capabilities. | Fixed |
| D-003 | Recommendations are read-only, non-executable proposals. No broker, RTA, AMC, bank, payment or order execution integration. Investor/adviser retains final decision and execution authority. | Fixed |
| D-004 | One canonical investor journey and one deterministic recommendation backend. API/service owns financial decisions; UI is a client of that backend and must not duplicate policy/math. | Fixed |
| D-005 | The retired Streamlit dashboard remains retired until a replacement SIP workflow is implemented and validated. Do not reactivate old portfolio/planning pages. | Fixed |

## B. Investor inputs and portfolio perimeter

| ID | Decision | Status |
|---|---|---|
| D-006 | Investor supplies only investor-specific facts and source documents: CAS/CGS, goals/horizon, monthly SIP budget, risk/IPS answers, constraints, liquidity/obligations and explicit authorisations/consents. The investor must not prepare internal engine JSON, fund metrics, aliases or candidate lists. | Fixed |
| D-007 | CAS/CGS ingestion is statement-date-driven, structurally validated and reconciled. Structural validity is not proof of registrar/publisher authenticity. Unknown source remains UNKNOWN/UNVERIFIED. | Fixed |
| D-008 | The portfolio denominator must explicitly declare its perimeter, sources and valuation dates. CAS mutual funds alone may be reported as an MF-only view; it must not be described as the investor's complete total portfolio. Missing external assets/cash/liabilities are UNKNOWN, not zero. | Fixed |
| D-009 | Existing holdings, transactions, active SIP mandates, values, plan/option, scheme identity and current exposures must be reconciled before portfolio-aware routing. A purchase transaction or text pattern is not an authenticated active SIP mandate. | Fixed |
| D-010 | Affordability and liquidity are separate from portfolio allocation. A user-entered SIP budget is not proof of affordability. Do not invent income, bank cash, expenses, obligations or emergency reserve. No universal six-month reserve default; use an explicit, evidence-backed investor/IPS policy. | Fixed |

## C. Investor risk contract and suitability

| ID | Decision | Status |
|---|---|---|
| D-011 | Public risk interface is exactly **Conservative, Moderate, Aggressive and Custom**. Do not expose the legacy six-level SEBI-style risk tier as the investor-facing choice. | Fixed |
| D-012 | Standard mapping is Conservative → internal Tier 2, Moderate → Tier 4, Aggressive → Tier 6. Mapping selects an approved policy profile; it does not automatically authorize every maximum-risk allocation. | Fixed |
| D-013 | Custom requires a validated investor-specific SAA whose asset weights reconcile to 100%, plus a separate explicit risk ceiling/maximum permitted scheme Riskometer. It must flow end-to-end through suitability, eligibility, scoring, allocation and trace. Never silently map Custom to Aggressive/Tier 6. | Fixed |
| D-014 | Investor risk capacity/suitability and a fund's SEBI Riskometer are different dimensions. Candidate Riskometer must be within the investor's approved ceiling; one must not be substituted for the other. | Fixed |
| D-015 | Risk profile is a permission/risk boundary, not an instruction to maximise risk. Existing portfolio deficits, concentration, look-through and marginal exposure determine where new SIP money is useful. No category is mandatory solely because of a risk label. | Fixed |

## D. Engine-owned Indian fund universe and evidence

| ID | Decision | Status |
|---|---|---|
| D-016 | The engine discovers the Indian mutual-fund scheme universe itself across eligible AMCs/categories. No investor-provided candidate universe. A user's named funds are comparison inputs only, never the market universe. | Fixed |
| D-017 | AMFI scheme/NAV feeds and AMC-published scheme documents/factsheets/monthly portfolio disclosures are primary evidence sources. Official benchmark TRI and exchange calendar sources are required for performance analysis. Third-party catalogues may aid discovery only; they do not become authoritative facts without verification. | Fixed |
| D-018 | Scheme identity is exact and multi-field: official scheme identifier, AMC, category, plan, option, ISIN where available, benchmark and lifecycle. Preserve original source labels and unresolved states. Never fabricate identifiers or fuzzy-match unresolved records into verified identity. | Fixed |
| D-019 | Every research input must carry publisher/source, source URL or retrieval locator, original-byte digest, retrieval/publication/effective/as-of dates, parser/schema version, coverage, freshness and validation/approval status. | Fixed |
| D-020 | Engine-owned data artifacts are acquired, normalized, versioned, validated, promoted and rolled back by the engine. Raw source bytes and last-known-good snapshots are preserved. Incomplete refresh cannot overwrite the last-known-good dataset. | Fixed |
| D-021 | Synthetic IDs, ISINs, NAVs, holdings, market-cap weights, TRI observations, benchmark calendars, fund metrics or reviewer approvals are never production evidence. Synthetic fixtures are allowed only in isolated tests and must be labelled TEST_ONLY. | Fixed |
| D-022 | Market coverage is measured per supported category and reported transparently. A global count (e.g. 30 or 100) cannot mask a missing category. Any minimum universe size or coverage threshold is versioned policy configuration with rationale, not a hardcoded universal constant. | Fixed |
| D-023 | New SIP candidates default to verified Direct Growth plans. Existing Regular holdings remain part of portfolio analysis; do not force redemption or Regular-to-Direct migration as a condition of SIP recommendation. Any plan migration advice is outside this SIP-only release. | Fixed |
| D-024 | Active funds and passive/index mutual funds may be evaluated on comparable category-appropriate evidence. ETF units are not included in conventional AMC SIP routing unless current operational recurring-purchase feasibility and all supporting evidence are explicitly validated. | Fixed |
| D-025 | Fund lifecycle, open/closed/subscription restrictions, minimum SIP, instalment frequency, transaction/cut-off and plan/option availability must be current and exact. Missing operational evidence blocks that candidate. | Fixed |

## E. Research, screening and portfolio-aware selection

| ID | Decision | Status |
|---|---|---|
| D-026 | Eligibility is a hard gate before scoring. Missing, stale, conflicting or unsupported mandatory data is not converted to zero, neutral score or assumed pass. | Fixed |
| D-027 | Screening is category-specific and benchmark-relative. Benchmark identity and TRI observation period must match the scheme category and decision date. No cross-category anchor substitution. | Fixed |
| D-028 | Research should evaluate multiple rolling horizons, consistency, downside/drawdown, volatility/risk-adjusted behaviour, costs, fund age/history, AUM/liquidity and operational suitability where evidence is available. One-year trailing returns or a composite score alone cannot determine selection. | Fixed |
| D-029 | Scoring methodology, metric weights, winsorisation, anchor ranges, minimum history/AUM, thresholds and category support are governed by one versioned policy with independent evidence/review. Unsupported categories remain unavailable; do not invent values to complete coverage. | Fixed |
| D-030 | Candidate evaluation is portfolio-aware: holdings-level stock/issuer, sector, market-cap, thematic and scheme exposure; overlap with existing holdings and other proposed funds; and marginal exposure after the proposed contribution. Use stable security identifiers and dated classifications. | Fixed |
| D-031 | Missing/incomplete look-through is UNKNOWN, never zero overlap or diversification. Current configured coverage thresholds (including 99.5% where specified) are policy-controlled and must be reconciled to source evidence. | Fixed |
| D-032 | Category labels and fund counts do not dictate the allocation. A category can receive zero if adequately funded, overweight, unsuitable or unsupported. No forced small-cap, mid-cap, multi-cap or thematic allocation. | Fixed |

## F. Allocation, constraints and decision behaviour

| ID | Decision | Status |
|---|---|---|
| D-033 | Strategic asset allocation (target SAA), current portfolio exposure, stability/liquidity buffer and incremental new-SIP cash-flow routing are separate quantities. | Fixed |
| D-034 | SIP routing uses verified current exposure and the projected post-contribution portfolio denominator. Candidate selection optimises the marginal improvement against approved IPS/SAA and constraints, not standalone rank. | Fixed |
| D-035 | An unfillable positive-target sleeve remains explicitly unallocated. No cross-sleeve redistribution unless the approved investor policy explicitly permits it and the resulting plan passes all gates. | Fixed |
| D-036 | Global integrity/evidence/mandate/release-gate failure produces HOLD / NO_ACTION with zero allocated and the entire requested budget unallocated. A sleeve-specific lack of eligible candidates may leave that sleeve unallocated while other independently valid sleeves proceed only if policy expressly allows partial recommendations. | Fixed |
| D-037 | Existing policy values such as 20% per-fund cap, ₹1,000 minimum ticket, ₹500 increments, maximum two new scheme introductions per 12 months, six core funds and thematic 0% default / 15% maximum with explicit IPS approval are **policy parameters**, not universal engine laws. Retain/enforce them only when present in the validated effective policy/IPS; do not duplicate or hardcode them in code. The allocator must prove the active parameters are mutually feasible before proposing amounts. | Fixed |
| D-038 | No universal cap on number of funds, new funds, or category weights may be invented by the engine. Any limit must be explicitly configured, versioned, justified and trace-bound. | Fixed |
| D-039 | Money and units follow the Decimal contract through ingestion, calculations, allocation and output. INR allocation + unallocated must reconcile exactly under the approved paise rounding rules. | Fixed |
| D-040 | Whole-budget/sleeve hold reasons, rejected candidates, constraints, data coverage, evidence dates, policy version and arithmetic must be visible in the decision report and reproducible from the decision trace. | Fixed |

## G. AI, privacy, deployment and lifecycle

| ID | Decision | Status |
|---|---|---|
| D-041 | Deterministic code and verified evidence own fund eligibility, scoring, portfolio analysis, allocation and release decisions. LLMs are optional, non-authoritative helpers for explanation/research summarisation only; provider availability must not change financial decisions. | Fixed |
| D-042 | Only free/zero-cost AI models/providers may be used. Pricing/quota must be verified from authenticated current catalogues; no paid fallback, hardcoded model IDs or automatic upgrade. If unavailable, deterministic SIP analysis still works without AI narrative. | Fixed |
| D-043 | No investor PII, PAN, folio/account identifiers, raw CAS, unmasked balances or unnecessary conversation history is sent to an external model. Consent, data minimisation and provider policy are mandatory. Investor-specific narrative cache is disabled unless an approved isolated retention design exists. | Fixed |
| D-044 | Production API requires authentication, authorization, tenant/client isolation, quotas/concurrency limits, upload/time limits, transport protection and redacted audit logs before network exposure. | Fixed |
| D-045 | The API/service is the canonical decision backend. The investor UI must support upload → mandate → review → SIP result using the same backend; no second financial logic implementation. Legacy UI stays retired until this replacement is validated. | Fixed |
| D-046 | Recommendations have immutable versioned lifecycle states. Stale data, changed holdings/mandate or scheme lifecycle events trigger review; the engine never silently changes an active SIP or issues execution/switch/redemption instructions. | Fixed |
| D-047 | Main is the only working branch. Use focused issue-referenced commits; do not create long-lived/parallel branches or merge clutter. Independent release approval remains separate from ordinary code commits. | Fixed |

## H. Release boundary

A green implementation-start baseline is not production approval. Production SIP recommendations remain blocked until the exact release commit has: all required source evidence and category coverage; authenticated daily TRI and independently verified NSE trading calendar; independent research/policy and reviewer approvals; end-to-end Custom support; CAS/portfolio reconciliation; API access controls; privacy/security review; owner-completed credential/history remediation; repository protections and independent release approval; and successful CI, security, SIP integration and release Actions.

## Explicitly parked

- Lumpsum/STP recommendation and deployment (#120).
- Tax, exit-load, redemption and switching advice (#21 and related modules).
- Trade execution and broker/registrar/payment integrations.
- ETF recurring purchase routing until operational SIP feasibility is evidenced.
