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
   - Aggregate issuer, sector, market-cap and theme exposures using dated issuer classifications and source-referenced limits.
   - Missing or stale issuer classification blocks the candidate; unknown look-through cannot improve a score or be treated as zero risk.
   - A rank score is accepted only with original reviewer-attested score bytes, a matching SHA-256 reference, effective date and methodology version. Normalized candidate JSON must also match its reviewed content digest.
   - Use only thresholds approved in the policy/IPS; this document does not
     invent concentration limits.

9. **Incremental monthly routing**
   - Derive contribution amounts from approved SAA gaps, horizon, budget,
     eligible candidates and constraints.
   - Keep every target sleeve independent. If no candidate qualifies for a
     positive-target sleeve, its amount remains unallocated.
   - Apply candidate-level allocation only after eligibility, operational and concentration checks; enforce approved per-fund minimums, contribution increments and core-fund limits.
   - Do not move an unfilled sleeve budget into another sleeve. Reconcile `sum(simulated candidate SIPs) + unallocated = requested budget` within the approved rounding tolerance.

10. **Decision trace and client explanation**
    - Retain source digests, source/as-of dates, policy and engine versions,
      candidate gate results, exposure deltas, arithmetic and explicit HOLD
      reasons.
    - Hash original metrics, scheme-master, disclosure, candidate-universe, ranking-score, portfolio-context and policy bytes, with as-of dates and candidate-level score provenance.
    - Include the sleeve and candidate allocation simulations in the canonical trace while keeping authorized allocation at zero until release approval.
    - Distinguish verified facts, policy choices, assumptions and unavailable evidence.
    - Provide a deterministic replay path without exposing client identifiers or uploaded statements in logs or shared artifacts.

11. **Lifecycle and review history**
    - Persist an immutable DRAFT snapshot keyed by decision-trace digest only when an external `MF_SIP_LIFECYCLE_DIR` is configured.
    - Persist no CAS contents, investor identifiers, folios or portfolio rows in the lifecycle record.
    - REVIEWED, SUPERSEDED and WITHDRAWN transitions still require an authenticated independent reviewer and append-only event history; no unauthenticated API transition is enabled.

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
| #30 | Goal suitability | Approved dated goal/mandate validation |
| #31 | Liquidity and reserve | Verified cash, obligations and reserve constraints |
| #32 | SIP affordability | Income/expense/debt stress test |
| #33 | Recommendation lifecycle | Immutable DRAFT trace record and controlled review history |
| #34 | Scheme operations | Current lifecycle, minimum SIP and transaction constraints |

## Release boundary

The above pipeline defines the work required to make recommendations
portfolio-aware. It does not approve any fund, target allocation, concentration
threshold, performance claim or deployment. Those require current source
evidence, approved client mandate, independent review and the existing TRI,
calendar and research release controls.


## 12. Portfolio-aware ranking and category benchmark anchor gates (#40 / #41)

- Standalone fund scoring and portfolio-aware SIP scoring are separate modes.
- A portfolio-aware score requires verified candidate-to-existing-portfolio overlap evidence, a stable candidate identity, an overlap source digest, an evidence date within the approved freshness window and at least 99.5% look-through coverage.
- Missing overlap is unavailable evidence, never a neutral 50-point observation. A verified 0% overlap remains a valid measured result and is distinguishable from missing evidence.
- Portfolio-aware scoring requires an independently reviewed category anchor record for the exact candidate category. It must supply all seven bounds: alpha, 1Y return, Sharpe, TER, defensive buffer, international exposure and portfolio overlap.
- Every bound must be finite and increasing. The anchor record must identify the exact benchmark, original source bytes/digest, effective date, reviewer and policy version.
- The provider contract requires the rank-score source to declare portfolio-aware scope and an explicit missing-overlap block policy. It also requires verified overlap status/coverage and matching category anchor source, policy version and benchmark identity.
- No category borrows another category's anchors or generic defaults. Categories with no complete, approved anchor set remain unavailable for scoring and SIP ranking.
- Current in-code numeric anchors are not automatically treated as independent approvals. Flexi Cap, Mid Cap and Large Cap currently lack their own 1Y-return anchor in the legacy map; they fail closed in standalone scoring until complete category-specific anchors are approved. Other unsupported categories remain unavailable.
- These controls validate the evidence and policy envelope; they do not independently validate that the scoring methodology predicts future returns or is investment-optimal. That remains a separate model/policy review.

