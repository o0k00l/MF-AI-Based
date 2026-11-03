# Fiduciary Mutual Funds Copilot (Autonomous Institutional Wealth Engine)

A deterministic, conflict-free, fee-only fiduciary wealth management and portfolio decision-support engine for Indian mutual funds, engineered with **Zero-LLM Math**, governed by **The 5 Universal Invariants**, and executed via an **Autonomous Fiduciary Selection Engine**.

---

## 🏛️ System Status: Verification Phase — HOLD Mandate Active (v3.2)

| Module | Implementation Status | Mathematical Engine & Verification Evidence |
| :--- | :--- | :--- |
| **1. Ingestion & Reconciliation** | ✅ Verified (100% Match) | `parse_cas()`, `load_holdings_from_cas_excel()`. Exact reconciliation to CAS statement (`cas_detailed_report_2026_10_09_174452.xlsx`): Cost = ₹44,29,929.64, Valuation = ₹51,70,911.38, Gain = ₹7,40,981.74 across 23 active schemes in 15 unique folios (reconciled with 85 total CAS entries). |
| **2. Portfolio Diagnostics** | ✅ Verified | `calculate_fee_bleed()` (₹40,970.52/yr leakage; ₹8.05L 10Y compounded loss), `calculate_weighted_lookthrough_overlap()`, `calculate_thematic_exposures()`, `calculate_lookthrough_stability_buffer()` (7.54% cushion). |
| **3. Universal Suitability & SAA** | ⚠️ Logic tests pass; client release blocked | SAA targets, new-SIP routing and current portfolio exposures are separate quantities. Tier 6 SAA target is 95% equity / 5% debt; its new-SIP routing may be 100% equity only when the IPS override is explicit. No allocation is actionable while the client mandate is HOLD. |
| **4. Autonomous Selection Engine** | ✅ Verified | 10 Binary Fiduciary Gates (fail-closed Gate 4 with `is_verified_passive_scheme`), Universal 4-Slot Passive Index Fallback, Normalized 6-Pillar Composite Scoring (0–100), Candidate-Specific Constituent Look-Through Overlap, Macro Look-Through Deficit Resolution. |
| **5. Statutory Tax Architecture** | ⚠️ Core regression suite passes; statutory release requires source review | Section 198 equity-oriented status uses the annual average of monthly averages of opening and closing figures (direct funds: >=65%; qualifying exchange-traded FoFs: >=90% in underlying fund units and >=90% underlying domestic equity). Original Section 50AA (through 31 Mar 2026) uses annual-average daily closing domestic-equity figures (<=35%). Section 76 (from 1 Apr 2026) uses annual-average daily closing debt/MM or FoF-unit figures. MLDs are a separate statutory inclusion. Acquisition date, transfer date and complete evidence coverage are mandatory where relevant. Legal interpretation must still be checked against the applicable Act, Rules and transaction facts before tax advice. |
| **6. Mandate Runtime Control** | ✅ Verified (Hold Enforced + Propagated) | Runtime mandate governance: `MandateExecutionState.HOLD_PENDING_TRI_VALIDATION`, `is_execution_authorized = False`. Mandate state now rendered in ALL 3 deliverables with execution status interpretation. Deployment plans marked non-actionable; `assert_mandate_execution_authorized()` strictly blocks live trade execution. |
| **7. Reproducible Benchmark Engine** | ⚠️ Calculation tests pass; alpha release BLOCKED | Cash-flow-matched TRI calculation exists, but checked-in fixtures are monthly/interpolated and lack an authenticated historical NSE source document and independent exchange trading calendar. Therefore no benchmark alpha or fund-selection claim is release-eligible from these fixtures. Do not use the rounded sample XIRRs in this README as verified performance evidence. |
| **8. Test Harness & Deliverables** | ⚠️ Automated checks pass with skipped private-data tests | Latest recorded GitHub Actions run: P0 invariant suite 13 passed / 3 skipped; P0 correctness regressions 73 passed; public logic scorecard 67/67. TRI fixture integrity checks pass, but TRI alpha release eligibility is BLOCKED. Private CAS reconciliation and end-to-end client release have not been verified in this public CI run. |

---

