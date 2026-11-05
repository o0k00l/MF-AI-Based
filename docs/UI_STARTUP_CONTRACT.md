# Canonical Application Startup Contract & UI Boundary

This specification defines the authoritative application startup contract and entry-point responsibilities for the repository.

## 1. Scope & Role of Entry Points

The repository maintains two entry points with distinct, non-overlapping roles:

1. **Root Launcher (`app.py`)**:
   - Canonical CLI invocation point for local development environments.
   - Executes: `python app.py` (which internally delegates to `streamlit run ui/app.py`).
   - Does NOT implement financial calculations, client ingestion, or planning logic.

2. **Streamlit Application (`ui/app.py`)**:
   - The UI entry point executed by Streamlit.
   - Enforces the legacy-dashboard retirement safety boundary.
   - Renders a read-only retirement notice explaining that legacy unvalidated planning flows are retired.
   - Guarantees that no portfolio data is ingested, no orders are generated, and no recommendations are emitted.

## 2. Invariants & Safety Constraints

- **No Duplicated Financial Logic**: All financial math, eligibility screening, allocation, and SAA calculations reside strictly in the core engine modules (`core/math_engine.py`, `core/eligibility.py`, `core/portfolio_sip_controls.py`) and services (`services/sip_recommendation.py`). The UI never implements or duplicates calculation routines.
- **Fail-Closed Boundary**: The former interactive dashboard depended on retired in-repository client file structures and unverified planning flows. It remains retired until an independently reviewed, external-only, read-only UI is implemented.
- **Production API Boundary**: For production decision support, the canonical entry point is `api/sip.py` via FastAPI (`uvicorn api.sip:app`), consuming validated evidence bundles without UI interactivity.

## 3. Contributor & Operator Verification

Tests verifying this contract are maintained in `tests/test_ui_retirement.py`.
