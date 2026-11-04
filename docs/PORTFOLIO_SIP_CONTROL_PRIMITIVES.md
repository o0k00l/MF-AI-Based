# Portfolio-aware SIP control primitives

This module adds a deterministic, fail-closed foundation for portfolio-level SIP analysis. It is a reusable calculation layer, not a production recommendation release and not yet wired into the public SIP API.

## Implemented in this tranche

| Control | Function | Safety behavior |
|---|---|---|
| Total-portfolio perimeter | `reconcile_total_portfolio` | Requires explicit perimeter-complete attestation, source references, owner scope and a common valuation date; otherwise HOLD/error |
| SAA drift | `calculate_saa_drift` | Requires exact sleeve match and approved target weights summing to 100% |
| Incremental SIP routing | `route_incremental_sip` | Routes only to eligible underweight sleeves; rounding remainder and unfillable budget stay unallocated |
| Eligibility before scoring | `screen_candidates_before_scoring` | Requires exact scheme identity, dated evidence, evidence reference and PASS for every mandatory gate |
| Look-through aggregation | `calculate_lookthrough_exposure` | Portfolio-weights issuer exposures and returns HOLD below caller-supplied approved coverage |
| Decision trace | `build_decision_trace` | Hashes a versioned source/policy/engine/decision record deterministically |
| Goal suitability inputs | `validate_goal_mandate` | Requires approved goal, target date, target amount, liabilities, source and approved horizon policy |
| Liquidity reserve | `assess_liquidity_and_sip_surplus` | Separates verified cash reserve/obligations from recurring monthly income surplus; missing/stale evidence holds |
| Affordability stress | `stress_test_sip_affordability` | Runs only caller-supplied income/expense shock scenarios; no assumed income growth |
| Scheme operations | `validate_scheme_operational_feasibility` | Requires current scheme status, exact identity, minimum SIP and evidence for exit load, lock-in and subscription status

## Important boundaries

- This code does not authenticate an evidence publisher or independently attest that a declared portfolio perimeter is complete.
- The caller must supply the approved SAA, tolerance, evidence-freshness limit, look-through threshold and candidate eligibility gates. No new investment-policy threshold is invented here.
- A portfolio perimeter marked complete is an explicit upstream attestation, not a conclusion inferred from CAS data.
- Candidate screening returns eligible identifiers only; it does not rank funds or create a positive recommendation.
- Look-through outputs are exposure calculations only. Candidate incremental exposure and concentration policy still require a separate approved policy integration.
- Automated scheduling/notification and CAS ingestion remain future work; the current lifecycle helper only evaluates supplied dates/events and state transitions.
- The module is not wired into `api/sip.py` in this tranche. The existing API must continue to return HOLD / NO_ACTION until source-provider, TRI/calendar, research and independent release gates are satisfied.
- No orders, switches, redemptions or broker actions are generated.

## Validation

Run:

```bash
python -m pytest tests/test_portfolio_sip_controls.py -q
```

The tests use synthetic fixtures only and do not validate any real investor portfolio or live fund data.
