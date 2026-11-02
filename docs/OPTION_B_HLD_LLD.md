# Option B — High‑Level Design (HLD) & Low‑Level Design (LLD)
## Version 2.5 (Production-Verified Fiduciary Specification with The 5 Universal Invariants)

> **Companion to OPTION_B_ROADMAP.md and logical_flow.md.**  
> Specifies the 6-Module unified architecture, rigorous look-through mathematical formulas, the 5 Universal Invariants, binary eligibility gates, tax execution realities, and the mandatory **NO ACTION** fiduciary branch.

---

## 1. High‑Level Design (HLD)

### 1.1 Core Fiduciary Principles
1. **Deterministic Calculations First:** Every number (XIRR, fee bleed, look-through concentration, capital gains tax, exit load, SAA drift, SIP allocation, lumpsum staging) is calculated by pure Python before any AI is called. Zero LLM math.
2. **Immutable Local Financial Data:** Ground truth is strictly rooted in verified statement data (`cas_detailed_report_*.xlsx`), canonical policies, and audited historical transactions.
3. **Pydantic V2 Validated Contracts:** Structured payloads pass through strict type and range validations.
4. **LLM Restricted to Narrative Interpretation:** The AI receives verified facts, applicable policies, and deterministic decisions; it translates them into plain English without altering figures.
5. **The Mandatory "NO ACTION" Rule:** If no candidate scheme offers a demonstrable, statistically validated improvement over existing holdings, the engine's explicit verdict is **NO ACTION / HOLD**.
6. **The 5 Universal Invariants:** Replaces procedural tier sprawl with 5 mathematical equations (Universal 20/80 Lumpsum, Universal 4-Slot Sizing, Universal ₹1.25L Tax Shield, Universal Personal Redemption Waterfall, Universal SAA & Stability Offset).

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
│                                  │ weighted overlap, 5-theme exposure, │
│                                  │ look-through stability cushion.     │
├──────────────────────────────────┼─────────────────────────────────────┤
│ 3. INVESTOR SUITABILITY & SAA    │ All 6 SEBI risk tiers, stability    │
│                                  │ offset threshold, 0% debt SIP rule. │
├──────────────────────────────────┼─────────────────────────────────────┤
│ 4. INVESTMENT SELECTION          │ Mandatory 10 eligibility gates,     │
│                                  │ multi-horizon scoring, SPIVA, NO ACT│
├──────────────────────────────────┼─────────────────────────────────────┤
│ 5. EXECUTION & TAX SAFEGUARDS    │ FIFO lot audit, exit loads, §112A   │
│                                  │ ₹1.25L tax shield, 20/80 arbitrage  │
│                                  │ STP, 4-stage personal redemption.   │
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

---

### 2.2 Module 2: Look-Through Diagnostics (`core/math_engine.py`)

#### 2.2.1 Weighted Look-Through Overlap
Unlike naive Jaccard similarity, the engine calculates the weighted overlap between funds $A$ and $B$:
$$\text{Overlap}(A, B) = \sum_{s \in S} \min\bigl(W_{A, s},\; W_{B, s}\bigr)$$
Where $W_{A, s}$ is the percentage weight of security $s$ inside portfolio $A$.

#### 2.2.2 Look-Through Stability Buffer
Rather than trusting category labels, the stability cushion is calculated from underlying cash and debt holdings:
$$\text{Stability Buffer \%} = \frac{\sum_{i=1}^{N} \bigl(V_i \times (\text{DebtPct}_i + \text{CashPct}_i)\bigr)}{\sum_{i=1}^{N} V_i} \times 100$$
In Lalit's portfolio:
$$\text{Embedded Debt: } 4.06\% \quad+\quad \text{Embedded Cash: } 3.48\% \quad=\quad \mathbf{7.54\% \text{ Stability Cushion}}$$

#### 2.2.3 5-Theme Real-Time Look-Through Diagnostics
Computes macro sector exposures across:
1. **Defence & Aerospace:** Evaluates dedicated defence funds + look-through holdings (5.98%).
2. **Power & Infrastructure:** Evaluates generation, transmission, capital goods (5.11%).
3. **PSU & CPSE:** Evaluates state-owned enterprise look-throughs (6.19%).
4. **Commodities & Metals:** Evaluates cyclical metals and energy (2.40%).
5. **Healthcare & Pharma:** Flags neglected secular themes (**1.55% vs 5.5% benchmark deficit**).

