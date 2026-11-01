# Fiduciary Mutual Funds Copilot (Prompt-First & Lean Engine)

A clean, modular fiduciary portfolio analysis and decision-support tool for Indian mutual funds.

## Directory Structure

```
.
├── core/                         # Core calculation & reasoning engines
│   ├── models.py                 # Clean Pydantic data schemas
│   ├── math_engine.py            # Portfolio mathematics (XIRR, CAGR, Sharpe, Drawdown)
│   ├── screens.py                # Fiduciary screening & overlap matrix
│   ├── five_pillars.py           # Morningstar 5-Pillar evaluation (People, Process, Parent, Performance, Price)
│   ├── allocator.py              # Bounded asset allocation & rebalancing solver
│   └── qualitative.py            # AI client with multi-provider fallback (Gemini, OpenRouter)
│
├── data/
│   ├── lalit_portfolio/          # Client data
│   │   ├── config.json           # Client profile, risk tolerance, goals, and monthly SIP budget
│   │   ├── fund_metrics.json     # Holding metrics (expense ratios, AUM, market-cap splits, top holdings)
│   │   ├── transactions.json     # Real transaction ledger for XIRR & tax calculations
│   │   ├── fund_aliases.json     # Fund name resolution aliases
│   │   └── statements/           # CAS and Capital Gains Statements (.xlsx)
│   └── policy/                   # Core fiduciary rules (zero bloat)
│       ├── asset_allocation.json # SAA targets & tolerance bands by risk profile
│       ├── fund_screening.json   # 5-Pillar thresholds & overlap triggers
│       └── tax_rules.json        # Section 112A (₹1.25L exemption), 111A, and 50AA tax rules
│
├── ingestion/                    # [Option A Pipeline]
│   ├── cas_parser.py             # CAMS / KFintech CAS Excel & PDF parser
│   ├── cgs_parser.py             # Capital Gains Statement parser
│   ├── schemes.py                # AMFI scheme catalogue lookup
│   └── fundmatch.py              # Scheme name token & fuzzy matcher
│
├── tax/                          # [Option A Pipeline]
│   ├── transition_planner.py     # Staged FIFO tax-loss harvesting & redemption sequencing
│   └── tax_optimizer.py          # Section 112A ₹1.25L exemption optimizer
│
└── ui/                           # [Option A Pipeline]
    └── pages/                    # Streamlit wizard pages (Upload, Profile, Goals, Report)
```

## Option B vs. Option A Roadmap

1. **Option B (Immediate):** Prompt-driven advisor taking verified portfolio numbers (`data/lalit_portfolio/`) and generating actionable recommendations (Regular-to-Direct switches, multi-cap overlap consolidation, and idle cash deployment).
2. **Option A (Phased Upgrade):** Automated CAS upload, FIFO tax lot engine, and interactive Streamlit UI.