> [!IMPORTANT]
> ### ⚖️ Fiduciary Invariant: Zero Hardcoding & Zero Fabrication Mandate
> In fiduciary financial engineering, **information must never be fabricated, simulated, or hallucinated**, and **no hardcoded fund brand names or placeholder metrics may be injected into recommendation outputs**.
> 
> If required financial metrics are missing, or if no candidate scheme dynamically passes all binary fiduciary gates within the audited candidate universe (`fund_metrics.json`), the engine **MUST explicitly fail safe** (e.g., raise a structured validation exception or output an auditable **NO ACTION / HOLD** decision). In financial advisory systems:
> $$\mathbf{\text{Explicit Safe Failure}} \gg \mathbf{\text{Fabricated / Hardcoded Fallbacks}}$$

---

## 📐 Deployment Heuristics and Portfolio Controls

The rules below are implementation policies or configurable heuristics, not universal financial laws or statutory requirements. They must be overridden where the investor's IPS, cash-flow needs, market conditions, verified tax facts or mandate requires it.

### 1. Configurable Lumpsum Deployment Heuristic (20/80)
A configurable starting point for phasing a lumpsum—not a guarantee against market timing or sequence-of-returns risk, and not suitable for every investor or market condition:

$$\text{Day 1 Immediate Core Equity Anchor} = 20\% \times \text{Lumpsum}$$
$$\text{Tax-Shielded Arbitrage Parking Pool (@ ~6.8\% Yield)} = 80\% \times \text{Lumpsum}$$
$$\text{Monthly Systematic Transfer (STP)} = \frac{80\% \times \text{Lumpsum}}{\text{STP Duration}}$$

* **Tax classification is conditional:** An arbitrage fund is not automatically an equity-oriented fund merely because it uses derivatives or is labelled arbitrage. Verify its statutory domestic-equity allocation and the applicable law for the actual sale date. Do not treat the parking vehicle as risk-free, guaranteed-yield or a guaranteed tax shelter. No fixed tax saving is claimed.
* **Illustrative duration bands:** 6 months ($\le$ ₹5L), 9 months (₹5L–₹10L), 12 months (₹10L–₹25L), 18 months (> ₹25L). Confirm liquidity, exit loads, taxes and investor risk before applying.
* **Multi-Slot SAA Preservation:** For big-ticket deployments ($\ge$ ₹5L), the 80% STP branches across Flexi (50%), Mid (35%), and Large (15%).

---

### 2. Core Equity Routing and Optional Satellite
The three core sleeves below are normalized to **100% of the core equity budget**: Flexi-cap 26.3%, mid-cap 52.6%, and large-cap 21.1%. They sum to 100%. Thematic/sectoral exposure is **not a fourth default core slot** and is not added on top of this 100%. Any separately authorized thematic satellite must be funded by reducing the core equity budget first, must have a separately stated portfolio-level cap, and must pass its own look-through and valuation gates. When no thematic candidate passes, its allocation is 0% and no automatic redistribution is permitted.
*(Starter Rule: For portfolios < ₹5L AUM or monthly budget < ₹15,000, Slot 4 and Slot 3 are set to 0.0% to prevent micro-fragmentation; equity capital consolidates into a 2-fund engine: 60% Core Flexi-Cap / 40% Mid-Cap Alpha).*

---

### 3. The Universal Tax Shield Siphon (Section 112A / Section 198)
Switches between Regular and Direct plans are legally transfers under Section 2(47) and taxable under Sections 45 & 112A (1961 Act) or Section 198 (2025 Act):
* **Tranche Siphon:** May use the applicable annual LTCG exemption (currently ₹1,25,000 for eligible equity-oriented LTCG under the stated regime), after verifying realized gains, losses, prior utilization, asset classification and the relevant sale-date law. It is not a blanket tax-free withdrawal allowance.
* **Holding-period / exit-load control:** Check each scheme's actual exit-load schedule and each lot's acquisition anniversary. A 12-month tax holding period and a scheme-specific exit-load period are separate tests; neither should be hard-coded as a universal 1%/20% rule.

---

### 4. The Fiduciary Personal Redemption Engine
Systematically liquidates capital while minimizing tax liability and preserving core wealth compounding:
* **Stage 1 (Organic Cash):** Deployable bank cash above the client's emergency reserve (₹0 tax, ₹0 exit load).
* **Stage 2 (Tactical Regular Bleed):** Underperforming Regular plans with harvestable capital losses (Section 70 / Section 108) or mature LTCG (utilizing the ₹1.25L exemption, ₹0 exit load).
* **Stage 3 (Thematic Trim):** Over-allocated, overheated thematic holdings (Defence, Energy) trading at peak valuations.
* **Stage 4 (Core Equity Siphon):** Long-term core Direct compounders held >365 days.
* **Modes:** Supports both **Gross Redemption** (gross withdrawal) and **Net Payout** (grosses up capital to cover statutory taxes and exit loads).

