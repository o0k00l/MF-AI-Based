# Architecture Decision Record: Option A (Phased) + Option B (Lean)

**Status:** Accepted  
**Date:** 2026-11-01  
**Decision:** Maintain **both** Option A and Option B with a clear migration path from B → A

---

## Overview

| Aspect | Option B (Lean / Current — **New Implementation**) | Option A (Phased / Target) |
|--------|---------------------------------------------------|----------------------------|
| **Paradigm** | Deterministic math → strict LLM interpreter | Automated ingestion → tax-lot engine → interactive wizard |
| **Entry Point** | `advisor.py` (new) | `ingestion/`, `tax/`, `ui/pages/` wizard |
| **Data Source** | Pre-verified JSON + CAS Excel (manual) | Auto-parsed CAS/CGS PDFs & Excels |
| **Tax Engine** | Heuristic in `math_engine.py` (70/30 split) | FIFO lot builder + 112A optimizer (`tax/`) |
| **Allocation** | ❌ Not implemented (SAA Drift Minimizer pending) | Bounded solver (`core/allocator.py`) |
| **Screening** | Binary gates in `eligibility.py` | Morningstar 5-Pillar (`core/five_pillars.py`, `core/screens.py`) |
| **UI** | CLI only (`--no-ai` / full) | Multi-step wizard (`ui/pages/`) |
| **Reports** | ❌ Single `Fiduciary_Action_Report.md` (3 reports pending) | Full pipeline |
| **LLM Role** | Strict interpreter (no math) | Same principle |

---

## Coexistence Strategy

### 1. Shared Core (Single Source of Truth) — **Actual State**

```text
core/
├── math_engine.py      ← Deterministic math (USED BY NEW Option B)
├── models.py           ← Pydantic schemas (USED BY NEW Option B)
├── eligibility.py      ← Binary gates (NEW Option B only)
├── prompt_advisor.py   ← LLM interpreter (NEW Option B only)
├── ai_engine.py        ← 3-tier LLM cascade (SHARED, untested)
├── candidate_scoring.py← 5-pillar scoring (Option A / legacy Option B)
├── screens.py          ← Overlap matrix (Option A)
├── five_pillars.py     ← Qualitative scoring (Option A)
├── allocator.py        ← Bounded solver (Option A)
└── pdf_exporter.py     ← Report export (both)
```

**Key divergence**: New Option B uses `math_engine.py`, `models.py`, `eligibility.py`, `prompt_advisor.py` — **not** `allocator.py`, `screens.py`, `five_pillars.py`.

### 2. Option B (Lean) — **Current Implementation Status**

| Component | File | Status |
|-----------|------|--------|
| Entry Point | `advisor.py` | ✅ `--no-ai` validated |
| Data Contracts | `core/models.py` | ✅ Complete |
| Deterministic Math | `core/math_engine.py` | ⚠️ Partial (overlap, FIFO, SAA stubbed) |
| Eligibility Gates | `core/eligibility.py` | ✅ Complete |
| LLM Interpreter | `core/prompt_advisor.py` | ✅ Complete (prompt only) |
| LLM Engine | `core/ai_engine.py` | ❌ Untested |
| Reports | `outputs/` | ❌ Single report only |
| Tests | `tests/` | ❌ None |

**Outputs**: 1 report (`Fiduciary_Action_Report.md`), not 3.  
**Maintenance**: Active fixes in progress (see `VERIFICATION_REPORT.md`).

### 3. Option A (Phased) — Legacy / Active Development

| Phase | Components | Status |
|-------|------------|--------|
| **1. Ingestion** | `ingestion/cas_parser.py`, `cgs_parser.py`, `fundmatch.py`, `schemes.py` | 🟡 Parsing works; needs validation |
| **2. Tax Engine** | `tax/transition_planner.py`, `tax_optimizer.py`, `compliance.py` | 🟡 FIFO lots built; optimizer stubbed |
| **3. Allocation/Screening** | `core/allocator.py`, `core/screens.py`, `core/five_pillars.py` | 🟢 Core logic done; needs integration |
| **4. Wizard UI** | `ui/pages/page_upload.py`, `page_profile.py`, `page_goals.py`, `page_report.py` | 🟡 Pages exist; flow needs wiring |
| **5. API Layer** | `fastapi/`, `sqlalchemy`, `redis`, `kafka` | ⚪ Planned (Milestone 2) |