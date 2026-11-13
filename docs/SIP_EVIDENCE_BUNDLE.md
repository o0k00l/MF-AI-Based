# SIP Evidence Bundle Contract

**Status: implementation contract; not production approval.**

The SIP API can be configured with `MF_SIP_EVIDENCE_BUNDLE_DIR`. The directory
must be outside the Git checkout and readable by the application process. The
provider is filesystem-backed and read-only: it performs no network scraping,
does not synthesize data, and does not persist uploaded CAS files.

A second, independent runtime trust root is mandatory:
`SIP_REVIEWER_TRUST_REGISTRY_JSON`. It must contain the independently
administered reviewer public-key registry. It must be mounted/configured
separately from the evidence bundle; the bundle publisher must not be able to
supply or replace its own trust registry. If the trust registry is absent or
invalid, `/ready` reports `not_ready` and recommendation requests remain
`HOLD / NO_ACTION` with the entire budget unallocated.

## Required layout

A version-1 bundle uses a UTF-8 `manifest.json`:

```json
{
  "schema_version": 1,
  "disclosure_as_of_date": "YYYY-MM-DD",
  "metrics_file": "metrics/fund_metrics.json",
  "metrics_metadata_file": "records/fund_metrics_metadata.json",
  "metrics_source_file": "originals/fund_metrics_source.xlsx",
  "aliases_file": "metrics/reviewed_aliases.json",
  "aliases_metadata_file": "records/reviewed_aliases_metadata.json",
  "aliases_source_file": "originals/reviewed_aliases_source.csv",
  "scheme_master_file": "records/scheme_master.json",
  "scheme_master_source_file": "originals/scheme_master.xlsx",
  "portfolio_disclosures": {
    "EXACT_SCHEME_ID": {
      "record_file": "records/disclosures/EXACT_SCHEME_ID.json",
      "source_file": "originals/disclosures/EXACT_SCHEME_ID.xlsx"
    }
  },
  "candidate_universe_file": "records/candidate_universe.json",
  "candidate_universe_metadata_file": "records/candidate_universe_metadata.json",
  "candidate_universe_source_file": "originals/candidate_universe.csv",
  "candidate_score_metadata_file": "records/candidate_score_metadata.json",
  "candidate_score_source_file": "originals/candidate_rank_scores.csv",
  "category_anchor_metadata_file": "records/category_anchor_metadata.json",
  "category_anchor_source_file": "originals/category_benchmark_anchor_source.pdf",
  "portfolio_context_file": "records/total_portfolio_context.json",
  "portfolio_context_metadata_file": "records/total_portfolio_context_metadata.json",
  "portfolio_context_source_file": "originals/total_portfolio_context.xlsx"
}
```

All paths are relative to the bundle root. The optional alias artifact is
configured as an atomic trio: `aliases_file`, `aliases_metadata_file` and
`aliases_source_file`; if no alias artifact is supplied, all three are null
or absent. The three `portfolio_context_*` fields are optional, but if one is present all three are required. The two `candidate_score_*` fields are optional, but must be configured together when supplied. The two `category_anchor_*` fields are optional, but any candidate carrying a ranking score requires the approved category-anchor pair. Every referenced file must exist. Paths that escape the bundle,
absolute paths, symlink escapes and bundles located inside the Git checkout
are rejected.

## Record contents

- `scheme_master_file`: JSON object containing `status: VERIFIED`, the exact
  scheme records, and source metadata (`source_url`, SHA-256,
  `reviewer_attested`, `effective_date`, `source_type`).
- `scheme_master_source_file`: original bytes used to calculate the declared
  digest. Do not re-serialize the JSON metadata and call it original source.
- `portfolio_disclosures`: keyed only by stable exact `scheme_id`; each
  record must declare the same ID and source metadata. The original source
  bytes are supplied separately.
- `candidate_universe_file`: non-empty JSON array. Every candidate must carry
  exact `fund_id`, scheme ID, ISIN, AMC, category, explicit Direct-plan
  status and reviewer-attested Direct-plan evidence. Its `source_file` is
  relative to the bundle root; the provider supplies the trusted root path.
- `candidate_universe_metadata_file`: source metadata plus
  `universe_complete: true`, a precise `coverage_scope`, and
  `normalized_candidate_universe_sha256` matching the exact normalized JSON
  file bytes. This prevents an independently edited candidate JSON file from
  inheriting a valid original-source attestation.
- `candidate_score_metadata_file` and `candidate_score_source_file`: optional
  original ranking-score output and its reviewed source metadata. Any candidate
  carrying a score must have:
  `rank_score_source_ref`, `rank_score_as_of_date`,
  `rank_score_methodology_version`, and `rank_score_scope=PORTFOLIO_AWARE`;
  verified portfolio-overlap status, percentage and look-through
  coverage meeting the effective, approved policy threshold; an overlap source reference; and the matching category-anchor
  source reference, policy version and benchmark identity. The score metadata
  must declare `score_scope=PORTFOLIO_AWARE` and
  `missing_overlap_policy=BLOCK_SCORE`. Missing overlap cannot be represented
  as a neutral score or enter portfolio-aware ranking. Score values are
  consumed as evidence; the SIP service does not manufacture a ranking model
  or claim that the model is independently validated.
