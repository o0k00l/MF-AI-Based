"""
services/acquisition/bundle_builder.py - Evidence bundle builder with atomic staging and rollback.
Issue #110: Deterministically synthesize and promote evidence bundles conforming to schema v1.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from services.sip_evidence_bundle import build_sip_evidence_provider


class EvidenceBundleBuilder:
    """
    Constructs and promotes a verified SIP evidence bundle directory.

    Maintains full cryptographic binding:
    - Raw source documents in originals/
    - SHA-256 digests in source metadata
    - Normalized JSON records matching reviewed metadata hashes
    - Atomic promotion with rollback to guarantee last-known-good state preservation.
    """

    def __init__(self, target_bundle_dir: Path):
        self.target_dir = Path(target_bundle_dir).expanduser().resolve()

    def _write_json(self, path: Path, data: Any) -> None:
        from decimal import Decimal
        path.parent.mkdir(parents=True, exist_ok=True)
        def decimal_default(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
        serialized = json.dumps(data, indent=2, sort_keys=True, default=decimal_default)
        path.write_text(serialized, encoding="utf-8")

    def _write_bytes(self, path: Path, raw_bytes: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw_bytes)

    @staticmethod
    def compute_bundle_digest(staging_dir: Path) -> str:
        """Compute SHA-256 digest of bundle payload files excluding detached reviewer envelopes."""
        bundle_files = sorted([
            p for p in staging_dir.rglob("*")
            if p.is_file() and p.name not in ("reviewer_approval_envelope.json", "reviewer_trust_registry.json")
        ])
        hasher = hashlib.sha256()
        for bf in bundle_files:
            rel = str(bf.relative_to(staging_dir)).replace("\\", "/")
            hasher.update(rel.encode("utf-8"))
            hasher.update(bf.read_bytes())
        return hasher.hexdigest()

    def build_and_promote(
        self,
        as_of: date,
        *,
        scheme_master: Dict[str, Any],
        scheme_master_source_bytes: bytes,
        metrics_payload: Dict[str, Any],
        metrics_source_bytes: bytes,
        candidate_universe: List[Dict[str, Any]],
        candidate_universe_source_bytes: bytes,
        portfolio_disclosures: Dict[str, Dict[str, Any]],
        portfolio_disclosure_source_bytes: Dict[str, bytes],
        direct_plan_evidence_bytes: Dict[str, bytes],
        master_source_url: Optional[str] = None,
        metrics_source_url: Optional[str] = None,
        universe_source_url: Optional[str] = None,
        aliases_payload: Optional[Dict[str, Any]] = None,
        aliases_source_bytes: Optional[bytes] = None,
        reviewer_attested: bool = False,
        reviewer_approval_envelope: Optional[Union[Dict[str, Any], Callable[[str], Dict[str, Any]]]] = None,
        reviewer_trust_registry: Optional[Dict[str, Any]] = None,
        expected_commit_sha: Optional[str] = None,
        expected_policy_digest: Optional[str] = None,
        require_commit_binding: bool = True,
        require_policy_binding: bool = True,
        require_artifact_binding: bool = True,
    ) -> Path:
        """
        Build an evidence bundle in a staging directory, verify its integrity,
        and atomically promote it to target_dir. Fails closed on any synthetic
        or missing evidence.
        Issue #112: In every production promotion path, cryptographic artifact digest,
        commit SHA, and policy digest binding are strictly mandatory and cannot be disabled.
        """
        if require_artifact_binding is False:
            raise ValueError(
                "Promotion requires mandatory cryptographic artifact digest binding; "
                "caller cannot disable it."
            )
        if require_commit_binding is False:
            raise ValueError(
                "Promotion requires mandatory cryptographic commit SHA binding; "
                "caller cannot disable it."
            )
        if require_policy_binding is False:
            raise ValueError(
                "Promotion requires mandatory cryptographic policy digest binding; "
                "caller cannot disable it."
            )

        if reviewer_approval_envelope is None or reviewer_trust_registry is None:
            raise ValueError(
                "Promotion blocked: independent reviewer approval envelope and trust registry are required; "
                "caller-asserted boolean flags without cryptographic signature cannot promote an evidence bundle."
            )
        from services.sip_reviewer_approval import verify_sip_reviewer_approval
        if isinstance(reviewer_approval_envelope, dict):
            approval_res = verify_sip_reviewer_approval(
                envelope=reviewer_approval_envelope,
                trust_registry=reviewer_trust_registry,
                expected_scope="SIP_EVIDENCE_RELEASE",
                expected_commit_sha=expected_commit_sha,
                expected_policy_digest=expected_policy_digest,
                require_commit_binding=True,
                require_policy_binding=True,
                require_artifact_binding=False,
            )
            if not approval_res.ok:
                raise ValueError(f"Independent reviewer approval verification failed: {'; '.join(approval_res.errors)}")

        self.target_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = self.target_dir.parent / f".staging_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Scheme Master
            master_rel_source = "originals/scheme_master.json"
            self._write_bytes(staging_dir / master_rel_source, scheme_master_source_bytes)
            master_source_sha256 = hashlib.sha256(scheme_master_source_bytes).hexdigest()

            normalized_master = dict(scheme_master)
            master_url = master_source_url or normalized_master.get("source_url")
            if not master_url or not str(master_url).strip():
                raise ValueError("Authoritative scheme master source URL is missing; synthetic defaults are prohibited.")
            normalized_master["source_url"] = str(master_url).strip()
            normalized_master["source_document_sha256"] = master_source_sha256
            normalized_master["reviewer_attested"] = reviewer_attested
            normalized_master["effective_date"] = as_of.isoformat()
            normalized_master["source_type"] = "OFFICIAL_SCHEME_MASTER"
            normalized_master["status"] = "VERIFIED"
            self._write_json(staging_dir / "scheme_master.json", normalized_master)

            # 2. Metrics & Metrics Metadata
            metrics_rel_source = "originals/metrics.csv"
            self._write_bytes(staging_dir / metrics_rel_source, metrics_source_bytes)
            metrics_source_sha256 = hashlib.sha256(metrics_source_bytes).hexdigest()

            self._write_json(staging_dir / "metrics.json", metrics_payload)
            normalized_metrics_bytes = (staging_dir / "metrics.json").read_bytes()
            normalized_metrics_sha256 = hashlib.sha256(normalized_metrics_bytes).hexdigest()

            m_url = metrics_source_url or metrics_payload.get("source_url")
            if not m_url or not str(m_url).strip():
                raise ValueError("Authoritative fund metrics source URL is missing; synthetic defaults are prohibited.")

            metrics_metadata = {
                "source_url": str(m_url).strip(),
                "source_document_sha256": metrics_source_sha256,
                "reviewer_attested": reviewer_attested,
                "effective_date": as_of.isoformat(),
                "source_type": "OFFICIAL_FUND_METRICS",
                "normalized_metrics_sha256": normalized_metrics_sha256,
            }
            self._write_json(staging_dir / "metrics_metadata.json", metrics_metadata)

            # 3. Direct plan evidence documents
            for scheme_id, raw_pdf in direct_plan_evidence_bytes.items():
                if not isinstance(raw_pdf, bytes) or not raw_pdf.startswith(b"%PDF-"):
                    raise ValueError(f"Direct plan evidence for scheme {scheme_id} must be genuine PDF bytes.")
                rel_path = f"originals/direct/{scheme_id}.pdf"
                self._write_bytes(staging_dir / rel_path, raw_pdf)

            # 4. Candidate Universe & Metadata
            if not candidate_universe:
                raise ValueError("Candidate universe cannot be empty.")
            candidates_for_bundle: List[Dict[str, Any]] = []
            for cand in candidate_universe:
                cand_copy = dict(cand)
                scheme_id = cand_copy["scheme_id"]
                cand_copy.pop("_evidence_root", None)

                if scheme_id not in direct_plan_evidence_bytes:
                    raise ValueError(f"Missing direct plan evidence bytes for candidate scheme {scheme_id}; synthetic defaults are prohibited.")
                direct_bytes = direct_plan_evidence_bytes[scheme_id]
                if not isinstance(direct_bytes, bytes) or not direct_bytes.startswith(b"%PDF-"):
                    raise ValueError(f"Direct plan evidence for scheme {scheme_id} must be genuine PDF bytes.")

                direct_evidence = dict(cand_copy.get("direct_plan_evidence", {}))
                rel_direct_file = f"originals/direct/{scheme_id}.pdf"
                direct_url = direct_evidence.get("source_url") or cand_copy.get("direct_plan_evidence_source_url")
                if not direct_url or not str(direct_url).strip():
                    raise ValueError(f"Missing direct plan evidence source URL for candidate scheme {scheme_id}; synthetic defaults are prohibited.")

                direct_evidence.update({
                    "source_file": rel_direct_file,
                    "source_document_sha256": hashlib.sha256(direct_bytes).hexdigest(),
                    "source_url": str(direct_url).strip(),
                    "source_type": "AMC_FACTSHEET",
                    "reviewer_attested": reviewer_attested,
                    "plan": "Direct",
                    "scheme_name": cand_copy["fund_name"],
                    "scheme_id": scheme_id,
                    "isin": cand_copy["isin"],
                    "amc_name": cand_copy["amc_name"],
                    "reviewed_at": as_of.isoformat(),
                })
                cand_copy["direct_plan_evidence"] = direct_evidence
                candidates_for_bundle.append(cand_copy)

            self._write_json(staging_dir / "candidates.json", candidates_for_bundle)
            normalized_candidates_bytes = (staging_dir / "candidates.json").read_bytes()
            normalized_candidates_sha256 = hashlib.sha256(normalized_candidates_bytes).hexdigest()

            universe_rel_source = "originals/universe.json"
            self._write_bytes(staging_dir / universe_rel_source, candidate_universe_source_bytes)
            universe_source_sha256 = hashlib.sha256(candidate_universe_source_bytes).hexdigest()

            if not universe_source_url or not str(universe_source_url).strip():
                raise ValueError("Candidate universe source URL is missing; synthetic defaults are prohibited.")

            candidate_metadata = {
                "source_url": str(universe_source_url).strip(),
                "source_document_sha256": universe_source_sha256,
                "reviewer_attested": reviewer_attested,
                "effective_date": as_of.isoformat(),
                "source_type": "REVIEWED_CANDIDATE_UNIVERSE",
                "universe_complete": True,
                "coverage_scope": "All reviewed direct equity schemes",
                "normalized_candidate_universe_sha256": normalized_candidates_sha256,
            }
            self._write_json(staging_dir / "candidate_metadata.json", candidate_metadata)

            # 5. Portfolio Disclosures
            manifest_disclosures: Dict[str, Dict[str, str]] = {}
            for scheme_id, disclosure_dict in portfolio_disclosures.items():
                disc_rel_source = f"originals/disclosures/{scheme_id}.json"
                raw_disc_bytes = portfolio_disclosure_source_bytes.get(scheme_id)
                if not raw_disc_bytes or not isinstance(raw_disc_bytes, bytes) or not raw_disc_bytes.strip():
                    raise ValueError(f"Missing original portfolio disclosure source bytes for scheme {scheme_id}; synthetic defaults are prohibited.")
                self._write_bytes(staging_dir / disc_rel_source, raw_disc_bytes)
                disc_source_sha256 = hashlib.sha256(raw_disc_bytes).hexdigest()

                normalized_disc = dict(disclosure_dict)
                disc_url = normalized_disc.get("source_url")
                if not disc_url or not str(disc_url).strip():
                    raise ValueError(f"Missing portfolio disclosure source URL for scheme {scheme_id}; synthetic defaults are prohibited.")

                normalized_disc["source_url"] = str(disc_url).strip()
                normalized_disc["source_document_sha256"] = disc_source_sha256
                normalized_disc["reviewer_attested"] = reviewer_attested
                normalized_disc["effective_date"] = as_of.isoformat()
                normalized_disc["source_type"] = "AMC_PORTFOLIO_DISCLOSURE"
                normalized_disc["scheme_id"] = scheme_id

                record_rel_path = f"disclosures/{scheme_id}.json"
                self._write_json(staging_dir / record_rel_path, normalized_disc)

                manifest_disclosures[scheme_id] = {
                    "record_file": record_rel_path,
                    "source_file": disc_rel_source,
                }

            # 6. Aliases (optional)
            aliases_file_manifest: Optional[str] = None
            if aliases_payload is not None:
                aliases_file_manifest = "aliases.json"
                self._write_json(staging_dir / "aliases.json", aliases_payload)
                if aliases_source_bytes is not None:
                    self._write_bytes(staging_dir / "originals/aliases.json", aliases_source_bytes)

            # Optional reviewer verification files
            reviewer_envelope_manifest: Optional[str] = None
            reviewer_registry_manifest: Optional[str] = None
            if reviewer_approval_envelope is not None:
                reviewer_envelope_manifest = "reviewer_approval_envelope.json"
                reviewer_registry_manifest = "reviewer_trust_registry.json"
                self._write_json(staging_dir / reviewer_envelope_manifest, reviewer_approval_envelope)
                self._write_json(staging_dir / reviewer_registry_manifest, reviewer_trust_registry)

            # 7. Manifest (Schema Version 1)
            manifest = {
                "schema_version": 1,
                "disclosure_as_of_date": as_of.isoformat(),
                "metrics_file": "metrics.json",
                "metrics_metadata_file": "metrics_metadata.json",
                "metrics_source_file": metrics_rel_source,
                "scheme_master_file": "scheme_master.json",
                "scheme_master_source_file": master_rel_source,
                "portfolio_disclosures": manifest_disclosures,
                "candidate_universe_file": "candidates.json",
                "candidate_universe_metadata_file": "candidate_metadata.json",
                "candidate_universe_source_file": universe_rel_source,
                "aliases_file": aliases_file_manifest,
            }
            if reviewer_envelope_manifest and reviewer_registry_manifest:
                manifest["reviewer_approval_envelope_file"] = reviewer_envelope_manifest
                manifest["reviewer_trust_registry_file"] = reviewer_registry_manifest

            # Resolve and enforce mandatory non-empty commit_sha and policy_digest in manifest
            commit_for_manifest = expected_commit_sha
            if not commit_for_manifest and isinstance(reviewer_approval_envelope, dict):
                commit_for_manifest = reviewer_approval_envelope.get("payload", {}).get("commit_sha")
            if not commit_for_manifest or not str(commit_for_manifest).strip():
                raise ValueError("Promotion requires a non-empty 'commit_sha' binding in the manifest.")

            policy_for_manifest = expected_policy_digest
            if not policy_for_manifest and isinstance(reviewer_approval_envelope, dict):
                policy_for_manifest = (
                    reviewer_approval_envelope.get("payload", {}).get("policy_digest")
                    or reviewer_approval_envelope.get("payload", {}).get("policy_sha256")
                )
            if not policy_for_manifest or not str(policy_for_manifest).strip():
                raise ValueError("Promotion requires a non-empty 'policy_digest' binding in the manifest.")

            manifest["commit_sha"] = str(commit_for_manifest).strip()
            manifest["policy_digest"] = str(policy_for_manifest).strip()

            self._write_json(staging_dir / "manifest.json", manifest)

            # 8. Pre-promotion Verification
            provider = build_sip_evidence_provider(staging_dir)
            if provider is None:
                raise ValueError("Pre-promotion validation failed: provider could not be built from staging bundle.")

            bundle_files = sorted([
                p for p in staging_dir.rglob("*")
                if p.is_file() and p.name not in ("reviewer_approval_envelope.json", "reviewer_trust_registry.json")
            ])
            hasher = hashlib.sha256()
            for bf in bundle_files:
                rel = str(bf.relative_to(staging_dir)).replace("\\", "/")
                hasher.update(rel.encode("utf-8"))
                hasher.update(bf.read_bytes())
            staging_bundle_digest = hasher.hexdigest()

            actual_envelope = (
                reviewer_approval_envelope(staging_bundle_digest)
                if callable(reviewer_approval_envelope)
                else reviewer_approval_envelope
            )

            # Ensure envelope and registry are written into staging
            self._write_json(staging_dir / "reviewer_approval_envelope.json", actual_envelope)
            self._write_json(staging_dir / "reviewer_trust_registry.json", reviewer_trust_registry)

            post_res = verify_sip_reviewer_approval(
                envelope=actual_envelope,
                trust_registry=reviewer_trust_registry,
                expected_scope="SIP_EVIDENCE_RELEASE",
                expected_commit_sha=expected_commit_sha,
                expected_policy_digest=expected_policy_digest,
                expected_artifact_digest=staging_bundle_digest,
                require_commit_binding=True,
                require_policy_binding=True,
                require_artifact_binding=True,
            )
            if not post_res.ok:
                raise ValueError(f"Staging artifact digest verification failed before promotion: {'; '.join(post_res.errors)}")

        except Exception as exc:
            # Staging failure: clean up staging directory and raise
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise ValueError(f"Evidence bundle staging failed: {exc}") from exc

        # 9. Atomic Promotion with Rollback
        backup_dir: Optional[Path] = None
        if self.target_dir.exists():
            backup_dir = self.target_dir.parent / f".backup_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            self.target_dir.rename(backup_dir)

        try:
            staging_dir.rename(self.target_dir)
            if backup_dir and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
        except Exception as exc:
            # Rollback to backup if promotion failed
            if backup_dir and backup_dir.exists() and not self.target_dir.exists():
                backup_dir.rename(self.target_dir)
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise IOError(f"Atomic promotion failed; restored prior bundle state: {exc}") from exc

        return self.target_dir

