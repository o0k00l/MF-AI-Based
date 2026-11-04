# SIP Evidence Bundle Contract

**Status: implementation contract; not production approval.**

The SIP API can be configured with `MF_SIP_EVIDENCE_BUNDLE_DIR`. The directory
must be outside the Git checkout and readable by the application process. The
provider is filesystem-backed and read-only: it performs no network scraping,
does not synthesize data, and does not persist uploaded CAS files.

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
  "portfolio_context_file": "records/total_portfolio_context.json",
  "portfolio_context_metadata_file": "records/total_portfolio_context_metadata.json",
  "portfolio_context_source_file": "originals/total_portfolio_context.xlsx"
}
```

All paths are relative to the bundle root. The optional `aliases_file` may be
null. The three `portfolio_context_*` fields are optional, but if one is present all three are required. Every referenced file must exist. Paths that escape the bundle,
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
  `universe_complete: true` and a precise `coverage_scope`.
- `metrics_file`: normalized fund metrics data file consumed by the engine.
  Metrics must not be inferred from scheme-master identity.
- `metrics_metadata_file` and `metrics_source_file`: source metadata and
  unchanged original publisher bytes for the metrics dataset. Metadata must
  also include `normalized_metrics_sha256`, the digest of the normalized
  `metrics_file`. The provider checks both the original-source digest and the
  normalized-file digest. It also verifies HTTPS URL, reviewer attestation
  and freshness before the evidence contract accepts the bundle.
- `aliases_file`: optional reviewed exact-alias mapping; fuzzy matching is
  not supported.
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

The provider checks bundle path safety and structure. The API then runs the
existing evidence contract, including source-byte hash, date/freshness,
scheme identity, candidate completeness attestation and Direct-plan evidence
checks. These checks do not independently authenticate the publisher or the
reviewer.

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