- `category_anchor_metadata_file` and `category_anchor_source_file`: required
  whenever any candidate carries a rank score. The source metadata must be
  reviewer-attested and include a policy version, reviewer ID and a category
  map. Each approved category entry must identify its exact benchmark, status,
  reviewer, policy version, effective date and complete metric bounds for
  alpha, 1Y return, Sharpe, TER, buffer, international exposure and overlap.
  Every bound must be a finite, increasing pair. The category anchor source
  digest must match the original source bytes. Candidate scores must reference
  the exact category, benchmark, anchor source digest and policy version.
  Categories without an approved complete anchor set are unavailable; no
  other category's anchors or generic defaults may be substituted.
- `metrics_file`: normalized fund metrics data file consumed by the engine. Its
  exact normalized bytes must match `normalized_metrics_sha256` in the metadata.

  Metrics must not be inferred from scheme-master identity.
- `metrics_metadata_file` and `metrics_source_file`: source metadata and
  unchanged original publisher bytes for the metrics dataset. Metadata must
  include `normalized_metrics_sha256`, `publisher`, `coverage_scope`,
  `record_count`, `effective_date`, `source_type`, `reviewer_id` and
  `policy_version`. The detached reviewer approval binds the original source
  digest and the complete normalized `funds` array, not merely the file hash.
  Every consumed metrics record must carry the exact `scheme_id`, `ISIN`,
  `AMC`, `category`, `plan_type`, `option_type`, benchmark identity,
  per-record effective date and a source reference equal to the original
  publisher SHA-256. Those identity dimensions must match the verified scheme
  master. Missing, stale, mixed-snapshot, unmatched or conflicting records
  block the current-holdings assessment.
- Numeric exposure fields must be finite and within 0–100. Equity plus debt
  cannot exceed 100%. Each record must declare `market_cap_basis`:
  `TOTAL_PORTFOLIO_PCT` requires large/mid/small-cap buckets to reconcile
  within equity exposure; `EQUITY_PCT` treats those buckets as weights within
  the equity sleeve and their sum cannot exceed 100%. An absent/unknown basis
  or unreconciled split blocks analysis. TER is accepted only when its plan
  matches the exact verified scheme plan.
- `aliases_file`, `aliases_metadata_file` and `aliases_source_file`: an
  optional atomic, independently reviewed alias evidence bundle. Metadata
  must include normalized digest, publisher, coverage scope/count, effective
  date, reviewer ID and policy version. Its detached signature binds the
  original bytes and complete normalized alias mapping. Aliases can resolve
  names only; they cannot carry category, plan/option, TER, exposure or other
  financial facts. Ambiguous mappings are rejected. The strict SIP holdings
  path does not use aliases to match metrics; it matches only exact verified
  scheme ID and ISIN.
- `portfolio_context_file`: optional provider-supplied total-portfolio context
  JSON. It must include the dated, owner-scoped perimeter, reconciled CAS row,
  approved IPS, goals, cash/reserve/obligation evidence, candidate policy,
  operational evidence, concentration policy and freshness inputs required by
  the portfolio service. Client-entered `portfolio_context_json` is diagnostic
  only and cannot replace this provider bundle.
- `portfolio_context_metadata_file` and `portfolio_context_source_file`:
  source metadata and unchanged original publisher/export bytes. The metadata
  must include HTTPS `source_url`, matching SHA-256, `reviewer_attested: true`,
  `effective_date` and `source_type`. All three context fields are loaded
  together and validated before the service can treat the context as
  provider-attested.

The provider checks bundle path safety and structure. The API then requires
detached Ed25519 reviewer approvals against the separately configured trust
registry. Approvals bind original source digests and the normalized structured
records (including scheme identity, constituent weights/coverage, candidate
universe, ranking inputs and approved category anchors). Reviewer identity,
independence, key validity/revocation, scope, repository, issuance and expiry
are verified. A plain `reviewer_attested: true` flag is not accepted as proof
of independent review. The trust registry and signed envelopes are required
for production evidence validation; this still does not establish that the
publisher is authoritative or that a candidate universe is truly complete.

The structured-record digest for each signed scope is canonicalized as follows:
- `SIP_SCHEME_MASTER`: the complete normalized `schemes` list.
- `SIP_PORTFOLIO_DISCLOSURE`: `{"constituent_weights": <uppercase identifiers and numeric weights>, "coverage_pct": <numeric coverage>}`; the exact scheme ID is also bound in the approval payload.
- `SIP_CANDIDATE_UNIVERSE`: the complete normalized candidate list.
- `SIP_EVIDENCE_RELEASE` for fund metrics: the complete normalized `funds` array.
- `SIP_EVIDENCE_RELEASE` for aliases: the complete normalized alias mapping.
- `SIP_EVIDENCE_RELEASE` for total-portfolio context: the complete normalized `portfolio_context` mapping.
- `SIP_EVIDENCE_RELEASE` for ranking scores: the ordered list of each scored candidate's fund ID, score, score date, methodology, portfolio-overlap status/coverage/source, category-anchor source/policy and benchmark identity.
- `SIP_EVIDENCE_RELEASE` for category anchors: the complete `category_anchors` mapping.

