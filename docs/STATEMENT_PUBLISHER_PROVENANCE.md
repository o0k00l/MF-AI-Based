# Statement structure and publisher provenance contract

**Status:** fail-closed contract implemented; no trusted CAMS/KFintech/MFCentral publisher verifier is currently configured in the application.

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

`authenticate_statement_provenance(result, evidence, trusted_verifier=...)` is the only supported promotion boundary. Evidence must bind:
- `source_digest`: exact SHA-256 of uploaded bytes
- `publisher`: one of CAMS, KFintech or MFCentral
- `verification_method`: `TRUSTED_SIGNATURE`, `AUTHENTICATED_DOWNLOAD` or `INDEPENDENT_REVIEW`
- `verified_at` and `evidence_reference`: auditable verification time and durable receipt/review/signature reference

The injected verifier is a trusted application integration, not user input. It must independently establish the claimed publisher and verify that its trusted signature, authenticated retrieval receipt/session, or controlled reviewer attestation binds the publisher to the exact `source_digest`. It must return literal `True`; exceptions, missing verifier, incomplete evidence or a false result fail closed. A plain URL, timestamp, digest, free-text reviewer statement, workbook marker or caller-supplied boolean is not verification.

The verifier must validate source URL/host and retrieval-session evidence where applicable, preserve the original receipt/signature bytes or durable reference, and verify the signature/attestation against configured trust material or an authenticated reviewer identity. Do not implement a verifier that merely echoes fields supplied by the upload client.

`require_authenticated_statement` requires consistent authenticated status, publisher identity, and retained provenance evidence. It rejects structural-only and internally inconsistent/forged result states.

## Current production limitation

No trusted publisher verifier is configured or called by the canonical SIP upload/recommendation path. Therefore this code does not claim to authenticate CAS/CGS publishers in production. Statements may be structurally parsed for workflows that explicitly permit unverified user-provided data, but must remain source-unverified. Any workflow requiring authenticated registrar evidence must HOLD until a trusted verifier is configured and independently reviewed.

## Required adversarial coverage

Tests cover unknown publishers, embedded single-publisher claims, mixed/spoofed CAS and CGS labels, structurally valid but unauthenticated statements, weak reviewer-string/URL evidence without a verifier, verifier rejection, digest mismatch, and forged/inconsistent authentication flags.
