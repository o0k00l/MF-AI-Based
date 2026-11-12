# Normative Architecture Specification

**Status**: Normative Architecture Baseline  
**Authority Boundary**: Read-Only Mutual Fund Decision Support  
**Version**: 2.1.0 (SIP-only product baseline; 2026-11-12)  
**Supersedes**: Version 2.0.0 and conflicting informal design notes for the current SIP product scope. Historical audit findings remain evidence, not authority.

---

## 1. System Scope & Authority Boundaries

1. **Read-Only Decision Support**:
   The engine generates deterministic, reproducible monthly mutual-fund SIP recommendations only. It does NOT possess execution authority, broker connectivity, exchange/clearing routing, or trading integration.
2. **Actionability Guard**:
   All engine recommendations are strictly advisory, non-actionable proposals (`is_actionable=False`, `is_execution_authorized=False`) until validated against verified evidence and approved by a licensed fiduciary advisor or client.
3. **Data Perimeter & Trust Boundaries**:
   - **Client Data Perimeter**: Investor facts, CAS statements, and mandate configurations MUST reside outside the Git repository in an external directory specified by `MF_CLIENT_DATA_DIR`.
   - **Engine-Owned Datasets**: Public datasets (scheme master, NAV, metrics, aliases) are acquired and managed by the engine in `MF_ENGINE_DATA_DIR`. Investors must never be prompted to author or maintain internal engine files.
   - **Model Non-Authority**: External LLM/AI models are strictly non-authoritative. Models cannot invent holdings, alter eligibility gates, override SAA drift, or bypass human review.

---

## 2. Core Subsystems & Invariants

### 2.1 Ingestion & Statement Selection (`ingestion/`)
- **Statement Selection (`ingestion/statement_selection.py`)**: Selects CAS/CGS statements based strictly on embedded statement dates (`To Date`, `As On Date`), never by filesystem timestamps or lexical order.
- **CAS Parser (`ingestion/cas_parser.py`)**: Fail-closed parsing. Malformed financial rows fail closed without conversion to false zeroes.
- **Cache Staging Envelope**: Materializing the enriched portfolio cache requires a parser-issued verification envelope bound to the exact statement SHA-256 digest, statement date, holdings count, and parsed totals.
- **Active Mandate Detection**: Separates keyword-matched recurring text from authenticated mandate verification (`MANDATE_VERIFIED`). Text alone cannot populate active SIP totals.

### 2.2 Evidence Contracts & Provenance (`services/sip_evidence_contract.py`)
- Authoritative source evidence (Scheme Master, Portfolio Disclosures, Candidate Universe, Fund Metrics, Aliases) must carry cryptographic provenance: SHA-256 digests, HTTPS source URLs, reviewer attestations, and dated validity.
- Any discrepancy between candidate identity (ISIN, category, plan, benchmark) and the verified scheme master results in immediate validation failure.
- Detached Ed25519 independent reviewer approvals are verified against an independently administered trust registry root.

### 2.3 Portfolio Accounting & SAA Routing (`core/math_engine.py`, `core/portfolio_sip_controls.py`)
- **Holding Verification**: Plan type (`Direct` vs. `Regular`) and Option type (`Growth` vs. `IDCW`) are verified from scheme master records, never inferred from name substrings.
- **Central SAA Single Source of Truth**: The validated `data/policy/asset_allocation.json` policy is the sole authoritative source for standard tier targets. Hardcoded duplicates are strictly prohibited.
- **Mathematical Post-Contribution Allocation**: Incremental routing derives contributions that move the post-contribution portfolio (`post_contribution_val = total_cur + monthly_sip`) toward approved targets.
- **Unfillable Sleeve Protection**: Underweight sleeves without eligible candidates retain their pro-rata contribution as unallocated; redistribution to other sleeves is prohibited without explicit IPS authorization.

### 2.4 Suitability & Eligibility Gates (`core/eligibility.py`)
- Candidate funds must pass all statutory and risk suitability gates before scoring or ranking.
- Scoring APIs accept only validated eligible candidate types, not raw unvetted candidates.
- Threshold overrides fail closed unless explicitly authorized by policy governance.

### 2.5 Decimal Money Contract
- All monetary amounts (INR), units, and NAVs must strictly adhere to the `Decimal` money contract with explicit scale and rounding (e.g. `quantize_inr` with `ROUND_HALF_UP`).
- Intermediate binary float conversions across ingestion, calculations, and outputs are prohibited.

### 2.6 Decision Traceability (`core/traceability.py`)
- Every recommendation produces an RFC 8785 (JCS) canonical SHA-256 decision hash.
- Lineage covers running commit SHA, policy version, policy digest, schema version, exact source digests, and candidate-level gate/allocation arithmetic.