The reviewer must sign these exact normalized structures; signing only the original
source file while leaving normalized records unbound is insufficient.

## Operational controls

1. Obtain source documents from approved publishers and retain the original
   downloaded bytes unchanged.
2. Have a reviewer independently verify publisher authenticity, scope,
   retrieval date, statement period and the normalized record.
3. Calculate SHA-256 from the original bytes; do not copy a digest from a
   metadata file without recomputing it.
4. Keep investor CAS, folio data and client-specific transaction records out
   of this bundle unless a separate approved client-data workflow explicitly
   requires them. The bundle is shared research evidence, not a client store.
5. Mount the bundle read-only and restrict access to the deployment identity.
6. Rotate and update the bundle through a reviewed operational process. Do not
   modify evidence files during a request.
7. The optional total-portfolio context bundle is required for portfolio-aware
   positive routing. Do not populate it with synthetic or investor-entered
   declarations; missing or stale external assets, IPS, goal, liquidity,
   candidate-score or operational evidence must leave the budget unallocated.
8. Deploy the explicit ASGI entry point `api.sip_production:app` only after the
   external bundle is mounted. The `api.sip:app` entry point remains a
   development-safe HOLD default. Neither entry point enables recommendations
   until the separate research release gate is approved.
9. Treat `/ready` as provider-configuration readiness only. The API continues
   to return HOLD / NO_ACTION while authenticated daily TRI, independent NSE
   calendar and research-release approval remain outstanding.

A configured bundle is not a production recommendation approval, and no
recommendation or transaction order is enabled by this provider.


## Cross-document policy and configurability rules (binding)

This document is subordinate to `docs/SIP_ENGINE_DECISION_REGISTER.md` for settled product decisions and `docs/NORMATIVE_ARCHITECTURE_SPECIFICATION.md` for normative behaviour. Read it with `IMPLEMENTATION_STATUS.md` for implementation/acceptance status. Historical audit snapshots and remediation plans are evidence/history, not a source of current policy.

**No arbitrary hardcoding:** no allocation percentage, fund-count limit, per-fund cap, candidate-count minimum, risk mapping, score weight, score threshold, concentration limit, look-through coverage threshold, freshness/staleness duration, SIP minimum/increment, reserve period, AUM floor/ceiling, manager-tenure requirement, benchmark mapping, refresh cadence or other investment/operational threshold may be introduced as a universal code or document default merely because it is conventional or appeared in an earlier proposal. Such values must come from an approved, versioned, effective-dated policy/IPS or authoritative source, with provenance, scope, owner/reviewer and validation. If a required value is absent, invalid, stale, conflicting or out of scope, the affected decision must HOLD / NO_ACTION and preserve affected budget as unallocated. Do not silently substitute zero, a generic default, a fallback category, another category's threshold or a prior policy version.

**Source-derived facts are not policy defaults:** scheme identity, category, plan/option, benchmark, NAV, AUM, TER, holdings, issuer/sector classification, scheme lifecycle, SIP operational terms, trading sessions and disclosure dates must be acquired from authoritative, dated sources and validated for the exact scheme/security and effective period. Do not infer them from names, synthetic fixtures, LLM output or unrelated records. A source's publication cadence is observed and monitored; it is not a hard-coded assertion that evidence is fresh.

**Calculation determinism:** formulas, units, denominator, date alignment, rounding mode/scale, missing-data semantics and tie-breaking must be explicit and versioned. Financial amounts and units use Decimal arithmetic end-to-end; round only at the specified policy boundary. Every requested rupee must reconcile to allocated plus unallocated rupees exactly after the approved rounding operation.

**Configuration contract:** every configurable policy value must be present in the validated policy object used for the decision, and the decision trace must bind its policy ID/version/digest/effective date and resolved values. No hidden environment fallback or duplicated local mapping is permitted. Environment variables may identify locations, credentials or deployment wiring; they must not silently become an unreviewed investment policy.

**Examples are non-operative:** numbers, scheme names, benchmark names, dates, file names and sample JSON are illustrative unless explicitly identified as a currently approved policy/source contract. Example values must never be promoted to runtime defaults. Any fixed numeric threshold or benchmark list in a legacy section is historical/example material pending explicit approval and migration into the effective policy/source registry; it is not authority to hardcode that value.

**Conflict resolution:** apply the decision register, then the normative architecture, then the approved effective policy/IPS for investor-specific values, then authoritative source evidence for market facts. Policy cannot override source facts and source facts cannot invent policy. Record unresolved conflicts and HOLD; do not pick whichever value makes the workflow pass.
