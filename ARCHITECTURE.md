# Architecture Decision Record: Option A (Phased) + Option B (Lean)

**Status:** Accepted  
**Date:** 2026-11-01  
**Decision:** Maintain **both** Option A and Option B with a clear migration path from B → A

---

## Overview

| Aspect | Option B (Lean / Current) | Option A (Phased / Target) |
|--------|---------------------------|----------------------------|
| **Paradigm** | Prompt-driven, verified data in `data/` | Automated ingestion → tax-lot engine → interactive wizard |
| **Entry Point** | `advisor_lean.py`, `app.py` | `ingestion/`, `tax/`, `ui/pages/` wizard |
| **Data Source** | Pre-verified JSON + CAS Excel (manual) | Auto-parsed CAS/CGS PDFs & Excels |
| **Tax Engine** | Inline heuristic (Phase 1/2/3 in prompts) | FIFO lot builder + 112A optimizer (`tax/`) |
| **Allocation** | Deterministic tables in `advisor_lean.py` | Bounded solver (`core/allocator.py`) |
| **Screening** | Jaccard overlap in `advisor_lean.py` | Morningstar 5-Pillar (`core/five_pillars.py`, `core/screens.py`) |
| **UI** | 4-tab Streamlit (`app.py`) | Multi-step wizard (`ui/pages/`) |
| **Deployment** | Single file / local | Full pipeline + API (`fastapi/`) |

---

## Coexistence Strategy

### 1. Shared Core (Single Source of Truth)
```
core/
├── math_engine.py      ← XIRR, overlap, SAA, cash waterfall (USED BY BOTH)
├── models.py           ← Pydantic schemas (USED BY BOTH)
├── allocator.py        ← Bounded allocation solver (A uses, B replicates inline)
├── screens.py          ← Overlap matrix, 5-pillar (A uses, B replicates inline)
├── five_pillars.py     ← Qualitative fund scoring (A only currently)
├── ai_engine.py        ← 3-tier LLM cascade (USED BY BOTH)
└── pdf_exporter.py     ← Report export (USED BY BOTH)
```

### 2. Option B (Lean) — Stable, Shipping Now
- **Files:** `advisor_lean.py`, `app.py`
- **Data:** `data/lalit_portfolio/*.json` (verified, committed)
- **Outputs:** 3 markdown/PDF reports + chat
- **Maintenance:** Bug fixes only; no new features

### 3. Option A (Phased) — Active Development
| Phase | Components | Status |
|-------|------------|--------|
| **1. Ingestion** | `ingestion/cas_parser.py`, `cgs_parser.py`, `fundmatch.py`, `schemes.py` | 🟡 Parsing works; needs validation |
| **2. Tax Engine** | `tax/transition_planner.py`, `tax_optimizer.py`, `compliance.py` | 🟡 FIFO lots built; optimizer stubbed |
| **3. Allocation/Screening** | `core/allocator.py`, `core/screens.py`, `core/five_pillars.py` | 🟢 Core logic done; needs integration |
---

## Migration Path: B → A

### Step 1: Data Ingestion Parity (Current Gap)
```
Option B: Manual CAS.xlsx → openpyxl → holdings list
Option A: CAS.pdf/Excel → cas_parser.py → transactions.json → FIFO lots
```
**Action:** Make `ingestion/cas_parser.py` produce the **exact same `holdings` list** that `advisor_lean.py` expects. Then `advisor_lean.py` can switch to `ingestion` output.

### Step 2: Tax Logic Unification
```
Option B: Heuristic Phase 1/2/3 in prompt templates
Option A: FIFO lots → transition_planner.py → tax_optimizer.py
```
**Action:** Replace `advisor_lean.py` switch prompt with call to `tax.transition_planner.generate_switch_plan(fifo_lots, saa_target)`.

