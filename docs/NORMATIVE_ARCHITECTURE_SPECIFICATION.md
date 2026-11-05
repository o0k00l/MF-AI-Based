# Normative Architecture Specification

**Status**: Normative Architecture Baseline  
**Authority Boundary**: Read-Only Mutual Fund Decision Support  
**Version**: 2.0.0 (SEBI Master Circular 2026 Aligned)  
**Supersedes**: All informal design documents, legacy docstrings, and unversioned proposals prior to 2026-11-04.

---

## 1. System Scope & Authority Boundaries

1. **Read-Only Decision Support**:
   The engine generates deterministic, reproducible mathematical analyses and proposed SIP/lump-sum allocation scenarios. It does NOT possess execution authority, broker connectivity, exchange/clearing routing, or trading integration.
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
| **REQ-011**: Fail-Closed Lumpsum Decision | Block repository-relative metrics fallback | `services/lumpsum_recommendation.py` | `tests/test_issues_24_120_121_remediations.py` | **Implemented** |
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
