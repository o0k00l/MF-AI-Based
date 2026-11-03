# Option B — High‑Level Design (HLD) & Low‑Level Design (LLD)
## Version 3.2 (Implementation-Ready Fiduciary Specification with The 5 Universal Invariants)

> **Companion to OPTION_B_ROADMAP.md and logical_flow.md.**  
> Specifies the 6-Module unified architecture, rigorous look-through mathematical formulas, the 5 Universal Invariants, binary eligibility gates, date-aware statutory tax execution, mandate authority governance, and the mandatory **NO ACTION / HOLD** fiduciary branch.

---

## 1. High‑Level Design (HLD)

### 1.1 Core Fiduciary Principles
1. **Deterministic Calculations First:** Every figure (true XIRR, fee bleed, constituent look-through overlap, capital gains tax, exit load, SAA drift, SIP allocation, lumpsum staging) is calculated by pure Python before any AI is called. Zero LLM math.
2. **Immutable Local Financial Data:** Ground truth is strictly rooted in verified statement data (`cas_detailed_report_2026_10_09_174452.xlsx`), canonical policies, and audited historical transactions.
3. **Pydantic V2 Validated Contracts:** Structured payloads pass through strict type and range validations via `core/models.py`.
4. **LLM Restricted to Narrative Interpretation:** The AI receives verified facts, applicable policies, and deterministic decisions; it translates them into plain English without altering figures.
5. **The Mandatory "NO ACTION" Rule:** If no candidate scheme offers a demonstrable, statistically validated improvement over existing holdings or if concentration ceilings are reached, the engine's explicit verdict is **NO ACTION / HOLD**.
6. **The 5 Universal Invariants:** Replaces procedural tier sprawl with 5 mathematical equations (Universal 20/80 Lumpsum, Universal 4-Slot Sizing, Universal ₹1.25L Tax Shield, Universal Personal Redemption Waterfall, Universal SAA & Stability Offset).
7. **Zero Hardcoding & Zero Fabrication Mandate:** In financial systems, no metrics may be simulated or fabricated, and no fund brand names may be hardcoded. If required data is missing or candidate schemes cannot be dynamically evaluated from verified sources, the engine MUST fail explicitly and safely (raise an exception or return an explicit NO ACTION / HOLD). Safe, transparent failure is strictly superior to fabricated output.
8. **Runtime Mandate Governance:** Recommendations default strictly to `MandateExecutionState.HOLD_PENDING_TRI_VALIDATION` with `is_execution_authorized = False`. Autonomous execution is blocked at runtime by `assert_mandate_execution_authorized()`.

---