---

## 3. Normative Traceability Matrix

| Requirement Clause | Normative Standard | Implementation Module | Primary Regression Tests | Status |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-001**: CAS Cache Staging Envelope | Require source digest & statement binding | `ingestion/cas_parser.py` | `tests/test_cas_cache_integrity.py` | **Implemented** |
| **REQ-002**: Active SIP Mandate vs Text | Distinguish text pattern from mandate | `ingestion/cas_parser.py` | `tests/test_active_sip_detection.py` | **Implemented** |
| **REQ-003**: Screening Policy Binding | Single validated screening policy | `core/eligibility.py` | `tests/test_issues_50_26_84_55_remediations.py` | **Implemented** |
| **REQ-004**: Multi-Dimensional Concentration | Overlap, issuer, sector, thematic limits | `core/math_engine.py` | `tests/test_issues_50_26_84_55_remediations.py` | **Implemented** |
| **REQ-005**: Exact Metrics & Alias Binding | 4-tuple scheme identity & provenance | `core/math_engine.py` | `tests/test_sip_metrics_provenance.py` | **Implemented** |
| **REQ-006**: Decimal Money Contract | Exact Decimal for all INR & units | `core/models.py`, `core/math_engine.py` | `tests/test_financial_model_defaults.py` | **Implemented** |
| **REQ-007**: Decision Trace RFC 8785 Hash | Deterministic JCS SHA-256 lineage | `core/traceability.py` | `tests/test_decision_traceability.py` | **Implemented** |
| **REQ-008**: Manifest Path Resolution | Resolve snapshots from manifest | `advisor.py` | `tests/test_issues_24_120_121_remediations.py` | **Implemented** |
| **REQ-009**: Atomic Promotion & Rollback | Directory swap preserving last-known-good | `services/engine_bootstrap.py` | `tests/test_issues_24_120_121_remediations.py` | **Implemented** |
| **REQ-010**: Anti-Synthetic Refresh Pipeline | Require detached Ed25519 signature by default | `services/acquisition/pipeline.py` | `tests/test_financial_data_acquisition.py` | **Implemented** |
| **REQ-011**: SIP-only scope boundary | Keep lump-sum/STP outside the current SIP product path | SIP API/service boundary | SIP scope regression tests | **Required** |
| **REQ-012**: SAA Drift Mathematical Routing | Post-contribution denominator & unallocated | `core/portfolio_sip_controls.py` | `tests/test_issues_24_120_121_remediations.py` | **Implemented** |
| **REQ-013**: Tier 6 Equity-Only Guard | Fail closed without explicit authorization | `core/math_engine.py` | `tests/test_tier6_authorization_invariants.py` | **Implemented** |
| **REQ-014**: SAA Single Source of Truth | Dynamic policy map from asset_allocation.json | `core/models.py` | `tests/test_saa_policy_authoritative.py` | **Implemented** |
| **REQ-015**: Canonical UI Startup Contract | Root launcher delegates to read-only notice | `app.py`, `ui/app.py` | `tests/test_ui_retirement.py` | **Implemented** |
| **REQ-016**: Tax & Legal Release Gate | Keep tax/exit-load APIs disabled pending review | `core/redemption_engine.py` | `tests/test_import_safety.py` | **Enforced (Disabled)** |
| **REQ-017**: AI Provider Key Access & Scope | Zero cost / quota verified before provider call | `providers/` | External provider account / secret setup | **Pending Provider Access** |
| **REQ-018**: Main Branch Protection Ruleset | Enforce required PR approvals & CI checks | `.github/workflows/` | GitHub Repository Ruleset Settings | **Repository Admin Gate** |

---

## 4. Architecture Decision Records (ADRs)

### ADR-1: Removal of Client-Authored Engine Datasets
- **Context**: Legacy advisor expected investors to author `fund_metrics.json` and `fund_aliases.json`.
- **Decision**: All public fund datasets are strictly engine-owned, acquired from official feeds (AMFI) and promoted via cryptographically verified staging bundles.
- **Consequences**: Investors only provide their private statement and dated mandate inputs.

### ADR-2: Cryptographic Promotion Gate vs. Boolean Attestation
- **Context**: Pipelines previously allowed caller booleans (`reviewer_attested=True`) to promote staging bundles.
- **Decision**: Every bundle promotion requires a detached Ed25519 signature verified against a trust registry root, bound to exact source digests and commit SHA.
- **Consequences**: Eliminates self-attestation and guarantees independent reviewer authority.

