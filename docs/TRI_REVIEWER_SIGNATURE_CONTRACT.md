# TRI Reviewer Approval — Cryptographic Trust Contract

**Status: DESIGN / NOT IMPLEMENTED. TRI release remains blocked.**

This contract defines the minimum cryptographic approval mechanism required before any TRI fixture or NSE trading-calendar evidence can be considered independently reviewed. It does not authenticate source publishers by itself and it does not make provisional market data eligible.

## Security objective

A release verifier must establish all of the following without trusting editable provenance fields in the TRI fixture:

1. A named independent reviewer approved a specific evidence package.
2. The approval was signed by a reviewer key authorized by a separately administered trust root.
3. The signature covers the exact bytes/digests of every TRI source document, parsed series, calendar source document, normalized calendar sessions and the review scope.
4. The approval is current, not expired or revoked, and uses an explicitly allowed signature algorithm.
5. The verifier fails closed if the trust root, signature, evidence, reviewer identity, scope, time bounds or key status is missing or invalid.

A local SHA-256 checksum is an integrity check only. It is not a signature, identity proof, source authenticity proof or independent review.

## Trust model

- Use Ed25519 signatures. Do not accept algorithm negotiation, none, HMAC, or an algorithm selected by the approval document.
- The reviewer's private key is held outside GitHub source control and outside the application runtime; hardware-backed key storage is preferred.
- The detached approval envelope is supplied through a separately administered release variable, not committed into the tree whose commit SHA it signs. This avoids a circular dependency between the signed approval and the Git commit hash.
- The verifier receives an allow-listed reviewer public-key registry from a separately administered deployment trust configuration. The registry must not be sourced from the TRI fixture, an ordinary repository file, a pull-request artifact, or a value editable by the same workflow that is being verified.
- The trust configuration is public material, not a secret. Its integrity and change control are security-critical. Restrict modification to a designated security administrator, require audited changes and dual control for key addition/revocation.
- The application and release workflow must use the same trust-root policy. Missing trust configuration means BLOCKED; never fall back to trusting an embedded public key.
- Key rotation must support overlapping validity windows. Revocation must invalidate approvals made after the effective revocation time and support emergency revocation of a compromised key.
- GitHub commit authorship, a GitHub review approval, a checked-in public key, and a self-asserted reviewer name are not substitutes for this signature.

## Signed approval envelope

Use a detached signature over the RFC 8785 JSON Canonicalization Scheme (JCS) bytes of the complete payload. The signature is base64url-encoded without padding. The envelope is stored separately from the source fixture and contains only:

- payload: the approval payload object.
- signature: detached Ed25519 signature over JCS(payload).

Required payload fields:

| Field | Requirement |
|---|---|
| schema_version | Exact supported schema version; reject unknown versions. |
| approval_id | Unique immutable identifier. |
| approval_scope | Fixed value TRI_EVIDENCE_RELEASE; no wildcard scopes. |
| reviewer_id | Stable reviewer identity, resolved through the trust registry. |
| reviewer_key_id | Key identifier in the external trust registry. |
| issued_at, expires_at | UTC RFC 3339 timestamps; reject malformed, future-issued beyond configured clock skew, or expired approvals. |
| repository | Exact repository identifier. |
| commit_sha | Exact 40-character commit SHA whose evidence is approved. |
| tri_fixture_sha256 | SHA-256 of the exact high-coverage fixture bytes. |
| tri_source_documents | Complete sorted list of source-document paths and SHA-256 digests, one per approved benchmark. |
| calendar_source_path, calendar_source_url | Exact repository-relative source path and official HTTPS URL for the original calendar document. |
| calendar_source_sha256 | SHA-256 of the original calendar source document. |
| calendar_sessions_sha256 | SHA-256 of JCS(normalized sorted session-date array). |
| review_attestation | Explicit reviewer attestation that source identity, index identifiers, observations, corrections, session coverage and parsing were independently checked. |

No payload field may be treated as true merely because it is signed: the verifier must independently recompute every digest and validate the underlying evidence and schema.

## Verification sequence

1. Load the trust registry only from the separately administered trust configuration.
2. Parse the envelope with duplicate JSON keys rejected; validate exact schema and bounded input sizes.
3. Resolve reviewer_key_id; require the key to be active for the approval's issuance time and not revoked.
4. Canonicalize the payload with the repository's RFC 8785 implementation and verify the Ed25519 signature.
5. Check reviewer identity, allowed scope, repository and exact commit SHA.
6. Enforce issued/expiry times using an injectable UTC clock in tests.
7. Recompute fixture, source-document and normalized calendar digests from files inside the repository boundary.
8. Independently validate benchmark identifiers, daily frequency, no interpolation, observation values and exact equality to the verified NSE session calendar.
9. Return a structured verification result with the approval ID, reviewer ID, key ID and evidence digests. Never return eligible if any check fails.
10. Keep publisher authenticity as a separate gate: a reviewer signature attests to review; it does not magically prove that a publisher's source document is genuine.

## Required negative and positive tests

- Valid signature with active trusted key and exact evidence passes cryptographic approval verification.
- One-byte change to payload, signature, fixture, source document or calendar fails.
- Unknown key, untrusted embedded key, revoked key, expired key, expired approval, future issue time and unsupported algorithm fail.
- Wrong repository, commit, scope, reviewer identity or evidence digest fails.
- Missing trust registry, malformed registry, duplicate JSON keys, malformed base64url and malformed timestamps fail closed.
- Approval for one commit cannot authorize a different commit or changed fixture.
- A valid signature cannot override missing official source documents, incomplete sessions, interpolated observations or invalid benchmark identifiers.
- Trust-root rotation and revocation behavior are covered by deterministic tests. A revocation invalidates outstanding approvals at verification time, not only approvals issued after revocation.
- Tests use generated ephemeral keys only; no production private key or real reviewer identity is committed.

## Implementation and release requirements

- Add a maintained Ed25519-capable dependency and pin it in both requirements.txt and the hash-locked requirements.lock. Regenerate the lock using the repository's documented process; do not hand-edit hashes.
- Add a standalone verifier module and CLI tests. Keep ordinary CI able to test fixture integrity without production keys, but make the release gate require a valid external trust registry and signed approval.
- Configure a GitHub Actions Environment named production with required independent deployment reviewers, protected tag/deployment restrictions and audited administrators. Store TRI_REVIEWER_TRUST_REGISTRY_JSON and TRI_REVIEWER_APPROVAL_JSON as environment-scoped Actions secrets so the release workflow cannot silently fall back to ordinary repository variables. Their contents are public cryptographic material, not private signing keys; the secrets mechanism is used to enforce protected release access.
- Add a key ceremony and reviewer operating procedure before any real approval is issued.
- Until implementation, deployment configuration, signed evidence and independent source/calendar validation all exist, the alpha release gate must continue to fail and aggregate benchmark XIRR/alpha must remain unavailable.