### 1.2 The 6‑Module Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        THE 6-MODULE ARCHITECTURE                       │
├──────────────────────────────────┬─────────────────────────────────────┤
│ 1. DATA & RECONCILIATION         │ Ingestion, canonical mapping, date  │
│                                  │ reconciliation, data quality gates. │
├──────────────────────────────────┼─────────────────────────────────────┤
│ 2. PORTFOLIO DIAGNOSTICS         │ Fee bleed, XIRR, benchmark alpha,   │
│                                  │ constituent overlap, 5-theme deficit│
│                                  │ look-through stability cushion.     │
├──────────────────────────────────┼─────────────────────────────────────┤
│ 3. INVESTOR SUITABILITY & SAA    │ All 6 SEBI risk tiers, stability    │
│                                  │ offset threshold, 0% debt SIP rule. │
├──────────────────────────────────┼─────────────────────────────────────┤
│ 4. INVESTMENT SELECTION          │ Mandatory 10 eligibility gates,     │
│                                  │ multi-horizon scoring, SPIVA, NO ACT│
├──────────────────────────────────┼─────────────────────────────────────┤
│ 5. EXECUTION & TAX SAFEGUARDS    │ FIFO lot audit, exit loads, §112A/  │
│                                  │ §198 ₹1.25L tax shield, 20/80 STP,  │
│                                  │ 4-stage personal redemption.        │
├──────────────────────────────────┼─────────────────────────────────────┤
│ 6. DECISION & EXPLAINABILITY     │ Deterministic SIP injection,        │
│    (AI Reporting Layer)          │ verified facts only, zero AI math.  │
└──────────────────────────────────┴─────────────────────────────────────┘
```

---

## 2. Low-Level Design (LLD) Specifications

### 2.1 Module 1: Ingestion & Reconciliation (`core/math_engine.py` & `core/eligibility.py`)
* `parse_cas(xlsx_path: Path) -> Tuple[str, List[Dict[str, Any]]]`:
  Enforces a single valuation date across all folios (throws `ValueError` on mixed statement dates).
* `load_holdings_from_cas_excel(...) -> List[HoldingItem]`:
  Reconciles scheme names with `fund_metrics.json` and `fund_aliases.json`. Maps underlying instrument weights: `equity_pct`, `debt_pct`, `other_pct`.
* `load_candidate_universe(metrics_path: Path) -> List[Dict[str, Any]]`:
  Ingests candidate mutual funds from `fund_metrics.json` ensuring complete schema compliance.

#### Statement Reconciliation Baseline (Lalit Saini):
* **Source Statement:** `cas_detailed_report_2026_10_09_174452.xlsx`
* **Period:** 01-Jan-2023 to 09-Oct-2026
* **Total Invested Cost:** **₹44,29,929.64**
* **Current Portfolio Valuation:** **₹51,70,911.38**
* **Total Unrealized Gain:** **₹7,40,981.74**
* **Active Schemes Count:** **23 schemes** (across 15 unique folios)
* **Total CAS Rows:** 85 entries (62 zero-balance historical entries, 23 active holdings).

---

### 2.2 Module 2: Look-Through Diagnostics & Benchmark Engine (`core/math_engine.py`)

#### 2.2.1 Candidate-Specific Constituent Look-Through Overlap
The engine calculates constituent look-through overlap against the client's actual holdings:
$$\text{Overlap}(C, P) = \sum_{s \in C \cap P} \min\bigl(W_{C, s},\; W_{P, s}\bigr)$$
Where $W_{P, s}$ is the aggregate weight of stock $s$ across the client's current holdings, and $W_{C, s}$ is the weight of stock $s$ in candidate fund $C$.

*Evaluated Overlaps for Lalit's Portfolio:*
* ICICI Pru Healthcare Direct: **0.78%** (Torrent Pharma 0.53%, Fortis Healthcare 0.25%)
* Mirae Asset Healthcare Direct: **0.93%** (Torrent Pharma 0.53%, Aurobindo Pharma 0.40%)
* Tata India Pharma Direct: **0.00%** (zero overlapping holdings)
* Nippon India Pharma Direct: **0.93%** (Torrent Pharma 0.53%, Aurobindo Pharma 0.40%)

#### 2.2.2 Look-Through Stability Buffer
The stability cushion is calculated from underlying cash and debt holdings:
$$\text{Stability Buffer \%} = \frac{\sum_{i=1}^{N} \bigl(V_i \times (\text{DebtPct}_i + \text{CashPct}_i)\bigr)}{\sum_{i=1}^{N} V_i} \times 100$$
In Lalit's portfolio:
$$\text{Embedded Debt: } 4.06\% \quad+\quad \text{Embedded Cash: } 3.48\% \quad=\quad \mathbf{7.54\% \text{ Stability Cushion}}$$

#### 2.2.3 Cash-Flow-Matched Benchmark TRI Performance Engine
Matches all 379 cash flows from `transactions.json` against official NSE Indices Total Return Index levels:
* Inflows purchase hypothetical units: $U_i = \frac{|C_i|}{\text{TRI}(t_i)}$.
* Outflows redeem units: $U_j = \frac{C_j}{\text{TRI}(t_j)}$.
* Terminal valuation: $V_{\text{bench}} = (\sum \Delta U) \times \text{TRI}(t_{\text{terminal}})$.
* Results:
  * **NIFTY 500 TRI:** Matched XIRR = **15.71%**, Portfolio XIRR = **15.82%**, True Alpha = **+0.11%** (+11 bps).
  * **NIFTY 50 TRI:** Matched XIRR = **13.34%**, Portfolio XIRR = **15.82%**, True Alpha = **+6.01%** (+601 bps).

---

### 2.3 Module 3: Universal Fiduciary Suitability & SAA (`core/math_engine.py`)

$$\text{Threshold}(T) = \max\bigl(0.0,\; D_{\text{target}}(T) - \text{Tolerance}(T)\bigr)$$

$$\text{Final Debt SIP \%} = \begin{cases} 
0.0\% & \text{if } S \ge \text{Threshold}(T) \quad (\text{Stability Cushion Organically Satisfied}) \\
D_{\text{base}}(T) & \text{if } S < \text{Threshold}(T) \quad (\text{Deficit Funded via Stability Vehicle})
\end{cases}$$

| SEBI Risk Tier | SAA Debt Target | Tolerance Band | Threshold ($D_{\min}$) | Lalit's $S = 7.54\%$ | Resulting SIP Split | Stability Vehicle Assigned |
|---|---|---|---|---|---|---|
| **Tier 6 (Very High)** | 5.0% | $\pm 5.0\%$ | **0.0%** | $7.54\% \ge 0.0\%$ | **100% Eq / 0% Debt** | None (Satisfied) |
| **Tier 5 (High)** | 10.0% | $\pm 5.0\%$ | **5.0%** | $7.54\% \ge 5.0\%$ | **100% Eq / 0% Debt** | **None (Organically Satisfied!)** |
| **Tier 4 (Mod. High)** | 15.0% | $\pm 5.0\%$ | **10.0%** | $7.54\% < 10.0\%$ | **70% Eq / 30% Debt** | Dynamic Arbitrage Direct (12.5% Tax) |
| **Tier 3 (Moderate)** | 30.0% | $\pm 5.0\%$ | **25.0%** | $7.54\% < 25.0\%$ | **50% Eq / 50% Debt** | Dynamic Short-Term Debt Direct (AAA/Sov) |
| **Tier 2 (Low to Mod.)**| 60.0% | $\pm 4.0\%$ | **56.0%** | $7.54\% < 56.0\%$ | **20% Eq / 80% Debt** | Dynamic Short-Term Debt Direct (AAA/Sov) |
| **Tier 1 (Capital Pres.)**| 80.0% | $\pm 3.0\%$ | **77.0%** | $7.54\% < 77.0\%$ | **0% Eq / 100% Debt** | Dynamic Short-Term Debt Direct (AAA/Sov) |

---

### 2.4 Module 4: Autonomous Selection Engine (`core/math_engine.py` & `core/eligibility.py`)

#### 2.4.1 The 10 Binary Fiduciary Gates (Fail-Closed Specification)
```
Gate 1: Single-AMC net worth exposure <= 30.0% (Mitigates counterparty risk)
Gate 2: Mid-Cap AUM <= ₹40,000 Cr | Flexi-Cap AUM <= ₹1,75,000 Cr (Prevents liquidity & size drag)
Gate 3: Scheme Top-10 <= 55.0% & Sector <= 35.0% | Portfolio Look-Through Sector <= 40.0%
Gate 4: Risk-Adjusted Sharpe & Alpha Gate (STRICTLY FAIL-CLOSED)
        - Rejects None, NaN, inf, booleans, empty strings, malformed strings.
        - Active Hurdle: 3Y Sharpe >= 0.40 AND 3Y Jensen's Alpha > 0.0% vs TRI Benchmark.
        - Verified Passive Exemption: `is_verified_passive_scheme()` verifies genuine Index/ETF structure via explicit `is_passive` metadata flag; falls back to SEBI category/name heuristics with active-keyword disqualification (adversarial hardening needed for production).