### ADR-3: Post-Contribution SAA Denominator Routing
- **Context**: Allocating new contributions based solely on pre-contribution drift can cause severe overshoot on small portfolios.
- **Decision**: Mathematical projection computes target allocations over the post-contribution portfolio total (`portfolio_total + sip_budget`). Underweight sleeves without eligible candidates retain their allocation as unallocated without cross-sleeve redistribution.
- **Consequences**: Deterministic budget reconciliation and strict adherence to client IPS bounds.


---

## 5. Product Decision Baseline — 2026-11-12 (Normative)

This section is the final product/engineering contract for the current delivery. It is governed by `docs/SIP_ENGINE_DECISION_REGISTER.md`. If an older section, audit note, policy comment or issue body conflicts with this section or the decision register, record and fix the conflict; do not silently apply the older rule.

### 5.1 Product scope and authority

- The current product is **monthly mutual-fund SIP recommendation only**.
- Lumpsum/STP, redemption, switching, tax/exit-load optimisation and trade execution are outside this delivery. Existing modules may remain for historical compatibility but must not be surfaced as supported capabilities in the SIP workflow.
- Recommendations are read-only and non-executable. No broker, exchange, RTA, AMC, bank or payment execution integration.
- The deterministic backend owns all financial decisions. The UI calls the backend and contains no duplicate financial logic.
- The retired Streamlit dashboard remains retired until a replacement SIP journey is implemented and validated.

### 5.2 Investor contract and portfolio perimeter

- Investor inputs are CAS/CGS and investor-specific facts: goal/horizon, monthly SIP budget, risk/IPS answers, constraints, liquidity/obligations and explicit authorisations/consents.
- Investors do not author or maintain engine configuration, scheme masters, fund metrics, aliases, research files or candidate-universe JSON.
- CAS/CGS statement selection uses embedded statement dates. Structural validity, document-claimed registrar and authenticated publisher identity are separate fields. Unknown publisher remains UNKNOWN/UNVERIFIED.
- The analysis declares its portfolio perimeter, sources and valuation dates. A CAS-only analysis is labelled mutual-fund-only; it must not claim to represent the complete total portfolio. Missing external assets, cash or liabilities are unknown, not zero.
- Existing holdings, transactions, plan/option, scheme identity and actual active SIP mandates must be reconciled before routing. A purchase or a text pattern is not an authenticated active SIP mandate.
- Affordability and liquidity are distinct from SAA. Do not invent income, bank cash, expenses, obligations or reserve. No universal six-month emergency-reserve default; use explicit, source-backed investor/IPS policy.

### 5.3 Public risk contract and suitability

The investor-facing risk choices are exactly:

| Public choice | Standard internal policy mapping |
|---|---|
| Conservative | Tier 2 |
| Moderate | Tier 4 |
| Aggressive | Tier 6 |
| Custom | Investor-specific SAA + separate risk ceiling |

- The legacy six-level scale is an internal policy/Riskometer scale, not the public investor interface.
- Custom SAA asset weights must be finite, non-negative and reconcile to 100%. A separate explicit maximum permitted fund Riskometer/risk ceiling is mandatory.
- Custom must flow through suitability, eligibility, scoring, allocation, decision trace and reporting. It must never silently inherit Aggressive/Tier 6.
- Investor risk capacity and a scheme's SEBI Riskometer are separate dimensions. Scheme risk must not exceed the investor's approved ceiling.
- A risk profile defines a permitted risk boundary; it does not command maximum risk. Actual portfolio gaps, concentration and candidate marginal exposure determine the new SIP.

### 5.4 Indian fund discovery and evidence ownership

- The engine discovers the Indian mutual-fund universe itself across eligible AMCs and supported categories. User-supplied fund names are comparison inputs only, never the universe.
- AMFI scheme/NAV sources, AMC-published scheme documents/factsheets/monthly portfolio disclosures, official benchmark TRI and independently verified exchange calendars are primary evidence. Third-party catalogues may aid discovery but are not authoritative facts without verification.
- Exact identity includes scheme identifier, AMC, category, plan, option, ISIN where available, benchmark and lifecycle. Ambiguous identity remains unresolved; no fabricated IDs, aliases or fuzzy verified matches.
- Every source carries publisher/source, URL or retrieval locator, original-byte digest, retrieval/publication/effective/as-of dates, parser/schema version, coverage, freshness and approval status.
- The engine owns acquisition, normalization, versioning, validation, promotion and rollback. Failed refresh preserves last-known-good data.
- No synthetic scheme IDs, ISINs, NAVs, holdings, market-cap weights, TRI observations, calendars, fund metrics or reviewer approvals are production evidence. Synthetic fixtures are TEST_ONLY.
- Candidate universe completeness is reported per supported category. A global candidate count cannot hide a missing category. Any minimum count/coverage threshold is versioned policy, not a hardcoded universal constant.
- New SIP candidates default to verified Direct Growth. Existing Regular holdings remain in portfolio analysis; no forced migration or redemption.
- Active and passive/index mutual funds can be evaluated with category-appropriate methodology. ETF units are excluded from conventional AMC SIP routing unless current recurring-purchase feasibility is independently evidenced.

