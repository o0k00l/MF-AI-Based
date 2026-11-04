"""Structural and provenance contract for injected SIP evidence providers.

Validation here is a gate, not an investment recommendation. Local hashes and
reviewer attestations do not independently authenticate a publisher.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timezone
from typing import Any


REQUIRED_EVIDENCE_FIELDS = frozenset({
    "metrics_path",
    "aliases_path",
    "metrics_source_metadata",
    "metrics_source_bytes",
    "scheme_master",
    "scheme_master_source_bytes",
    "portfolio_disclosures_by_scheme_id",
    "portfolio_disclosure_source_bytes_by_scheme_id",
    "disclosure_as_of_date",
    "candidate_universe",
    "candidate_universe_source",
    "candidate_universe_source_bytes",
})
REQUEST_BOUND_FIELDS = frozenset({"cas_path", "monthly_budget_inr", "risk_profile"})
OPTIONAL_EVIDENCE_FIELDS = frozenset({"portfolio_context", "portfolio_context_source_metadata", "portfolio_context_source_bytes", "candidate_score_source_metadata", "candidate_score_source_bytes", "category_anchor_source_metadata", "category_anchor_source_bytes"})


class EvidenceProviderContractError(ValueError):
    """Raised when a provider response violates the structural contract."""


def _validate_source_document(
    metadata: Any,
    source_bytes: Any,
    *,
    label: str,
    as_of: date,
    trust_registry: Optional[dict[str, Any]] = None,
    require_reviewer_signature: bool = False,
    structured_records: Optional[Any] = None,
    scope: Optional[str] = None,
    expected_scheme_id: Optional[str] = None,
) -> None:
    if not isinstance(metadata, dict):
        raise EvidenceProviderContractError(f"{label} source metadata must be a mapping.")
    if not isinstance(source_bytes, bytes) or not source_bytes:
        raise EvidenceProviderContractError(f"{label} original source bytes must be non-empty bytes.")

    source_url = metadata.get("source_url")
    declared_hash = metadata.get("source_document_sha256")
    if not isinstance(source_url, str) or not re.fullmatch(r"https://\S+", source_url):
        raise EvidenceProviderContractError(f"{label} source URL must be HTTPS.")
    if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash):
        raise EvidenceProviderContractError(f"{label} source SHA-256 must be 64 hexadecimal characters.")
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    if actual_hash != declared_hash.lower():
        raise EvidenceProviderContractError(f"{label} source SHA-256 does not match original bytes.")
    if metadata.get("reviewer_attested") is not True:
        raise EvidenceProviderContractError(f"{label} requires explicit reviewer attestation.")

    envelope = metadata.get("reviewer_approval_envelope")
    if require_reviewer_signature or envelope is not None or trust_registry is not None:
        if envelope is None:
            raise EvidenceProviderContractError(
                f"{label} requires verifiable independent reviewer signature envelope; plain boolean attestation is rejected."
            )
        if trust_registry is None:
            raise EvidenceProviderContractError(
                f"{label} requires independently administered trust registry to verify reviewer signature."
            )
        from services.sip_reviewer_approval import verify_sip_reviewer_approval
        now_dt = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
        res = verify_sip_reviewer_approval(
            envelope,
            trust_registry,
            expected_scope=scope,
            expected_source_sha256=actual_hash,
            structured_records=structured_records,
            expected_scheme_id=expected_scheme_id,
            now=now_dt,
        )
        if not res.ok:
            raise EvidenceProviderContractError(
                f"{label} reviewer signature verification failed: {'; '.join(res.errors)}"
            )

    effective_raw = metadata.get("effective_date")
    try:
        effective = date.fromisoformat(effective_raw) if isinstance(effective_raw, str) else None
    except ValueError:
        effective = None
    if effective is None:
        raise EvidenceProviderContractError(f"{label} effective_date must be an ISO date.")
    if effective > as_of:
        raise EvidenceProviderContractError(f"{label} effective_date is after the decision as-of date.")
    age_days = (as_of - effective).days
    if age_days > 45:
        raise EvidenceProviderContractError(f"{label} source is stale ({age_days} days; maximum 45).")

    source_type = metadata.get("source_type")
    if not isinstance(source_type, str) or not source_type.strip():
        raise EvidenceProviderContractError(f"{label} source_type is required.")


def _validate_scheme_master(
    master: Any,
    *,
    source_bytes: Optional[bytes] = None,
    trust_registry: Optional[dict[str, Any]] = None,
    require_reviewer_signature: bool = False,
    as_of: Optional[date] = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(master, dict) or master.get("status") != "VERIFIED":
        raise EvidenceProviderContractError("Scheme master must explicitly carry VERIFIED status.")
    schemes = master.get("schemes")
    if not isinstance(schemes, list) or not schemes:
        raise EvidenceProviderContractError("Verified scheme master must contain a non-empty schemes list.")

    by_scheme_id: dict[str, dict[str, Any]] = {}
    by_isin: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(schemes):
        if not isinstance(record, dict):
            raise EvidenceProviderContractError(f"Scheme master row {index} must be a mapping.")
        scheme_id, isin = record.get("scheme_id"), record.get("isin")
        if not isinstance(scheme_id, str) or not scheme_id.strip():
            raise EvidenceProviderContractError(f"Scheme master row {index} has no stable scheme_id.")
        if not isinstance(isin, str) or not isin.strip():
            raise EvidenceProviderContractError(f"Scheme master row {index} has no ISIN.")
        if scheme_id in by_scheme_id or isin in by_isin:
            raise EvidenceProviderContractError("Scheme master contains duplicate scheme_id or ISIN records.")
        required_master_fields = (
            "scheme_name", "amc_name", "category",
            "benchmark_identity", "scheme_structure",
        )
        if not all(isinstance(record.get(key), str) and record[key].strip()
                   for key in required_master_fields):
            raise EvidenceProviderContractError(
                f"Scheme master row {index} lacks exact scheme identity, category, benchmark or structure."
            )
        if str(record.get("plan_type", "")).strip().casefold() not in {"direct", "regular"}:
            raise EvidenceProviderContractError(
                f"Scheme master row {index} requires exact Direct/Regular plan_type."
            )
        if str(record.get("option_type", "")).strip().casefold() not in {"growth", "idcw"}:
            raise EvidenceProviderContractError(
                f"Scheme master row {index} requires exact Growth/IDCW option_type."
            )
        riskometer = record.get("riskometer_score")
        if (isinstance(riskometer, bool) or not isinstance(riskometer, int)
                or not 1 <= riskometer <= 6):
            raise EvidenceProviderContractError(
                f"Scheme master row {index} requires a verified integer scheme Riskometer score from 1 to 6."
            )
        by_scheme_id[scheme_id] = record
        by_isin[isin] = record

    envelope = master.get("reviewer_approval_envelope")
    if require_reviewer_signature or envelope is not None or trust_registry is not None:
        if envelope is None:
            raise EvidenceProviderContractError(
                "Scheme master requires verifiable independent reviewer signature envelope; plain boolean attestation is rejected."
            )
        if trust_registry is None:
            raise EvidenceProviderContractError(
                "Scheme master requires independently administered trust registry to verify reviewer signature."
            )
        from services.sip_reviewer_approval import verify_sip_reviewer_approval
        expected_hash = hashlib.sha256(source_bytes).hexdigest() if source_bytes else master.get("source_document_sha256")
        now_dt = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc) if as_of else None
        res = verify_sip_reviewer_approval(
            envelope,
            trust_registry,
            expected_scope="SIP_SCHEME_MASTER",
            expected_source_sha256=expected_hash,
            structured_records=schemes,
            now=now_dt,
        )
        if not res.ok:
            raise EvidenceProviderContractError(
                f"Scheme master reviewer signature verification failed: {'; '.join(res.errors)}"
            )
    return by_scheme_id


def validate_evidence_provider_payload(
    payload: Any,
    *,
    trust_registry: Optional[dict[str, Any]] = None,
    require_reviewer_signature: bool = True,
) -> dict[str, Any]:
    """Validate provider shape and critical source provenance before engine use."""
    if not isinstance(payload, dict):
        raise EvidenceProviderContractError("Provider response must be a mapping.")

    supplied = set(payload)
    missing = REQUIRED_EVIDENCE_FIELDS - supplied
    unexpected = supplied - REQUIRED_EVIDENCE_FIELDS - OPTIONAL_EVIDENCE_FIELDS
    optional_present = supplied & OPTIONAL_EVIDENCE_FIELDS
    portfolio_context_fields = {
        "portfolio_context", "portfolio_context_source_metadata",
        "portfolio_context_source_bytes",
    }
    portfolio_context_present = supplied & portfolio_context_fields
    if portfolio_context_present and portfolio_context_present != portfolio_context_fields:
        raise EvidenceProviderContractError(
            "Portfolio context, source metadata and original source bytes must be supplied together."
        )
    metrics_fields = {"metrics_source_metadata", "metrics_source_bytes"}
    metrics_present = supplied & metrics_fields
    if metrics_present != metrics_fields:
        raise EvidenceProviderContractError(
            "Fund metrics source metadata and original source bytes are mandatory and must be supplied together."
        )
    if missing:
        raise EvidenceProviderContractError(
            "Provider response is missing required fields: " + ", ".join(sorted(missing))
        )
    if unexpected:
        raise EvidenceProviderContractError(
            "Provider response contains unsupported fields: " + ", ".join(sorted(unexpected))
        )
    score_source_fields = {"candidate_score_source_metadata", "candidate_score_source_bytes"}
    score_source_present = optional_present & score_source_fields
    if score_source_present and score_source_present != score_source_fields:
        raise EvidenceProviderContractError(
            "Candidate score source metadata and original source bytes must be supplied together."
        )
    anchor_source_fields = {"category_anchor_source_metadata", "category_anchor_source_bytes"}
    anchor_source_present = optional_present & anchor_source_fields
    if anchor_source_present and anchor_source_present != anchor_source_fields:
        raise EvidenceProviderContractError(
            "Category anchor source metadata and original source bytes must be supplied together."
        )

    as_of = payload["disclosure_as_of_date"]
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise EvidenceProviderContractError("disclosure_as_of_date must be a date, not a timestamp or string.")

    scheme_records = payload["scheme_master"].get("schemes") if isinstance(payload["scheme_master"], dict) else None
    _validate_source_document(
        payload["scheme_master"], payload["scheme_master_source_bytes"],
        label="Scheme master", as_of=as_of,
        trust_registry=trust_registry,
        require_reviewer_signature=require_reviewer_signature,
        structured_records=scheme_records,
        scope="SIP_SCHEME_MASTER",
    )
    if metrics_present == metrics_fields:
        _validate_source_document(
            payload["metrics_source_metadata"], payload["metrics_source_bytes"],
            label="Fund metrics", as_of=as_of,
            trust_registry=trust_registry,
            require_reviewer_signature=require_reviewer_signature,
            scope="SIP_EVIDENCE_RELEASE",
            structured_records={
                "normalized_metrics_sha256": payload["metrics_source_metadata"].get(
                    "normalized_metrics_sha256"
                )
            },
        )
        metrics_path = payload["metrics_path"]
        if not isinstance(metrics_path, Path) or metrics_path.is_symlink() or not metrics_path.is_file():
            raise EvidenceProviderContractError(
                "Fund metrics normalized file must be a regular, non-symlink file."
            )
        if metrics_path.stat().st_size <= 0 or metrics_path.stat().st_size > 50 * 1024 * 1024:
            raise EvidenceProviderContractError(
                "Fund metrics normalized file is empty or exceeds the 50 MiB limit."
            )
        normalized_digest = payload["metrics_source_metadata"].get("normalized_metrics_sha256")
        if not isinstance(normalized_digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", normalized_digest):
            raise EvidenceProviderContractError(
                "Fund metrics metadata requires normalized_metrics_sha256."
            )
        actual_normalized_digest = hashlib.sha256(metrics_path.read_bytes()).hexdigest()
        if actual_normalized_digest != normalized_digest.lower():
            raise EvidenceProviderContractError(
                "Fund metrics normalized file SHA-256 does not match reviewed metadata."
            )
    if portfolio_context_present:
        if not isinstance(payload["portfolio_context"], dict):
            raise EvidenceProviderContractError("portfolio_context must be a mapping.")
        _validate_source_document(
            payload["portfolio_context_source_metadata"],
            payload["portfolio_context_source_bytes"],
            label="Total portfolio context", as_of=as_of,
            trust_registry=trust_registry,
            require_reviewer_signature=require_reviewer_signature,
            scope="SIP_EVIDENCE_RELEASE",
            structured_records={
                "normalized_portfolio_context_sha256": payload[
                    "portfolio_context_source_metadata"
                ].get("normalized_portfolio_context_sha256")
            },
        )
    if score_source_present:
        score_metadata = payload["candidate_score_source_metadata"]
        _validate_source_document(
            score_metadata,
            payload["candidate_score_source_bytes"],
            label="Candidate ranking scores",
            as_of=as_of,
            trust_registry=trust_registry,
            require_reviewer_signature=require_reviewer_signature,
            scope="SIP_EVIDENCE_RELEASE",
            structured_records=[
                {
                    field: candidate.get(field)
                    for field in (
                        "fund_id", "rank_score", "rank_score_source_ref",
                        "rank_score_as_of_date", "rank_score_methodology_version",
                        "rank_score_scope", "rank_score_portfolio_overlap_status",
                        "rank_score_portfolio_overlap_pct",
                        "rank_score_portfolio_overlap_coverage_pct",
                        "rank_score_portfolio_overlap_source_ref",
                        "rank_score_category_anchor_source_ref",
                        "rank_score_category_anchor_policy_version",
                        "rank_score_benchmark_identity",
                    )
                }
                for candidate in payload["candidate_universe"]
                if isinstance(candidate, dict) and "rank_score" in candidate
            ],
        )
        if not isinstance(score_metadata.get("methodology_version"), str) or not score_metadata["methodology_version"].strip():
            raise EvidenceProviderContractError("Candidate score source requires methodology_version.")
        if score_metadata.get("score_scope") != "PORTFOLIO_AWARE":
            raise EvidenceProviderContractError("Candidate score source must explicitly declare PORTFOLIO_AWARE scope.")
        if score_metadata.get("missing_overlap_policy") != "BLOCK_SCORE":
            raise EvidenceProviderContractError("Portfolio-aware score source must block missing overlap evidence.")

    if anchor_source_present:
        anchor_metadata = payload["category_anchor_source_metadata"]
        _validate_source_document(
            anchor_metadata,
            payload["category_anchor_source_bytes"],
            label="Category benchmark anchors",
            as_of=as_of,
            trust_registry=trust_registry,
            require_reviewer_signature=require_reviewer_signature,
            scope="SIP_EVIDENCE_RELEASE",
            structured_records=anchor_metadata.get("category_anchors"),
        )
        if not isinstance(anchor_metadata.get("policy_version"), str) or not anchor_metadata["policy_version"].strip():
            raise EvidenceProviderContractError("Category benchmark anchor source requires policy_version.")
        if not isinstance(anchor_metadata.get("reviewer_id"), str) or not anchor_metadata["reviewer_id"].strip():
            raise EvidenceProviderContractError("Category benchmark anchor source requires reviewer_id.")
        category_anchors = anchor_metadata.get("category_anchors")
        if not isinstance(category_anchors, dict) or not category_anchors:
            raise EvidenceProviderContractError("Approved category benchmark anchors must be supplied by category.")
        required_anchor_keys = {"alpha", "ret1y", "sharpe", "ter", "buffer", "intl", "overlap"}
        for category, anchor_record in category_anchors.items():
            if not isinstance(category, str) or not category.strip() or not isinstance(anchor_record, dict):
                raise EvidenceProviderContractError("Category anchor records must be keyed by exact category name.")
            if anchor_record.get("status") != "APPROVED":
                raise EvidenceProviderContractError(f"Category {category!r} anchor set is not approved.")
            if not isinstance(anchor_record.get("benchmark_identity"), str) or not anchor_record["benchmark_identity"].strip():
                raise EvidenceProviderContractError(f"Category {category!r} anchor set requires benchmark identity.")
            if anchor_record.get("reviewer_id") != anchor_metadata["reviewer_id"]:
                raise EvidenceProviderContractError(f"Category {category!r} anchor reviewer does not match source reviewer.")
            if anchor_record.get("policy_version") != anchor_metadata["policy_version"]:
                raise EvidenceProviderContractError(f"Category {category!r} anchor policy version does not match source policy version.")
            if anchor_record.get("effective_date") != anchor_metadata["effective_date"]:
                raise EvidenceProviderContractError(f"Category {category!r} anchor effective date does not match source evidence.")
            anchor_set = anchor_record.get("anchor_set")
            if not isinstance(anchor_set, dict) or set(anchor_set) != required_anchor_keys:
                raise EvidenceProviderContractError(f"Category {category!r} anchor set must define all seven scoring metric bounds.")
            for metric, bounds in anchor_set.items():
                if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                    raise EvidenceProviderContractError(f"Category {category!r} anchor {metric!r} must have two bounds.")
                try:
                    lower, upper = Decimal(str(bounds[0])), Decimal(str(bounds[1]))
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise EvidenceProviderContractError(f"Category {category!r} anchor {metric!r} bounds are invalid.") from exc
                if not lower.is_finite() or not upper.is_finite() or lower >= upper:
                    raise EvidenceProviderContractError(f"Category {category!r} anchor {metric!r} bounds must be finite and increasing.")
    scheme_index = _validate_scheme_master(
        payload["scheme_master"],
        source_bytes=payload.get("scheme_master_source_bytes"),
        trust_registry=trust_registry,
        require_reviewer_signature=require_reviewer_signature,
        as_of=as_of,
    )

    disclosures = payload["portfolio_disclosures_by_scheme_id"]
    disclosure_bytes = payload["portfolio_disclosure_source_bytes_by_scheme_id"]
    if not isinstance(disclosures, dict) or not isinstance(disclosure_bytes, dict):
        raise EvidenceProviderContractError("Disclosure records and source bytes must be mappings.")
    if set(disclosures) != set(disclosure_bytes):
        raise EvidenceProviderContractError(
            "Disclosure records and source bytes must have identical scheme-ID keys."
        )
    for scheme_id, record in disclosures.items():
        if not isinstance(scheme_id, str) or not scheme_id.strip():
            raise EvidenceProviderContractError("Disclosure keys must be non-empty stable scheme IDs.")
        if scheme_id not in scheme_index:
            raise EvidenceProviderContractError(f"Disclosure scheme ID {scheme_id!r} is absent from verified scheme master.")
        if not isinstance(record, dict) or record.get("scheme_id") != scheme_id:
            raise EvidenceProviderContractError(f"Disclosure record for {scheme_id!r} has conflicting scheme identity.")
        raw = disclosure_bytes[scheme_id]
        if not isinstance(raw, bytes) or not raw:
            raise EvidenceProviderContractError(f"Original source bytes for {scheme_id!r} are missing.")
        if require_reviewer_signature:
            raw_weights = record.get("constituent_weights")
            coverage_raw = record.get("constituent_weights_coverage_pct")
            try:
                signed_weights = {
                    str(key).strip().upper(): float(value)
                    for key, value in raw_weights.items()
                } if isinstance(raw_weights, dict) else None
                signed_coverage = float(coverage_raw)
            except (TypeError, ValueError, AttributeError, OverflowError) as exc:
                raise EvidenceProviderContractError(
                    f"Portfolio disclosure {scheme_id!r} has malformed signed constituent weights."
                ) from exc
            if signed_weights is None:
                raise EvidenceProviderContractError(
                    f"Portfolio disclosure {scheme_id!r} has no signed constituent weights."
                )
            _validate_source_document(
                record, raw, label=f"Portfolio disclosure {scheme_id!r}", as_of=as_of,
                trust_registry=trust_registry,
                require_reviewer_signature=True,
                structured_records={
                    "constituent_weights": signed_weights,
                    "coverage_pct": signed_coverage,
                },
                scope="SIP_PORTFOLIO_DISCLOSURE",
                expected_scheme_id=scheme_id,
            )
        else:
            _validate_source_document(
                record, raw, label=f"Portfolio disclosure {scheme_id!r}", as_of=as_of,
            )

    candidates = payload["candidate_universe"]
    if not isinstance(candidates, list) or not candidates:
        raise EvidenceProviderContractError("candidate_universe must be a non-empty list.")
    candidate_source = payload["candidate_universe_source"]
    _validate_source_document(
        candidate_source, payload["candidate_universe_source_bytes"],
        label="Candidate universe", as_of=as_of,
        trust_registry=trust_registry,
        require_reviewer_signature=require_reviewer_signature,
        structured_records=candidates,
        scope="SIP_CANDIDATE_UNIVERSE",
    )
    if candidate_source.get("universe_complete") is not True:
        raise EvidenceProviderContractError("Candidate universe must be explicitly reviewer-attested as complete.")
    if not isinstance(candidate_source.get("coverage_scope"), str) or not candidate_source["coverage_scope"].strip():
        raise EvidenceProviderContractError("Candidate universe coverage_scope must identify the covered market/universe.")
    seen_fund_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or not candidate:
            raise EvidenceProviderContractError(f"Candidate row {index} must be a non-empty mapping.")
        fund_id = candidate.get("fund_id") or candidate.get("id")
        if not isinstance(fund_id, str) or not fund_id.strip():
            raise EvidenceProviderContractError(f"Candidate row {index} requires a stable fund_id.")
        if fund_id in seen_fund_ids:
            raise EvidenceProviderContractError(f"Duplicate candidate fund_id: {fund_id!r}.")
        seen_fund_ids.add(fund_id)

        required_text = (
            "fund_name", "scheme_id", "isin", "amc_name", "category",
            "plan_type", "option_type",
        )
        for field in required_text:
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                raise EvidenceProviderContractError(f"Candidate {fund_id!r} requires {field}.")
        master_record = scheme_index.get(candidate["scheme_id"])
        if master_record is None:
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} scheme_id is absent from verified scheme master.")
        if (candidate["isin"] != master_record["isin"]
                or candidate["fund_name"].strip().casefold() != master_record["scheme_name"].strip().casefold()
                or candidate["amc_name"].strip().casefold() != master_record["amc_name"].strip().casefold()):
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} identity conflicts with verified scheme master.")
        if candidate["plan_type"].strip().casefold() != master_record["plan_type"].strip().casefold():
            raise EvidenceProviderContractError(
                f"Candidate {fund_id!r} plan_type conflicts with verified scheme master."
            )
        if candidate["option_type"].strip().casefold() != master_record["option_type"].strip().casefold():
            raise EvidenceProviderContractError(
                f"Candidate {fund_id!r} option_type conflicts with verified scheme master."
            )
        if candidate["plan_type"].strip().casefold() != "direct":
            raise EvidenceProviderContractError(
                f"Candidate {fund_id!r} must be an explicitly verified Direct plan."
            )
        if candidate["category"].strip().casefold() != master_record["category"].strip().casefold():
            raise EvidenceProviderContractError(
                f"Candidate {fund_id!r} category conflicts with verified scheme master."
            )
        for field in ("benchmark_identity", "scheme_structure", "riskometer_score"):
            if candidate.get(field) != master_record[field]:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} {field} conflicts with verified scheme master."
                )
        if candidate.get("is_direct") is not True:
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} is not explicitly classified as Direct.")
        if not isinstance(candidate.get("direct_plan_evidence"), dict):
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} is missing Direct-plan source evidence.")
        if not isinstance(candidate.get("_evidence_root"), (str, __import__("pathlib").Path)):
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} is missing its evidence root.")
        from core.eligibility import _reviewed_direct_plan_evidence_status
        if _reviewed_direct_plan_evidence_status(
            candidate, as_of_date=as_of, trust_registry=trust_registry,
            require_signature=require_reviewer_signature,
        ) != "REVIEWER_ATTESTED_HASH_MATCH":
            raise EvidenceProviderContractError(
                f"Candidate {fund_id!r} Direct-plan source evidence is invalid, stale, or identity-conflicting."
            )

        score_fields = {
            "rank_score", "rank_score_source_ref",
            "rank_score_as_of_date", "rank_score_methodology_version",
            "rank_score_scope", "rank_score_portfolio_overlap_status",
            "rank_score_portfolio_overlap_pct", "rank_score_portfolio_overlap_coverage_pct",
            "rank_score_portfolio_overlap_source_ref",
            "rank_score_category_anchor_source_ref",
            "rank_score_category_anchor_policy_version",
            "rank_score_benchmark_identity",
        }
        score_supplied = score_fields & set(candidate)
        if score_supplied and score_supplied != score_fields:
            raise EvidenceProviderContractError(
                f"Candidate {fund_id!r} has incomplete rank-score provenance."
            )
        if score_supplied:
            if not score_source_present:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} has a rank score without a reviewed score source bundle."
                )
            try:
                score = Decimal(str(candidate["rank_score"]))
                score_date = date.fromisoformat(candidate["rank_score_as_of_date"])
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} rank score or score date is invalid."
                ) from exc
            if not score.is_finite() or score <= 0:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} rank score must be finite and positive."
                )
            expected_score_ref = "sha256:" + payload["candidate_score_source_metadata"]["source_document_sha256"].lower()
            if candidate["rank_score_source_ref"] != expected_score_ref:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} rank score source reference does not match reviewed source bytes."
                )
            if score_date.isoformat() != payload["candidate_score_source_metadata"]["effective_date"]:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} rank score date does not match the reviewed source effective date."
                )
            if candidate["rank_score_methodology_version"] != payload["candidate_score_source_metadata"]["methodology_version"]:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} rank score methodology version is not the reviewed version."
                )
            if not anchor_source_present:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} rank score has no independently reviewed category anchor source."
                )
            if candidate["rank_score_scope"] != "PORTFOLIO_AWARE":
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} rank score is not marked portfolio-aware."
                )
            if candidate["rank_score_portfolio_overlap_status"] != "VERIFIED":
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} lacks verified portfolio overlap; neutral fallback is prohibited."
                )
            try:
                overlap_pct = Decimal(str(candidate["rank_score_portfolio_overlap_pct"]))
                overlap_coverage = Decimal(str(candidate["rank_score_portfolio_overlap_coverage_pct"]))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} portfolio overlap evidence is invalid."
                ) from exc
            if not overlap_pct.is_finite() or overlap_pct < 0 or overlap_pct > 100:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} portfolio overlap percentage is invalid."
                )
            if not overlap_coverage.is_finite() or overlap_coverage < Decimal("99.5") or overlap_coverage > 100:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} portfolio overlap coverage is below 99.5 percent."
                )
            for ref_field in ("rank_score_portfolio_overlap_source_ref", "rank_score_category_anchor_source_ref"):
                value = candidate[ref_field]
                if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                    raise EvidenceProviderContractError(
                        f"Candidate {fund_id!r} {ref_field} must be a SHA-256 source reference."
                    )
            anchor_metadata = payload["category_anchor_source_metadata"]
            anchor_digest_ref = "sha256:" + anchor_metadata["source_document_sha256"].lower()
            if candidate["rank_score_category_anchor_source_ref"] != anchor_digest_ref:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} category anchor source reference does not match original reviewed bytes."
                )
            if candidate["rank_score_category_anchor_policy_version"] != anchor_metadata["policy_version"]:
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} category anchor policy version is not approved."
                )
            approved_category = anchor_metadata["category_anchors"].get(candidate["category"])
            if not isinstance(approved_category, dict):
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} category has no approved benchmark anchor set."
                )
            if (
                candidate["rank_score_benchmark_identity"] != approved_category["benchmark_identity"]
                or approved_category["status"] != "APPROVED"
            ):
                raise EvidenceProviderContractError(
                    f"Candidate {fund_id!r} benchmark identity or category anchor approval conflicts."
                )

    for optional_path in ("metrics_path", "aliases_path"):
        value = payload[optional_path]
        if optional_path == "metrics_path" and (value is None or not hasattr(value, "is_file")):
            raise EvidenceProviderContractError("metrics_path must be a Path-like source for candidate evidence files.")
        if value is not None and not hasattr(value, "is_file"):
            raise EvidenceProviderContractError(f"{optional_path} must be a Path-like object or None.")

    # The completeness flag is an attestation, not an independent proof that
    # every eligible scheme in the stated market scope has been enumerated.
    # Publisher authenticity and reviewer identity also remain external checks.
    return dict(payload)