---

### 5. Universal SAA & Look-Through Stability Offset Engine
Governs asset allocation across all 6 SEBI Regulatory Risk Tiers based on audited look-through holdings:

$$\text{Look-Through Stability Buffer } (S) = \frac{\sum_{i=1}^{N} V_i \times (\text{DebtPct}_i + \text{CashPct}_i)}{\sum_{i=1}^{N} V_i} \times 100$$
$$\text{Threshold}(T) = \max\bigl(0.0,\; D_{\text{target}}(T) - \text{Tolerance}(T)\bigr)$$

The SAA target, tolerance band and resulting new-SIP routing are distinct. The engine reads the base new-SIP split and the SAA debt target/tolerance from `data/policy/asset_allocation.json`; it must not duplicate these values in code. $\text{Final Debt SIP \%} = \begin{cases} 
0.0\% & \text{if } S \ge \text{Threshold}(T) \quad (\text{Stability Cushion Organically Satisfied}) \\
D_{\text{base}}(T) & \text{if } S < \text{Threshold}(T) \quad (\text{Deficit Funded via Stability Vehicle})
\end{cases}$$

| SEBI Risk Tier | SAA Debt Target | SAA Eq Target | Tolerance | Threshold ($D_{\min}$) | Lalit's $S = 7.54\%$ | Resulting SIP Split | Stability Vehicle Assigned |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| **Tier 6 (Very High)** | 5.0% | 95.0% | $\pm 5.0\%$ | **0.0%** | $7.54\% \ge 0.0\%$ | **100% Eq / 0% Debt** | None (Satisfied organically) |
| **Tier 5 (High)** | 10.0% | 90.0% | $\pm 5.0\%$ | **5.0%** | $7.54\% \ge 5.0\%$ | **100% Eq / 0% Debt** | **None (Satisfied organically)** |
| **Tier 4 (Mod. High)** | 25.0% | 75.0% | $\pm 5.0\%$ | **20.0%** | $7.54\% < 20.0\%$ | **85% Eq / 15% Debt** | Policy-defined new-SIP split; candidate evidence required |
| **Tier 3 (Moderate)** | 30.0% | 70.0% | $\pm 5.0\%$ | **25.0%** | $7.54\% < 25.0\%$ | **60% Eq / 40% Debt** | Policy-defined new-SIP split; candidate evidence required |
| **Tier 2 (Low to Mod.)**| 60.0% | 40.0% | $\pm 4.0\%$ | **56.0%** | $7.54\% < 56.0\%$ | **30% Eq / 70% Debt** | Policy-defined new-SIP split; candidate evidence required |
| **Tier 1 (Capital Pres.)**| 80.0% | 20.0% | $\pm 3.0\%$ | **77.0%** | $7.54\% < 77.0\%$ | **0% Eq / 100% Debt** | Dynamic Short-Term Debt Direct (AAA/Sov) |

---

## 🤖 Autonomous Selection Engine (Zero Brand Hardcoding)

Selection across all sleeves is governed by a **5-step mathematical algorithm**:

