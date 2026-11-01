# Option B — High‑Level Design (HLD) & Low‑Level Design (LLD)

> Companion to **OPTION_B_ROADMAP.md**.  Describes architecture, data contracts, formulas, prompt contracts, and CLI interfaces.

---

## 1. High‑Level Design (HLD)

### 1.1 System Context
- **Actors**: End‑investor (Lalit), Advisor script (`advisor.py`), Gemini LLM.
- **Data sources** (local, immutable):
  - `data/lalit_portfolio/config.json` – client profile, SIP budget, cash block.
  - `data/lalit_portfolio/fund_metrics.json` – 22‑fund static metrics (ER, AUM, market‑cap splits, top‑10 holdings).
  - `data/lalit_portfolio/fund_aliases.json` – canonical → CAS name mapping.
  - `data/lalit_portfolio/statements/cas_detailed_report_*.xlsx` – latest CAS “Portfolio Details” sheet.
  - `data/policy/asset_allocation.json` – SAA targets & tolerance bands.
  - `data/policy/tax_rules.json` – Sec 112A, STCG/LTCG, exit‑load.
  - `data/policy/fund_screening.json` – 5‑Pillar thresholds & overlap triggers.

### 1.2 Component Diagram (text)

```
┌─────────────────────┐
│  advisor.py (CLI)   │  ◄── user
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐     ┌─────────────────────────────────────┐
│ core/math_engine.py │────▶│ FiduciaryFactsPayload (Pydantic)    │
│  aggregate_facts()  │     │  • fee_bleed: FeeBleedAnalysis      │
└───────┬─────────────┘     │  • overlap_matrix: List[OverlapPair]│
        │                   │  • saa_drift: SAADrift              │
        ▼                   │  • cash_plan: CashPlan              │
┌─────────────────────┐     │  • client_meta, holdings[]          │
│ core/prompt_advisor │────▶│                                     │
│  – 3 generators     │     └──────────────┬──────────────────────┘
└───────┬─────────────┘                    │
        │                                 ▼
        │                    ┌───────────────────────────────┐
        │                    │  google‑genai (Gemini)        │
        │                    │  • model fallback chain       │
        │                    │  • system prompt (fiduciary)  │
        │                    └──────────────┬────────────────┘
        ▼                                   ▼
┌─────────────────────┐          3 × markdown reports
│ outputs/            │          + optional console chat
│  health_audit.md    │
│  switch_plan.md     │
│  cash_plan.md       │
└─────────────────────┘
```

### 1.3 Trust Zones
| Zone | Components | Threat Model |
|---|---|---|
| **Local Trusted** | `advisor.py`, `core/*`, `data/*`, `policy/*` | Fully trusted – code & data under version control. |
| **External** | Gemini API (HTTPS) | Untrusted – only receives serialized `FiduciaryFactsPayload`; no secrets, no PII beyond portfolio numbers. |

### 1.4 Execution Sequence
1. `advisor.py` parses CLI flags.
2. Loads all local JSON + CAS xlsx → builds in‑memory dicts.
3. Calls `math_engine.aggregate_fiduciary_facts()` → returns **validated** `FiduciaryFactsPayload`.
4. If `--no-ai`: pretty‑prints payload & exits.
5. Otherwise, calls each generator in `prompt_advisor` → each builds a prompt, calls `_call_gemini_with_retry`.
6. Writes returned markdown to `outputs/*.md`; prints summary.
7. `--chat` / `--query` re‑use the same payload + conversation history.

---
## 2. Low‑Level Design (LLD)

### 2.1 Pydantic V2 Data Contracts (`core/models.py`)

```python
class FeeBleedAnalysis(BaseModel):
    regular_funds_count: int
    regular_portfolio_value_inr: float
    annual_bleed_inr: float               # sum(value * (TER_regular - TER_direct))
    ten_year_compounded_loss_inr: float   # annual_bleed * ((1+0.12)^10 - 1)/0.12
    details: List[RegularFundDetail]

class RegularFundDetail(BaseModel):
    scheme: str
    value_inr: float
    ter_regular_pct: float
    ter_direct_pct: float
    annual_commission_inr: float

class OverlapPair(BaseModel):
    fund_a: str
    fund_b: str
    overlap_pct: float          # min‑weight Jaccard on top‑10
    shared_stocks: List[str]

class SAADrift(BaseModel):
    current_equity_pct: float
    current_debt_pct: float
    current_cash_pct: float
    target_equity_pct: float
    target_debt_pct: float
    rebalance_required: bool
    breach_buckets: List[str]

class CashPlan(BaseModel):
    total_bank_cash_inr: float
    emergency_buffer_inr: float
    deployable_surplus_inr: float
    stp_monthly_amount_inr: float
    stp_duration_months: int

class FiduciaryFactsPayload(BaseModel):
    client_name: str
    as_of: str
    total_portfolio_value_inr: float
    total_invested_value_inr: float
    total_unrealized_gain_inr: float
    holdings_count: int
    fee_bleed: FeeBleedAnalysis
    overlap_matrix: List[OverlapPair]
    saa_drift: SAADrift
    cash_plan: CashPlan
    monthly_sip_budget_inr: float
    # … extra meta fields
```

