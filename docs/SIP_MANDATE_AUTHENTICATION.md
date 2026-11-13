# SIP mandate authentication contract

**Status:** Implemented verification boundary; production issuer trust configuration and real provider schedules remain deployment prerequisites.

## Decision rule

CAS transaction rows, free-text labels, UMRNs, mandate IDs, a status field, and a caller-supplied `evidence_attested_by_provider` boolean are not authentication. They may be retained as transaction evidence, but they cannot reduce monthly SIP affordability commitments.

Only a complete schedule with a valid detached Ed25519 signature from a signer present in the deployment-owned trust registry can be counted. The signature binds:

- the original schedule source bytes;
- the canonical normalized schedule records;
- the investor owner reference;
- signer identity, key identity and signer class;
- issue and expiry timestamps.

Each mandate record is then checked for owner, folio, exact scheme ID, status, monthly amount, frequency, effective dates and next debit date. Each record's `evidence_ref` is the SHA-256 digest of its canonical record with `evidence_ref` omitted. The full schedule digest includes all records including those references.

## Deployment trust root

Production must configure `SIP_MANDATE_TRUST_REGISTRY_JSON` outside the repository and outside the uploaded evidence bundle. It is a JSON object with `schema_version: 1` and a non-empty `keys` array. Each key entry contains:

- `key_id`: unique key identifier;
- `signer_id`: stable registrar, AMC, bank or investor identity;
- `signer_type`: one of `REGISTRAR`, `AMC`, `BANK`, `INVESTOR`;
- `public_key`: canonical unpadded base64url encoding of the 32-byte Ed25519 public key;
- `valid_from` and `valid_until`: canonical UTC RFC3339 timestamps;
- `revoked`: boolean.

A signer type is constrained by the mandate record's authentication method:

| Authentication method | Required signer type |
|---|---|
| `REGISTRAR_SIGNED` | `REGISTRAR` |
| `AMC_SIGNED` | `AMC` |
| `BANK_MANDATE_SIGNED` | `BANK` |
| `INVESTOR_SIGNED_CONFIRMATION` | `INVESTOR` |

For investor-signed confirmation, the trusted signer identity must equal the investor owner reference. A request or evidence payload cannot provide or replace the trust registry.

## Evidence envelope

The internal evidence object contains `coverage_status`, `source_bytes` (the original bytes), `source_ref` (`sha256:<64 lowercase hex>`), `mandates`, and `signature_envelope`. The envelope has exactly `payload` and `signature`.

When this evidence is stored in the filesystem-backed JSON bundle, the JSON field is `source_bytes_base64` (canonical standard Base64). The bundle loader decodes it to internal `source_bytes` before the SIP service sees it; a JSON-supplied `source_bytes` field is rejected. The enclosing portfolio-context artifact is separately reviewer-signed and digest-checked.

The signed payload has exactly:

- `schema_version` = 1;
- `signer_id`, `signer_key_id`, `signer_type`;
- `owner_ref`;
- `source_sha256`;
- `schedule_sha256`;
- `issued_at`, `expires_at`.

The signature is Ed25519 over RFC 8785 JSON Canonicalization Scheme bytes of the payload. `source_sha256` must match the original source bytes and `schedule_sha256` must match the canonical normalized mandate list. The signed expiry and trusted key validity must cover the decision as-of date.

## Fail-closed behavior

Missing trust configuration, missing source bytes, incomplete coverage, invalid/expired signatures, unknown/revoked keys, signer-role mismatch, owner mismatch, source or schedule digest mismatch, malformed mandate terms, and stale active mandate terms return HOLD. The former non-authenticated detector opt-out is disabled.

A complete, validly signed schedule with an empty mandate list represents a verified zero-commitment result. An absent or incomplete schedule is UNKNOWN/HOLD, not zero.

## Operational prerequisite

The production API accepts the mandate schedule only inside the reviewer-validated provider portfolio-context bundle. At the API boundary it independently verifies the mandate-specific Ed25519 envelope against the deployment-owned `SIP_MANDATE_TRUST_REGISTRY_JSON` and sets the internal provider-attestation gate only on success; a provider-supplied boolean is overwritten. The recommendation service repeats signature and record-term verification immediately before affordability calculations. The API copies the context before adding internal verification flags so cached provider payloads are not mutated across requests.

The implementation defines and verifies the evidence contract; it does not manufacture provider signatures or claim that a CAS worksheet is a trusted registrar feed. A production deployment must obtain the actual schedule from the authorized registrar/AMC/bank or a signed investor confirmation, preserve its original bytes, and provision the independently administered trust registry. Until a complete, correctly signed schedule is supplied for the investor and decision date, the SIP decision remains fail-closed.
