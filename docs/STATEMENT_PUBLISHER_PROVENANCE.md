# Statement structure and publisher provenance contract

**Status:** CAS and CGS validators separate structural validity from document-claimed publisher text. The canonical SIP CAS upload is structurally validated and supports independent Ed25519 reviewer approval bound to exact uploaded bytes. Publisher authentication is available only when a separately administered `STATEMENT_PUBLISHER_TRUST_REGISTRY_JSON` trust root is configured and a valid signed review envelope is submitted. Without both, the source remains `UNVERIFIED`.

## Three independent facts

The statement pre-flight validator exposes three distinct concepts:

1. **Structural validity** — `is_valid` and `structural_validity` mean only that the uploaded bytes can be parsed and satisfy the CAS/CGS structural checks. They do not prove the document is genuine, complete, current, issued by a registrar, or suitable as authenticated evidence.
2. **Document-claimed publisher** — `detected_content_publisher` is derived from untrusted workbook/PDF content. A single marker produces a claimed label with `UNAUTHENTICATED_DOCUMENT_CONTENT`; multiple registrar markers produce `Ambiguous` / `AMBIGUOUS_DOCUMENT_CONTENT`; no marker produces `Unknown` / `UNVERIFIED`. File names, sheet names and generic mutual-fund terms do not authenticate a publisher.
3. **Authenticated publisher** — `authenticated_publisher`, `rta_source`, and `is_publisher_authenticated` are populated only after the configured trusted verifier independently validates publisher evidence bound to the uploaded-byte SHA-256 digest. Until then, `rta_source` remains `Unknown`.

## Byte and source provenance

Every validation result records:
- SHA-256 of the exact uploaded bytes (`provenance_digest`)
- Original file name and byte length
- Structural/document type classification
- Untrusted content-claimed publisher, separately from authenticated identity

A digest establishes byte identity/integrity after receipt; it does **not** establish who created, issued, hosted or delivered the file.

## Authentication integration boundary

`authenticate_statement_provenance(result, evidence, trusted_verifier=...)` is the only supported promotion boundary. The canonical SIP route calls `validate_cas_excel` on the exact upload bytes before passing them to the evidence provider. It accepts an optional `statement_publisher_approval_json` detached Ed25519 envelope with scope `STATEMENT_PUBLISHER_AUTHENTICATION`. The signed envelope binds the exact source SHA-256 and the document type, publisher, verification method, UTC review time, durable evidence reference and optional HTTPS source URL. Evidence must bind:
- `source_digest`: exact SHA-256 of uploaded bytes
- `publisher`: one of CAMS, KFintech or MFCentral
- `verification_method`: `TRUSTED_SIGNATURE`, `AUTHENTICATED_DOWNLOAD` or `INDEPENDENT_REVIEW`
- `verified_at` and `evidence_reference`: auditable verification time and durable receipt/review/signature reference

The injected verifier is a trusted application integration, not user input. It must independently establish the claimed publisher and verify that its trusted signature, authenticated retrieval receipt/session, or controlled reviewer attestation binds the publisher to the exact `source_digest`. It must return literal `True`; exceptions, missing verifier, incomplete evidence or a false result fail closed. A plain URL, timestamp, digest, free-text reviewer statement, workbook marker or caller-supplied boolean is not verification.

The verifier must validate source URL/host and retrieval-session evidence where applicable, preserve the original receipt/signature bytes or durable reference, and verify the signature/attestation against configured trust material or an authenticated reviewer identity. Do not implement a verifier that merely echoes fields supplied by the upload client.

`require_authenticated_statement` requires consistent authenticated status, publisher identity, and retained provenance evidence. It rejects structural-only and internally inconsistent/forged result states.

## Runtime configuration and fail-closed behavior

Configure `STATEMENT_PUBLISHER_TRUST_REGISTRY_JSON` with an independently administered schema-v1 Ed25519 reviewer registry. The production default requires authenticated CAS; test/development environments default to allowing structurally valid CAS as unverified input unless explicitly overridden. The reviewer key must have `reviewer_role: independent`, be valid and unrevoked, and must not be supplied by the evidence bundle or upload client. A reviewer signs a detached approval envelope using scope `STATEMENT_PUBLISHER_AUTHENTICATION`. The API verifies the signature, reviewer trust key, expiry, source digest and structured review claims before setting `AUTHENTICATED_SOURCE`.

Production defaults to requiring authenticated CAS input (`MF_SIP_REQUIRE_AUTHENTICATED_CAS=true`). Without a signed approval, the canonical SIP route returns HOLD and leaves the full budget unallocated. A structurally valid user-provided CAS may be processed only as `UNVERIFIED` when an operator explicitly disables this requirement (`MF_SIP_REQUIRE_AUTHENTICATED_CAS=false`), for example in controlled test/development environments; it never upgrades `rta_source`, `authenticated_publisher` or `is_publisher_authenticated`. This status is included in the SIP response and decision-trace digest. If a signed approval is submitted but the trust root is missing, invalid, expired, revoked or mismatched, the route returns HOLD and leaves the full budget unallocated. A workflow whose policy requires authenticated registrar evidence must call `require_authenticated_statement` before using the statement as authenticated evidence. The same signed-review verifier accepts `CAS_EXCEL`, `CAS_PDF` and `CGS_EXCEL` validation results; any future CGS upload or tax-evidence workflow must use this boundary before labelling CGS source figures as registrar-authenticated. The current canonical SIP endpoint accepts CAS XLSX only.

## Required adversarial coverage

Tests cover unknown publishers, embedded single-publisher claims, mixed/spoofed CAS and CGS labels, structurally valid but unauthenticated statements, weak reviewer-string/URL evidence without a verifier, verifier rejection, digest mismatch, and forged/inconsistent authentication flags.
