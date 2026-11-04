# Portfolio-Aware SIP Recommendation Gates

**Status: engineering contract and work plan. No recommendation release is approved.**

The recommendation flow must answer a portfolio question: how should a new
monthly contribution change the investor's verified total portfolio? It must
not rank standalone schemes first and then force-fit a SIP split.

## End-to-end sequence

1. **Client perimeter and mandate**
   - Confirm the investor, household/account perimeter, investment horizon,
     liquidity constraints, risk profile and current approved IPS/SAA.
   - Identify which asset classes/accounts are included and which are excluded.
   - An absent value is unknown, not zero. An incomplete perimeter cannot be
     represented as a complete total portfolio.

2. **CAS and transaction ingestion**
   - Parse supported CAS workbook headers by name, not fixed column position.
   - Validate scheme, folio, units, invested value and current value.
   - Reconcile active units to transaction history where available; surface
     duplicate, unmatched, reversed and pending items.
   - Preserve the temporary-upload boundary; never log or persist raw CAS.

3. **Stable scheme identity**
   - Resolve scheme name + AMC to a stable scheme ID and ISIN using the
     verified scheme master and original source bytes.
   - Keep scheme identity independent from category/performance metrics.
   - Missing identity remains MISSING; no fuzzy/name-only identity fallback.

4. **Fund metrics and portfolio look-through**
   - Independently validate category, plan, expense, asset exposure and risk
     metrics. Identity evidence is not a substitute for metrics evidence.
   - Attach constituent disclosures by exact scheme ID and validate source
     bytes, effective date, freshness, weights and coverage.
   - Missing or partial coverage is unknown exposure, never zero overlap.

5. **Total-portfolio reconciliation**
   - Establish the included assets and liabilities, valuation dates and source
     evidence for CAS holdings, cash and any other in-scope investments.
   - Reconcile the denominator and show excluded assets explicitly.
   - Do not infer emergency reserve or deployable bank cash from a CAS file.

6. **SAA gap calculation**
   - Compare current verified look-through allocation against the client's
     approved IPS/SAA and tolerance bands.
   - Keep target SAA, current allocation, stability buffer and incremental SIP
     routing as distinct values.
   - Risk-profile defaults are policy inputs, not proof of an individually
     reviewed mandate.

7. **Candidate eligibility**
   - Establish a dated, scoped, complete universe with exact scheme identity.
   - Evaluate every mandatory policy gate before ranking.
   - Missing, stale, conflicting or unsupported evidence makes the candidate
     ineligible or evidence-insufficient; it must not be scored as a pass.
   - The market/category universe and required evidence fields must be
     independently approved; completeness attestation alone is not proof.

8. **Portfolio-aware candidate evaluation**
   - Assess each candidate's incremental effect on asset allocation, issuer,
     sector, market-cap, thematic and underlying-fund concentration.
   - Evaluate overlap against existing holdings and the other proposed funds.
   - Unknown look-through cannot improve a score or be treated as zero risk.
   - Use only thresholds approved in the policy/IPS; this document does not
     invent concentration limits.

9. **Incremental monthly routing**
   - Derive contribution amounts from approved SAA gaps, horizon, budget,
     eligible candidates and constraints.
   - Keep every target sleeve independent. If no candidate qualifies for a
     positive-target sleeve, its amount remains unallocated.
   - Reconcile `sum(recommended SIP items) + unallocated = requested budget`
     within the approved rounding tolerance.

10. **Decision trace and client explanation**
    - Retain source digests, source/as-of dates, policy and engine versions,
      candidate gate results, exposure deltas, arithmetic and explicit HOLD
      reasons.
    - Distinguish verified facts, policy choices, assumptions and unavailable
      evidence.
    - Provide a deterministic replay path without exposing client identifiers
      or uploaded statements in logs or shared artifacts.

## Mandatory fail-closed conditions

- Unresolved exact scheme identity.
- Missing/stale/conflicting fund metrics or constituent disclosure.
- Incomplete constituent weight coverage or unexplained portfolio mismatch.
- Unreconciled total-portfolio perimeter or stale/mismatched valuation dates.
- Missing approved IPS/SAA or unsupported risk/asset-class mapping.
- Candidate universe or mandatory eligibility evidence not verified.
- Unknown or excessive portfolio concentration/overlap.
- Missing TRI/calendar/research-release approval.
- Any arithmetic mismatch between requested, allocated and unallocated budget.

In each case, return HOLD / NO_ACTION and preserve the entire affected budget as
unallocated. The API's current benchmark/research release gate remains separate
and continues to suppress positive allocations even when upstream evidence
passes.

## Implementation ownership map

| GitHub issue | Workstream | Expected artifact |
|---|---|---|
| #14 | CAS/metrics integration regression | Full-suite CI green without weaker identity rules |
| #15 | Evidence-provider wiring | Explicit read-only evidence bundle and validation |
| #16 | Scheme master, candidate universe and look-through | Reconciled source-backed evidence bundle |
| #23 | Total portfolio and cash perimeter | Reconciliation record with inclusions/exclusions |
| #24 | SAA drift and SIP routing | IPS-linked gap and monthly budget calculation |
| #25 | Candidate eligibility | Gate-by-gate candidate decision record |
| #26 | Concentration and overlap | Portfolio-level incremental risk analysis |
| #27 | Decision traceability and suitability | Replayable source-to-decision explanation |

## Release boundary

The above pipeline defines the work required to make recommendations
portfolio-aware. It does not approve any fund, target allocation, concentration
threshold, performance claim or deployment. Those require current source
evidence, approved client mandate, independent review and the existing TRI,
calendar and research release controls.
