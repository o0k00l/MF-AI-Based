# Private client portfolio data

This directory is intentionally kept free of client records in Git.

To run client-specific analysis locally, create the following files in this directory
from the client's own verified source records:

- `config.json` — client IPS, risk profile, budget, mandate and preferences.
- `fund_metrics.json` — dated, sourced fund/portfolio metrics used by the analysis.
- `fund_aliases.json` — explicit scheme-name aliases to metric identifiers.
- `transactions.json` — normalized transaction ledger, if the workflow requires it.
- `statements/cas_detailed_report_*.xlsx` — original CAS statement(s).

All files other than this README are ignored by Git. Do not force-add client data.
Use synthetic fixtures in tests; never copy a real client's CAS, folios, tax details,
bank balances, goals, or mandate into the repository.

Before using any generated recommendation, independently verify source dates,
coverage, scheme identity, tax lots, and the current mandate. The engine is
decision-support only and does not authorize execution.