### Step 3: Allocation/Screening Unification
```
Option B: Inline allocator + Jaccard overlap
Option A: core/allocator.py + core/screens.py + core/five_pillars.py
```
**Action:** Refactor `advisor_lean.py` to import and use `core.allocator.solve_allocation()` and `core.screens.compute_overlap_matrix()`.

### Step 4: UI Convergence
```
Option B: 4 tabs in app.py
Option A: Multi-step wizard in ui/pages/
```
**Action:** When wizard is complete, deprecate `app.py` tabs in favor of wizard flow. Keep chat as standalone component.

---

## Directory Structure (Target)

```
.
├── advisor_lean.py          ← Option B entry (stable)
├── app.py                   ← Option B UI (stable)
├── ARCHITECTURE.md          ← This file
├── core/                    ← SHARED ENGINE (both options)
│   ├── math_engine.py
│   ├── models.py
│   ├── allocator.py
│   ├── screens.py
│   ├── five_pillars.py
│   ├── ai_engine.py
│   └── pdf_exporter.py
├── ingestion/               ← Option A Phase 1
│   ├── cas_parser.py
│   ├── cgs_parser.py
│   ├── fundmatch.py
│   └── schemes.py
├── tax/                     ← Option A Phase 2
│   ├── transition_planner.py
│   ├── tax_optimizer.py
│   └── compliance.py
├── ui/
│   ├── pages/               ← Option A Phase 4 wizard
│   │   ├── page_upload.py
│   │   ├── page_profile.py
│   │   ├── page_goals.py
│   │   └── page_report.py
│   └── components/          ← Shared UI components (chat, charts)
├── data/
│   ├── lalit_portfolio/     ← Option B verified data (committed)
│   │   ├── config.json
│   │   ├── fund_metrics.json
│   │   ├── fund_aliases.json
│   │   ├── transactions.json
│   │   └── statements/      ← .xlsx (gitignored)
│   └── policy/              ← Fiduciary rules (committed)
├── tests/                   ← NEW: pytest suite for core/
├── .github/workflows/       ← NEW: CI/CD
├── .env.example
├── requirements.txt
└── README.md
```

---

## Development Rules

1. **Never duplicate logic** — if Option A builds a component, Option B should import it (not copy-paste)
2. **`core/` is the contract** — both options depend on `core/`; changes to `core/` require validation for both
3. **Option B tests Option A** — `advisor_lean.py --no-ai` output is the regression baseline for Option A components
4. **Feature flag via import** — e.g., `from core.allocator import solve_allocation` with fallback to inline if not ready

---

## Next Steps (Priority Order)

1. [ ] **Add pytest suite** for `core/math_engine.py` (XIRR, overlap, SAA, cash) — validates both options
2. [ ] **Make `ingestion/cas_parser.py` output match `advisor_lean.py` holdings schema** — enables swap
3. [ ] **Wire `core/allocator.py` into `advisor_lean.py`** — replaces inline allocation
4. [ ] **Wire `core/screens.py` into `advisor_lean.py`** — replaces inline Jaccard
5. [ ] **Replace switch prompt with `tax.transition_planner` call** — unifies tax logic
6. [ ] **Complete wizard flow in `ui/pages/`** — parity with `app.py` tabs
7. [ ] **Deprecate `advisor.py` (8k lines)** — superseded by lean + phased
8. [ ] **Add GitHub Actions CI** running tests on both entry points

---

## References
- `README.md` — Project overview
- `docs/OPTION_B_HLD_LLD.md` — Option B High/Low Level Design
- `docs/OPTION_B_ROADMAP.md` — Option B roadmap
- `core/math_engine.py` — Deterministic math engine (single source of truth for calculations)
| **4. Wizard UI** | `ui/pages/page_upload.py`, `page_profile.py`, `page_goals.py`, `page_report.py` | 🟡 Pages exist; flow needs wiring |
| **5. API Layer** | `fastapi/`, `sqlalchemy`, `redis`, `kafka` | ⚪ Planned (Milestone 2) |