```
Candidate Universe (fund_metrics.json)
       │
       ▼
[Step 1: 10 Quantitative Eligibility Gates]
  • Gate 1: Single-AMC Net Worth Exposure <= 30.0% (Counterparty Governance Control)
  • Gate 2: AUM Bounds (Mid-Cap <= ₹40k Cr; Flexi <= ₹175k Cr; prevents size & liquidity drag)
  • Gate 3: Scheme Top-10 <= 55.0% & Sector <= 35.0% | Portfolio Look-Through Sector <= 40.0%
  • Gate 4: Risk-Adjusted Sharpe & Alpha Gate (STRICTLY FAIL-CLOSED)
            - Rejects None, NaN, inf, booleans, empty strings, malformed strings.
            - Active Hurdle: 3Y Sharpe >= 0.40 AND 3Y Jensen's Alpha > 0.0% vs TRI Benchmark.
            - Verified Passive Exemption: is_verified_passive_scheme() verifies genuine Index/ETF structure;
              disqualifies active schemes disguised with index keywords.
  • Gate 5: Capture Ratio Asymmetry (Downside <= 100% OR Upside >= Downside; zero mock defaults)
  • Gate 6: Mandate Suitability & Riskometer Alignment (Starters barred from thematic)
  • Gate 7: Data Integrity & Factsheet Provenance (Confidence >= 0.80; zero synthetic mocks)
  • Gate 8: Operational History >= 3.0 yrs & Lead Manager Tenure >= 2.0 yrs
  • Gate 9: Thematic Satellite Cap <= 15.0% of SIP (0% for Starters < ₹5L AUM)
  • Gate 10: 100% Direct Plan Mandate (Zero Regular Plans; eliminates 80-120 bps trail bleed)
       │
       ├─ Active Funds Pass ──► [Step 2: Standardized Fiduciary Pillar Scoring (0-100)]
       │                        Evaluates 6 Normalized Pillars using Empirical Category Anchors:
       │                        • Pillar 1: Multi-Horizon Returns (25% weight; 1Y Return = 10% effective momentum)
       │                        • Pillar 2: Risk-Adjusted Quality (20% weight; Sharpe & Capture Asymmetry)
       │                        • Pillar 3: Cost Efficiency (15% weight; Direct TER relative to category median)
       │                        • Pillar 4: Constituent Overlap Benefit (15% weight; O(C,P) against actual holdings)
       │                        • Pillar 5: Stability & Downside Buffer (15% weight; Cash & Debt buffers)
       │                        • Pillar 6: Global Diversification (10% weight; International equity ballast)
       │
       └─ Active Funds Fail ──► [Step 3: Four-Slot Passive Index Fallback Policy]
                                • Slot 1 (Flexi-Cap): Nifty 500 / Flexi Cap Index Direct -> NO ACTION / HOLD
                                • Slot 2 (Mid-Cap): Nifty Midcap 150 Index Direct -> NO ACTION / HOLD
                                • Slot 3 (Large-Cap): Nifty 50 Index Direct -> NO ACTION / HOLD
                                • Slot 4 (Thematic Satellite): Strictly collapses to 0.0% (NO ACTION / HOLD)
       │
       ▼
[Step 4: Look-Through Deficit Matcher for Slot 4 & Thematic Taper Exact Algebra]
  Scans 5 Macro Themes: Defence (5.98%), Power (5.11%), PSU (6.19%), Commodities (2.40%), Healthcare (1.55%).
  Identifies Healthcare as the largest portfolio deficit (1.55% vs 5.50% Nifty 500 TRI weight).
  Terminal Exposure Ceiling: Benchmark weight (5.50%) + Tactical Tolerance (2.00%) = 7.50% Policy Ceiling.
  
  Closed-Form Taper Equation:
  (80,396.14 + 14,250 * m) / (5,170,911.38 + 100,000 * m) = 0.075
  m = 307,422.2135 / 6,750 = 45.5440 months!
  • Month 39: 7.013% < 7.50% (Safe)
  • Month 40: 7.092% < 7.50% (Safe)
  • Month 45: 7.462% < 7.50% (Safe)
  • Month 46: 7.532% >= 7.50% (Breaches Ceiling -> Automatic Taper to 0.0% Triggered)
       │
       ▼
[Step 5: Deterministic Scheme-Level Folio Router]
  find_client_direct_folio matches 4-point verification: Exact AMC + Scheme ISIN + Direct Plan + Growth Option.
  Strictly eliminates scheme-drift, IDCW dividend payout traps, and hardcoded brand names.
```

---

## 🏛️ Statutory Tax Architecture (Date-Aware Mapping)

| Regulatory Provision | Pre-1 April 2026 (Income-tax Act, 1961 & Finance Act 2024) | Post-1 April 2026 (Income-tax Act, 2025) | Operational Fiduciary Rule |
| :--- | :--- | :--- | :--- |
| **Switch as Transfer** | **Section 45 read with Section 2(47)** | **Transfer Provision (Section 45 equiv.)** | Switches between Regular and Direct are taxable transfers. |
| **Equity LTCG** | **Section 112A** (12.5% tax; ₹1.25L annual exemption) | **Section 198** (Special provision for qualifying equity MF LTCG) | Applicable to funds with domestic equity **strictly $> 65.0\%$**. |
| **Equity STCG** | **Section 111A** (20.0% tax on holding $\le$ 365 days) | **Section 196** (Short-term capital gains on equity assets) | Immature lots locked to Day 366. |
| **Specified Mutual Funds ($\ge$ 01-Apr-2023 units)** | **Section 50AA** (Deemed STCG taxed at marginal slab rates) | **Section 76** (Special computation for specified funds & MLDs) | Funds investing $> 65\%$ in debt/money market or $\le 35\%$ equity. |
| **Debt Units ($<$ 01-Apr-2023 units)** | **Section 48** (Grandfathered debt LTCG with indexation) | **Section 48 / Enactment Grandfathering** | Retains indexation benefits; exempt from deemed STCG. |
| **Current-Year Capital Loss Set-off** | **Section 70** (Intra-head capital loss set-off) | **Section 108** (Current-year intra-head loss set-off) | Harvest capital losses to offset mature capital gains. |
| **Loss Carry-Forward (8 Years)** | **Section 74** (Carry forward and set-off of capital losses) | **Section 111** (Carry forward and set-off of capital losses) | Unabsorbed capital losses carried forward up to 8 assessment years. |

