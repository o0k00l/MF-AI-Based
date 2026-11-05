# Normative Architecture Specification

**Status**: Normative Architecture Baseline  
**Authority Boundary**: Read-Only Mutual Fund Decision Support  
**Version**: 1.0.0 (SEBI Master Circular 2026 Aligned)

---

## 1. System Scope & Authority Boundaries

1. **Read-Only Decision Support**: The system generates deterministic, reproducible mathematical analyses and proposed SIP/allocation scenarios. It does NOT possess execution authority, broker connectivity, or trading integration.
2. **Authority Limits**: All SIP recommendations are non-actionable conditional scenarios until validated against verified evidence and approved by a qualified advisor or client.
3. **Data Perimeter**: Client data (CAS, transactions, IPS configs) MUST reside outside the Git repository in an external directory pointed to by `MF_CLIENT_DATA_DIR`.

---

## 2. Core Subsystems & Responsibilities

### 2.1 Ingestion & Statement Selection
- **Statement Selection (`ingestion/statement_selection.py`)**: Selects candidate CAS/CGS statements based strictly on validated embedded statement valuation dates (`To Date`, `As On Date`), never by lexical filename or filesystem timestamps.
- **CAS Parser (`ingestion/cas_parser.py`)**: Strict fail-closed parsing of CAS PDF/Excel formats. Unknown transaction types or corrupted financial rows fail closed without silent omission.

### 2.2 Evidence Provider Contract (`services/sip_evidence_contract.py`)
- Authoritative source evidence (Scheme Master, Portfolio Disclosures, Candidate Universe, Fund Metrics, Aliases) must carry cryptographic provenance: SHA-256 digests, HTTPS source URLs, reviewer attestations, and dated validity.
- Any discrepancy between candidate identity (ISIN, category, plan, benchmark) and the verified scheme master results in immediate validation rejection.

### 2.3 Portfolio Accounting & SAA Drift (`core/math_engine.py`, `core/portfolio_sip_controls.py`)
- **Holding Verification**: Plan type (Direct vs. Regular) and Option type (Growth vs. IDCW) must be established from verified scheme master evidence, never inferred from name substrings.
- **SAA Policy**: The single source of truth for SAA targets is `data/policy/asset_allocation.json`. Hardcoded duplicates in source code are prohibited.
- **Empty Denominator Defense**: When active holdings are empty or total current value is non-positive, portfolio diagnostics return an explicit `UNAVAILABLE` status.

### 2.4 Suitability & Candidate Eligibility Gates (`core/eligibility.py`)
- Candidate funds must pass all statutory and risk suitability gates before scoring or ranking.
- Investor Risk Tiers (Conservative = Tier 2, Moderate = Tier 4, Aggressive = Tier 6) must resolve canonically across all parsers without enum vs. string discrepancies.

### 2.5 Tax & Legal Release Boundary (`core/redemption_engine.py`, `tax/`)
- Statutory tax classification (LTCG vs. STCG), lot holding-period calculations, and exit-load assessments remain fail-closed and disabled pending independent Indian legal and tax review.

### 2.6 Decision Traceability (`core/traceability.py`)
- Complete cryptographic decision trace hashes are computed over canonical RFC 8785 (JCS) payloads to provide full lineage from source bytes to final recommendation output.
