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
  "candidate_universe_source_file": "originals/candidate_universe.csv"
}
```

All paths are relative to the bundle root. The optional `aliases_file` may be
null. Every other referenced file must exist. Paths that escape the bundle,
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
- `metrics_file`: existing fund metrics data file consumed by the engine.
  Metrics must not be inferred from scheme-master identity.
- `aliases_file`: optional reviewed exact-alias mapping; fuzzy matching is
  not supported.

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
7. Treat `/ready` as provider-configuration readiness only. The API continues
   to return HOLD / NO_ACTION while authenticated daily TRI, independent NSE
   calendar and research-release approval remain outstanding.

A configured bundle is not a production recommendation approval, and no
recommendation or transaction order is enabled by this provider.