Gate 5: Capture Ratio Asymmetry (Downside <= 100.0% OR Upside >= Downside; zero mock defaults)
Gate 6: Mandate Suitability & Riskometer score <= client SEBI risk tier (Starters barred from thematic)
Gate 7: Data Integrity & Factsheet Provenance (Confidence score >= 0.80; zero synthetic mocks)
Gate 8: Operational History >= 3.0 yrs & Lead Manager Tenure >= 2.0 yrs
Gate 9: Thematic satellite cap <= 15.0% of SIP (0% for Starter AUM < ₹5L)
Gate 10: 100% Direct Plan mandate (Zero Regular plans; eliminates 80-120 bps trail fee drag)
```

#### 2.4.2 Standardized 6-Pillar Fiduciary Model ($0 - 100$ Scale)
$$\text{Composite Score} = 0.25 P_1 + 0.20 P_2 + 0.15 P_3 + 0.15 P_4 + 0.15 P_5 + 0.10 P_6$$
* **Pillar 1: Multi-Horizon Returns (25% weight):** $0.40 R_{\text{1Y}} + 0.35 R_{\text{3Y}} + 0.25 R_{\text{6M}}$ (Effective 1Y momentum weight = 10.0%).
* **Pillar 2: Risk-Adjusted Quality (20% weight):** 3Y Sharpe + Capture Ratio Asymmetry.
* **Pillar 3: Cost Efficiency (15% weight):** Direct TER relative to category median.
* **Pillar 4: Constituent Overlap Benefit (15% weight):** $100.0 - \text{Overlap}(C, P)$.
* **Pillar 5: Stability Buffer (15% weight):** Organic cash and debt cushion.
* **Pillar 6: Global Diversification (10% weight):** International equity ballast.

#### 2.4.3 Closed-Form Thematic Taper Exact Algebra ($m = 45.544$ Months)
$$\frac{80,396.14 + 14,250 \cdot m}{5,170,911.38 + 100,000 \cdot m} = 0.075 \implies m = \frac{307,422.2135}{6,750} = \mathbf{45.5440\text{ months}}$$
* Month 39: 7.013% < 7.50% (Safe)
* Month 40: 7.092% < 7.50% (Safe)
* Month 45: 7.462% < 7.50% (Safe)
* Month 46: 7.532% >= 7.50% (**Breaches Ceiling $\rightarrow$ Automatic Taper to 0.0% Triggered**)

#### 2.4.4 Universal 4-Slot Passive Index Fallback Policy
* **Slot 1 (Flexi-Cap):** Active rank #1 $\rightarrow$ Nifty 500 / Flexi Index Direct $\rightarrow$ NO ACTION / HOLD
* **Slot 2 (Mid-Cap):** Active rank #1 $\rightarrow$ Nifty Midcap 150 Index Direct $\rightarrow$ NO ACTION / HOLD
* **Slot 3 (Large-Cap):** Direct folio reuse $\rightarrow$ Active rank #1 $\rightarrow$ Nifty 50 Index Direct $\rightarrow$ NO ACTION / HOLD
* **Slot 4 (Thematic Satellite):** Active rank #1 under 7.5% ceiling $\rightarrow$ strictly collapses to 0.0% (**NO ACTION / HOLD**).

---

### 2.5 Module 5: Execution, Date-Aware Tax & Mandate Governance

#### 2.5.1 Date-Aware Statutory Tax Mapping
* **Income-tax Act, 1961 — Section 50AA Original (FY 2024–25 / AY 2025–26):**
  * Specified mutual fund = equity $\le 35\%$; deemed STCG at slab rates for units acquired $\ge$ 1 April 2023.
* **Income-tax Act, 1961 — Section 50AA Amended (FY 2025–26 / AY 2026–27, per Finance (No. 2) Act 2024):**
  * Specified mutual fund = debt/money market $> 65\%$ OR fund-of-funds investing $\ge 65\%$ in such funds.
  * Calculation method: annual average of daily closing figures.
* **Income-tax Act, 2025 — Section 76 (FY 2026–27+ / AY 2027–28+):**
  * Special computation for specified mutual funds ($> 65\%$ debt/money market) and MLDs acquired $\ge$ 1 April 2023.
* **Income-tax Act, 1961 — Equity LTCG/STCG (Pre-1 April 2026):**
  * Section 112A: 12.5% LTCG above ₹1.25L exemption on equity funds ($>= 65.0\%$ equity).
  * Section 111A: 20.0% STCG on equity units held $\le 365$ days.
* **Income-tax Act, 2025 — Equity LTCG/STCG (Post-1 April 2026):**
  * Section 198: Special provision for LTCG on qualifying equity mutual funds ($>= 65.0\%$ equity). **Statutory minimum threshold — distinct from Section 50AA/76 definitions.**
  * Section 196: Short-term capital gains on qualifying equity assets (20%).
* **Common (Both Acts):**
  * Section 48: Grandfathered debt mutual funds acquired $<$ 1 April 2023 retain indexation.
  * Section 70 / 108: Current-year intra-head loss set-off.
  * Section 74 / 111: Loss carry-forward (8 years).
  * Section 45 read with Section 2(47): Switches are taxable transfers.

### Statutory Transition Table (Section 50AA / Section 76)

| Transaction Period | Financial Year | Assessment Year | Governing Provision | Specified-Fund Definition |
|--------------------|----------------|-----------------|---------------------|---------------------------|
| Before 1 Apr 2025 | FY 2024–25 | AY 2025–26 | Section 50AA (original) | Equity $\le 35\%$ |
| 1 Apr 2025 – 31 Mar 2026 | FY 2025–26 | AY 2026–27 | Section 50AA (amended) | Debt $> 65\%$ OR FoF $\ge 65\%$ in such funds |
| 1 Apr 2026 onwards | FY 2026–27+ | AY 2027–28+ | Section 76 (2025 Act) | Debt $> 65\%$ + MLDs |

> **✅ RESOLVED Code Defects (P0):**
> 1. **Old regime fallback** — FIXED: Now uses equity ≤ 35% only (lines 2606-2630). Test `test_p0_13` passes.
> 2. **Amended regime (FY 2025–26):** Three-regime classifier implemented (`qualifies_as_specified_mutual_fund_under_section_50AA`); annual-average-of-daily-closing-figures **requires daily NAV data source** (G1/G6).
> 3. **Section 76 dispatcher** — FIXED: Separated as `qualifies_as_specified_mutual_fund_under_section_76` with MLD scope (acquired ≥ 1 Apr 2023). Test `test_p0_13` passes.
> 4. **Architectural Debt** — FIXED: Provision-specific classifiers implemented returning rich `ClassificationResult`:
>    - `qualifies_as_equity_oriented_under_section_198` (threshold ≥ 65%, returns `ClassificationResult`)
>    - `qualifies_as_specified_mutual_fund_under_section_50AA` (FY-aware: FY 2024–25 equity ≤ 35%; FY 2025–26 debt > 65% / FoF ≥ 65%)
>    - `qualifies_as_specified_mutual_fund_under_section_76` (FY 2026–27+: debt > 65% + MLDs)
> 5. **Benchmark XIRR cashflow classification** — FIXED: SWITCH/STP netted to zero at portfolio level (lines 463-519); DIVIDEND classified cash vs reinvested via description heuristic. Test `test_p0_14` passes (cashflows 363, portfolio XIRR 19.35%).
> 6. **`ltcg_rate` NameError** — FIXED: Uses `get_tax_rates_for_sale()` (line 505). Test `test_p0_2` passes.
> 7. **Mandate state propagation** — FIXED: Mandate state now rendered in ALL 3 deliverables with execution status interpretation.

#### 2.5.2 Runtime Mandate Governance
* Persisted in `config.json` as `MandateExecutionState.HOLD_PENDING_TRI_VALIDATION`.
* `is_execution_authorized = False`.
* Plans tagged with `execution_status = "ON_HOLD_PENDING_TRI_VALIDATION"` and `is_actionable_order = False`.
* `assert_mandate_execution_authorized()` strictly blocks live order execution.

---

### 2.6 Module 6: Decision & Explainability (`core/prompt_advisor.py`)
* Pre-calculated `FiduciaryFactsPayload` injected into Jinja templates.
* All 3 fiduciary reports and PDFs generated deterministically in `outputs/`.
* Zero LLM math calculations.