#### 2.2.4 Regular Commission Fee Bleed & Compounded Loss
Calculates annual distributor commission leakage:
$$\text{Annual Bleed} = \sum_{i \in \text{Regular}} V_i \times (\text{TER}_{\text{Regular}, i} - \text{TER}_{\text{Direct}, i})$$
For Lalit's 14 Regular schemes: **₹40,970.52/year**.  
10-Year Compounded Loss at 12% CAGR:
$$\text{FV} = \sum_{t=1}^{10} \text{Annual Bleed} \times (1 + 0.12)^{10 - t} = \mathbf{₹8,05,258.41}$$

---

### 2.3 Module 3: Universal Fiduciary Suitability & SAA (`core/math_engine.py`)

Governs asset allocation across all 6 SEBI Regulatory Risk Tiers based on `data/policy/asset_allocation.json`:

$$\text{Threshold}(T) = \max\bigl(0.0,\; D_{\text{target}}(T) - \text{Tolerance}(T)\bigr)$$

$$\text{Final Debt SIP \%} = \begin{cases} 
0.0\% & \text{if } S \ge \text{Threshold}(T) \quad (\text{Stability Cushion Organically Satisfied}) \\
D_{\text{base}}(T) & \text{if } S < \text{Threshold}(T) \quad (\text{Deficit Funded via Stability Vehicle})
\end{cases}$$

| SEBI Risk Tier | SAA Debt Target | Tolerance Band | Threshold ($D_{\min}$) | Lalit's $S = 7.54\%$ | Resulting SIP Split | Stability Vehicle Assigned |
|---|---|---|---|---|---|---|
| **Tier 6 (Very High)** | 5.0% | $\pm 5.0\%$ | **0.0%** | $7.54\% \ge 0.0\%$ | **100% Eq / 0% Debt** | None (Satisfied) |
| **Tier 5 (High)** | 10.0% | $\pm 5.0\%$ | **5.0%** | $7.54\% \ge 5.0\%$ | **100% Eq / 0% Debt** | **None (Organically Satisfied!)** |
| **Tier 4 (Mod. High)** | 15.0% | $\pm 5.0\%$ | **10.0%** | $7.54\% < 10.0\%$ | **70% Eq / 30% Debt** | `Kotak Equity Arbitrage Direct` (12.5% Tax) |
| **Tier 3 (Moderate)** | 30.0% | $\pm 5.0\%$ | **25.0%** | $7.54\% < 25.0\%$ | **50% Eq / 50% Debt** | `ICICI Pru Short Term Debt Direct` (AAA/Sov) |
| **Tier 2 (Low to Mod.)**| 60.0% | $\pm 4.0\%$ | **56.0%** | $7.54\% < 56.0\%$ | **20% Eq / 80% Debt** | `ICICI Pru Short Term Debt Direct` (AAA/Sov) |
| **Tier 1 (Capital Pres.)**| 80.0% | $\pm 3.0\%$ | **77.0%** | $7.54\% < 77.0\%$ | **0% Eq / 100% Debt** | `ICICI Pru Short Term Debt Direct` (AAA/Sov) |

---

### 2.4 Module 4: Autonomous Selection Engine (`core/math_engine.py` & `core/eligibility.py`)

#### 2.4.1 The 10 Binary Fiduciary Gates
```
Gate 1: Single-AMC net worth exposure <= 30.0%
Gate 2: Mid-Cap AUM <= ₹40,000 Cr | Flexi-Cap AUM <= ₹1,75,000 Cr (with >=65% Large-Cap/Cash, else ₹90k Cr)
Gate 3: Top-10 stock concentration <= 55.0% (Debt & dedicated thematic funds exempted)
Gate 4: 3-Year Sharpe Ratio >= 0.40 (Index & Debt funds adjusted)
Gate 5: Downside Capture Ratio <= 100.0%
Gate 6: Upside Capture Ratio >= 90.0%
Gate 7: Riskometer score <= client SEBI risk tier
Gate 8: Manager tenure >= 3 years & complete track record
Gate 9: Thematic satellite cap <= 15% (0% for < ₹5L AUM)
Gate 10: 100% Direct Plan mandate (Zero Regular plans)
```