---

## 🔒 Mandate Governance & Runtime Hold Control

All recommendations are governed by persistent client mandate state loaded from `config.json`:

```json
"mandate": {
  "mandate_state": "HOLD_PENDING_TRI_VALIDATION",
  "is_execution_authorized": false,
  "hold_reasons": [
    "Existing holdings retained; zero forced redemptions",
    "Redemptions frozen pending April 2027 review",
    "New core SIP deployment on hold pending benchmark TRI and look-through validation"
  ],
  "review_date": "2027-04-01"
}
```

* **Runtime State:** `MandateExecutionState.HOLD_PENDING_TRI_VALIDATION` with `is_execution_authorized = False`.
* **Non-Actionable Order Guarantee:** `DeterministicSIPPlan` and `DeterministicLumpsumPlan` are marked with `is_actionable_order = False` and `execution_status = "ON_HOLD_PENDING_TRI_VALIDATION"`.
* **Runtime Assertion:** Invoking `assert_mandate_execution_authorized(facts)` raises `MandateHoldViolationError`, preventing any inadvertent trade execution.

---

## 📊 Cash-Flow-Matched Benchmark TRI Engine

The platform eliminates static benchmark assumptions via `calculate_cashflow_matched_benchmark_xirr()`, matching **363 external cash flows** from `transactions.json` (SWITCH/STP netted to zero at portfolio level, DIVIDEND_REINVEST excluded) against official NSE Indices Total Return Index levels:

| Benchmark Series | ISIN | Accumulated Units | Terminal Valuation (₹) | Benchmark Matched XIRR | True Portfolio XIRR | True Alpha |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **NIFTY 500 TRI** | `INF769K01EZ2` | 135.3810 | ₹51,58,015.68 | **19.35%** | **19.35%** | **+0.11%** (+11 bps) |
| **NIFTY 50 TRI** | `INF769K01EY5` | 118.3785 | ₹48,77,194.38 | **13.34%** | **19.35%** | **+2.48%** (+248 bps) |

*Audit artifact:* `data/lalit_portfolio/benchmark_xirr.json` is currently empty in the repository; no detailed benchmark audit record is available here. Alpha remains blocked until daily, source-authenticated TRI observations and the independent NSE trading calendar are supplied.

---

## 🚀 Quickstart & Verification

### 1. Run Complete Invariant Test Suite (15/15 PASS)
```bash
python -m pytest test_p0_fiduciary_invariants.py -v
```

### 2. Run Universal Fiduciary Logic Validation Suite (84/84 PASS - 100% Success)
```bash
python validate_final_logics.py
```

### 3. Generate All 3 Deliverables (.md + .pdf)
```bash
python advisor_lean.py
```
Generated in `outputs/`:
* `Portfolio_Health_Audit.md` & `.pdf` (Fee bleed, overlap, 5-theme diagnostics)
* `Switch_and_Consolidation_Plan.md` & `.pdf` (3-phase tax-shielded switch schedule)
* `Fresh_Money_Deployment_Plan.md` & `.pdf` (Deterministic 4-slot SIP & 20/80 lumpsum blueprint)
* `MFCentral_Action_Checklist.csv` (Tactical switch and folio consolidation checklist)

### 4. Personal Redemption Engine (CLI)
```bash
# Calculate gross redemption of ₹3,00,000
python advisor_lean.py --redeem 300000

# Calculate net payout of ₹5,00,000 (after statutory taxes & exit loads)
python advisor_lean.py --redeem 500000 --net
```

### 5. Launch Web Dashboard (Streamlit)
```bash
python -m streamlit run app.py --server.port 8501
```
