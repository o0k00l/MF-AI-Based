## ⚠️ **ARCHITECTURAL REVISION - 2024-11-01**

### **REVISED ROADMAP BASED ON INSTITUTIONAL CRITIQUE**

#### **ROADMAP CORRECTIONS**

1. **Sprint Reordering:** AI reporting moved to LAST (Sprint 5)
   - Financial mathematics and execution safety FIRST
   - AI explanation layer LAST

2. **12-Engine Sprawl → 6-Module Architecture**
   - Data & Reconciliation
   - Portfolio Diagnostics  
   - Investor Suitability
   - Investment Selection
   - Execution & Tax Safeguards
   - Decision & Explainability

3. **Mathematical Corrections:**
   - Weighted look-through overlap (not Jaccard only)
   - SAA Drift Minimizer (not optimizer)
   - Risk distribution reporting (ordinal, not cardinal)
   - NO ACTION decision branch mandatory

4. **Removed Flawed Assumptions:**
   - ❌ Zero-friction switches
   - ❌ Dogmatic multi-cap exits
   - ❌ Cardinal risk scores
   - ❌ Manufactured conviction scoring

---

# Option B — Detailed Implementation Roadmap & Deliverables
## Version 2.0 (Fiduciary Architecture Alignment)

> **Goal:** Build and verify a lean, deterministic, mathematically sound fiduciary advisor that implements the **6-Module Architecture**, enforces binary eligibility gates, calculates true look-through concentration, respects tax realities, and enshrines the **NO ACTION** principle.

---

## 1. Core Principles & Non-Negotiables

| Principle | Description |
|---|---|
| **Deterministic Math First** | All calculations (XIRR, fee bleed, look-through concentration, capital gains tax, exit load, SAA drift) are computed in pure Python before AI is called. |
| **LLM Explains, Never Computes** | The LLM receives pre-computed, verified facts only. It never calculates financial metrics. |
| **Binary Eligibility Gates** | Funds must pass data integrity, liquidity, and concentration gates before candidate scoring. |
| **The "NO ACTION" Mandate** | If no candidate provides a statistically validated improvement, the recommendation is explicitly **HOLD / NO ACTION**. |
| **Tax Reality Compliance** | All switches are treated as taxable redemptions under Sections 47 and 112A. Zero-friction myths are prohibited. |

---

## 2. Six-Sprint Implementation Sequence

| Sprint | Module / Focus | Key Deliverables & Validation Gates | Status |
| :---: | :--- | :--- | :---: |
| **0** | **Hygiene & Data Contracts** | • Lock immutable statement baseline (`09-Oct-2026`).<br>• Enforce Pydantic V2 payload schemas.<br>• Reconcile client IPS (`monthly_sip_budget: ₹99,995`). | ✅ Complete |
| **1** | **Deterministic Math & Look-Through** | • Implement **Look-Through Weighted Stock Exposure** across 23 folios.<br>• Rename optimizer to **SAA Drift Minimizer**.<br>• Reconcile configurable emergency buffer (3–6 months). | ✅ Complete / Expanding |
| **2** | **Diagnostics & Risk Distribution** | • Full transaction-level XIRR and benchmark alpha (+3.82%).<br>• Report **distribution across SEBI risk tiers** (retract cardinal 5.84).<br>• Rupee drawdown stress-testing (-₹10.5L on 20% drop). | ✅ Complete |
| **3** | **Suitability & Selection Gates** | • Implement **4 Binary Eligibility Gates** (AUM, tenure, concentration, mandate).<br>• Codify **"NO ACTION" decision branch**.<br>• Dynamic SAA derived from investor horizon and risk capacity. | ✅ Specified / Next |
| **4** | **Execution, Tax & Staging** | • Lot-level FIFO capital gains and exit load audit.<br>• Tranche 1/2/3 staging (offset gains against losses = ₹0 tax).<br>• Staggered 6-month Liquid STP @ ~6.8% yield. | ✅ Complete |
| **5** | **AI Reporting Layer & Verification** | • Gemini / Nemotron prompts restricted to narrative explanation.<br>• Zero independent LLM financial math.<br>• End-to-end regression test suite passing with code 0. | ✅ Complete |

---

## 3. Capability Status & Scope Boundary

| Functional Capability | Current Implementation Status | Architectural Boundary |
| :--- | :---: | :--- |
| **CAS xlsx Parsing & Canonical Matching** | ✅ Implemented & Tested | Option B Scope |
| **Fee Bleed Calculation (Annual & 10Y)** | ✅ Implemented & Tested | Option B Scope |
| **Newton-Raphson XIRR & Alpha** | ✅ Implemented & Tested | Option B Scope |
| **Tax-Loss Harvesting & FIFO Lots** | ✅ Implemented & Tested | Option B Scope |
| **SAA Drift Minimizer (6 Profiles)** | ✅ Implemented & Tested | Option B Scope |
| **Reverse Fed Model & Liquid STP** | ✅ Implemented & Tested | Option B Scope |
| **Look-Through Weighted Concentration** | 🟡 Sprint 1 Refinement | Option B Scope |
| **Binary Eligibility Gates & NO ACTION** | 🟡 Sprint 3 Formalization | Option B Scope |
| **Multi-Period Historical NAV Feeds** | 🔵 Future Enhancement | Option A Migration Scope |
| **Automated CAMS/KFin PDF Decryption** | 🔵 Future Enhancement | Option A Migration Scope |
| **Multi-User Relational Database / Auth** | 🔵 Future Enhancement | Option A Migration Scope |

---

## 4. Final Assessment: Option B Optimization

With the integration of the **6-Module Architecture**, **Look-Through Weighted Mathematics**, **Binary Eligibility Gates**, and the **NO ACTION** safeguard:

* **Option B is fully max-optimized as the standalone fiduciary benchmark.**
* It provides the exact mathematical engine and data contracts required to power the full enterprise platform.
* We can smoothly migrate to **Option A tomorrow** with complete confidence in our underlying financial logic.

---
*End of Roadmap v2.0*