All numbers are **Decimal‑safe** (float is fine for reporting; internal math uses `Decimal` where needed).

### 2.2 Core Formulas (pure Python, unit‑tested)

| Metric | Formula |
|---|---|
| **Regular bleed (annual)** | Σ valueᵢ × (TER_regᵢ − TER_dirᵢ) / 100 |
| **10‑yr compounded loss** | annual_bleed × ((1 + r)¹⁰ − 1) / r  with r = 12 % |
| **Top‑10 min‑weight overlap** | 100 × |A ∩ B| / min(|A|,|B|) where A,B are top‑10 stock sets |
| **SAA drift** | current_pct − target_pct per bucket; breach if |drift| > tolerance_band |
| **Emergency buffer** | min(cash_total, 4 × monthly_expenses) – here configured explicitly |
| **Deployable surplus** | cash_total − emergency_buffer |
| **STP monthly** | deployable_surplus / stp_duration_months (default 6) |
| **SIP allocation** | Solve linear programme: minimise ‖target − (current + SIP)‖₂ s.t. ΣSIP = budget, SIP ≥ 0 |

All helpers live in `core/math_engine.py` and are **pure functions** → deterministic, testable.

### 2.3 Prompt Engineering Contracts (`core/prompt_advisor.py`)

- **System prompt** – immutable fiduciary rules (see file). Version‑controlled.
- **Three user prompts** – each a Jinja‑style f‑string that injects the *exact* payload fields.
- **Output contract** – markdown with:
  - No code fences.
  - Compact tables (`| Col | Col |` no extra spaces).
  - Section headers `## 1. …`.
- **Model fallback chain** – `gemini-2.5-flash → gemini-3.5-flash → gemini-3.5-flash-lite`.
- **Retry policy** – exponential backoff (2 s, 4 s, 6 s) *only* for non‑quota errors; quota (429) → immediate next model.

### 2.4 CLI Interface (`advisor.py`)

```bash
python advisor.py               # full run → three .md files
python advisor.py --no-ai       # deterministic facts only
python advisor.py --query "..." # one‑off grounded answer
python advisor.py --chat        # interactive REPL
```

Exit codes: 0 success, 1 config error, 2 data parse error, 3 Gemini error.

### 2.5 Error Handling & Logging
- `logging` at INFO for steps, DEBUG for payload dump.
- All external calls wrapped; on failure → clear message + exit code.
- No silent retries on quota; fallback is explicit.

### 2.6 Testing Strategy
| Layer | Tool | Coverage Target |
|---|---|---|
| Unit (math) | `pytest` + `hypothesis` | 100 % of formulas |
| Unit (prompt build) | `pytest` | snapshot test of prompt strings |
| Integration | `pytest` (monkeypatch Gemini) | end‑to‑end `--no-ai` + one mocked call |
| CLI | `pytest` (tmp_path) | `--help`, `--no-ai`, report file existence |

---

## 3. Configuration & Extensibility

- **Policy files** (`data/policy/*.json`) are the single source of truth for SAA, tax, screening.
- Adding a new client = drop a folder under `data/<client>/` with same JSON set; `advisor.py` takes `--client <name>` (future).
- Model list in `prompt_advisor.MODEL_FALLBACKS` – update without code change.

---

## 4. Security & Compliance Checklist
- [ ] No API keys in repo (`.env` git‑ignored).
- [ ] PII limited to client name & PAN in CAS; not sent to LLM.
- [ ] All numbers sourced from deterministic engine – LLM never computes.
- [ ] Reports contain regulatory citations (Sec 112A, FIFO, exit‑load).

---

*End of HLD/LLD*