### 5.5 Research and candidate evaluation

- Eligibility is a hard gate before scoring. Missing, stale, conflicting or unsupported mandatory evidence is not zero, neutral or pass.
- Scoring is category-specific and benchmark-relative. No cross-category anchor substitution.
- Research evaluates multiple rolling horizons, consistency, downside/drawdown, volatility/risk-adjusted behaviour, expenses, fund age/history, AUM/liquidity and operational suitability where supported by evidence. Trailing 1-year returns or a composite score alone cannot decide.
- Scoring methodology, weights, winsorisation, anchor ranges, history/AUM requirements and category support live in one versioned, independently reviewed policy.
- Candidate selection evaluates current and proposed stock/issuer, sector, market-cap, theme and scheme exposures, including marginal exposure after the SIP. Use stable security identifiers and dated classifications.
- Missing/incomplete look-through is UNKNOWN, never zero overlap. Coverage thresholds (including 99.5% where configured) are policy-controlled, not duplicated in code.

### 5.6 SIP allocation and fail-closed behaviour

- Target SAA, current exposure, stability/liquidity buffer and incremental monthly SIP routing are separate values.
- Routing uses verified current exposure and the projected post-contribution denominator. A category may receive zero where it is adequately funded, overweight, unsuitable or unsupported.
- No forced small-cap, mid-cap, multi-cap or thematic allocation based on risk label or category quotas.
- Unfillable positive-target sleeves remain unallocated. No cross-sleeve redistribution unless the effective approved IPS/policy explicitly allows it.
- Global integrity, evidence, mandate or release-gate failure returns HOLD / NO_ACTION, zero allocation and the entire budget unallocated. Sleeve-specific candidate absence may leave only that sleeve unallocated when the approved policy permits an otherwise valid partial proposal.
- Existing numeric constraints (per-fund cap, min ticket, increments, fund count, new-fund introductions and thematic limits) are effective only when explicitly present in the validated policy/IPS. They are configurable policy parameters, not universal engine constants. The allocator must prove the active constraints are jointly feasible before proposing an amount.
- Decimal money arithmetic is mandatory end-to-end. Allocated plus unallocated INR reconciles exactly under the approved rounding contract.

### 5.7 AI, privacy, deployment and lifecycle

- AI/LLM is optional and non-authoritative. It may assist narrative explanation only. It cannot determine eligibility, ranking, holdings, overlap, allocation or release approval.
- Only free/zero-cost AI models are permitted. Pricing/quota must be verified from authenticated current catalogues; no paid fallback or hardcoded model IDs. AI unavailability must not change deterministic SIP results.
- No investor PII, PAN, folio/account identifiers, raw CAS or unmasked balances are sent to external models. Consent, data minimisation and privacy review are mandatory. Investor-specific narrative caching is disabled unless an approved isolated design exists.
- Production API requires authentication, authorization, tenant isolation, quotas, concurrency/upload/time limits, transport security and redacted audit logs before network exposure.
- The canonical user journey is upload → mandate → reconciliation → engine-owned discovery/research → portfolio-aware SIP recommendation → explanation/report. The API/service is the sole decision backend; legacy UI remains retired until replacement is validated.
- Recommendation versions are immutable. Changed holdings, mandate, evidence freshness or scheme lifecycle trigger review. No silent SIP modification or execution instruction.

### 5.8 Release boundary

An implementation-start green light is not production approval. Production remains blocked until the exact release commit demonstrates live source coverage, authenticated daily TRI, independently verified NSE calendar, approved research/policy and reviewer evidence, end-to-end Custom support, CAS/portfolio reconciliation, API access controls, privacy/security review, credential/history remediation, repository protection/independent release approval, and green CI, Security, SIP integration and release workflows.

### 5.9 Version history

- **2.1.0 (2026-11-12):** Consolidated user decisions into a SIP-only product baseline; formalised 3+1 public risk contract, Custom SAA/risk ceiling, portfolio-marginal allocation, engine-owned Indian discovery, policy configurability, AI non-authority and release boundaries.
- **2.0.0 (2026-11-04):** Earlier architecture baseline; superseded where it conflicts with 2.1.0 and the decision register.