#### 2.4.2 Multi-Horizon Quantitative Composite Scoring Formula
$$\begin{aligned}
\text{Score} =\;& (R_{1\text{Y}} \times 5.0) + (R_{6\text{M}} \times 3.0) + (\text{Alpha}_{3\text{Y}} \times 8.0) \\
&+\; (\text{Sharpe}_{3\text{Y}} \times 15.0) + (\text{Sharpe}_{1\text{Y}} \times 10.0) \\
&+\; (\text{Intl\%} \times 2.5) + (\text{CashBuf\%} \times 1.0) \\
&-\; (\text{TER}_{\text{Direct}} \times 25.0) - \text{Concentration Penalty}
\end{aligned}$$

#### 2.4.3 Peer Evaluation (Healthcare / Pharma Slot 4 Ranking)
- **ICICI Prudential Healthcare Direct:** Score: **360.1** | 1Y: **49.4%** | 3Y: **24.1%** | Sharpe: **1.02** | TER: **0.89%** $\implies$ **SELECTED #1**
- **Mirae Asset Healthcare Direct:** Score: **308.2** | 1Y: **40.2%** | 3Y: **22.5%** | Sharpe: **0.94** | TER: **0.62%** $\implies$ Runner-Up
- **Tata India Pharma Direct:** Score: **287.8** | 1Y: **41.5%** | 3Y: **19.8%** | Sharpe: **0.85** | TER: **0.76%** $\implies$ Rejected
- **Nippon India Pharma Direct:** Score: **231.6** | 1Y: **35.2%** | 3Y: **18.7%** | Sharpe: **0.78** | TER: **0.99%** $\implies$ **REJECTED (Rank #4)**

#### 2.4.4 Automated SPIVA Passive Fallback
Triggered when active funds fail gates:
- Large-Cap Anchor: Nifty 50 Index Fund Direct (0.18% TER)
- Mid-Cap Alpha: Nifty Midcap 150 Index Fund Direct (0.25% TER)

---

### 2.5 Module 5: Execution, Tax Safeguards & Redemptions

#### 2.5.1 The Universal 20/80 Lumpsum Deployment
$$\text{Day 1 Immediate Core Equity Anchor} = 0.20 \times L$$
$$\text{Tax-Shielded Arbitrage Parking Pool} = 0.80 \times L$$
$$\text{Monthly Systematic Transfer (STP)} = \frac{0.80 \times L}{M}$$
- Bypasses Section 50AA slab rate debt taxation (up to 39.0%) by parking in **Equity Arbitrage Funds** (12.5% LTCG).
- Multi-slot SAA preservation for $L \ge \text{₹5 Lakhs}$: 50% Flexi, 35% Mid-Cap, 15% Large-Cap.

#### 2.5.2 The Universal 4-Slot Sizing Engine (40/30/15/15)
- Slot 1: Core Flexi-Cap Compounder (40%)
- Slot 2: Mid-Cap Alpha Engine (30%)
- Slot 3: Large-Cap Bluechip Anchor (15%)
- Slot 4: Tactical Thematic Satellite (15%) [0% for Starter AUM < ₹5L]

#### 2.5.3 Universal Personal Redemption Engine (4-Stage Waterfall)
- **Stage 1 (Cash Surplus):** Bank cash exceeding emergency buffer (₹0 tax, ₹0 load).
- **Stage 2 (Tactical Regular Bleed):** Sweeps underperforming Regular plans. First harvests Section 70 capital losses; then sweeps mature LTCG within the ₹1.25L exemption (₹0 exit load).
- **Stage 3 (Thematic Trim):** Over-allocated, bubble-valuation thematic holdings.
- **Stage 4 (Core Equity Siphon):** Core long-term Direct equity holdings held >365 days.
- **Gross & Net Cash Modes:** In Net Cash mode, gross redemption is calculated to cover statutory capital gains taxes.

---

### 2.6 Module 6: Decision & Explainability (`core/prompt_advisor.py`)
- Injects verified facts payload (`FiduciaryFactsPayload`) into Jinja templates.
- Markdown and PDF outputs generated deterministically. Zero LLM math hallucinations.
