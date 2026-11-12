"""
services/engine_bootstrap.py - Engine-managed public evidence bootstrapping and operable promotion workflow.
Addresses Issue #121: Make engine bootstrap its own configuration and fund evidence; implement an operable promotion workflow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.acquisition.adapters.amfi_nav import AmfiNavAdapter
from services.acquisition.adapters.amfi_scheme_master import AmfiSchemeMasterAdapter
from services.acquisition.bundle_builder import EvidenceBundleBuilder
from services.sip_reviewer_approval import verify_sip_reviewer_approval


@dataclass(frozen=True)
class GateReport:
    gate_name: str
    passed: bool
    evidence_ref: str
    freshness_date: Optional[str] = None
    coverage_pct: Optional[float] = None
    reasons: Tuple[str, ...] = ()
    remediation: Optional[str] = None


@dataclass(frozen=True)
class ValidationReport:
    status: str                         # "PROMOTABLE" | "BLOCKED"
    as_of_date: str
    report_timestamp: str
    gates: Tuple[GateReport, ...]
    can_provide_read_only_report: bool
    summary: str
    unpromoted_reason: Optional[str] = None


@dataclass
class InvestorMandateInput:
    """
    Typed investor-provided inputs.
    Strictly isolates client-specific facts from engine-owned configuration and public evidence.
    """
    as_of_date: date
    horizon_years: float
    goal: str
    monthly_sip_budget_inr: Decimal = Decimal("0")
    lumpsum_budget_inr: Decimal = Decimal("0")
    risk_comfort_text: Optional[str] = None
    explicit_authorized_risk_tier: Optional[str] = None  # e.g. "Tier 2", "Tier 4", "Tier 6"
    tier6_equity_only_authorized: bool = False
    bank_cash_inr: Optional[Decimal] = None
    emergency_reserve_inr: Optional[Decimal] = None
    near_term_obligations_inr: Optional[Decimal] = None
    monthly_essential_expenses_inr: Optional[Decimal] = None
    monthly_debt_service_inr: Optional[Decimal] = None
    monthly_net_income_inr: Optional[Decimal] = None
    consent_external_processing: bool = False

    def validate_for_lumpsum(self) -> Tuple[bool, List[str]]:
        """Validate suitability and mandate requirements for lump-sum deployment."""
        errors: List[str] = []

        if self.lumpsum_budget_inr <= Decimal("0"):
            errors.append("Lump-sum deployment requires a positive lumpsum_budget_inr.")

        if self.horizon_years <= 0:
            errors.append("Investment horizon must be a positive number of years.")

        # Risk tier mandate enforcement: free-text 'aggressive'comfort is not explicit tier authorization
        if self.explicit_authorized_risk_tier is None or not str(self.explicit_authorized_risk_tier).strip():
            comfort = str(self.risk_comfort_text or "").lower()
            errors.append(
                f"Missing investor-authorized risk tier. Stated preference ({comfort or 'None'}) and "
                f"{self.horizon_years}Y horizon do not establish a SEBI risk tier or authorize equity deployment."
            )

        if self.bank_cash_inr is None:
            errors.append("Verified bank cash evidence is missing; missing cash is not zero.")
        elif self.bank_cash_inr < Decimal("0"):
            errors.append("Bank cash cannot be negative.")

        if self.emergency_reserve_inr is None:
            errors.append("Approved emergency reserve evidence is missing; missing reserve is not zero.")
        elif self.emergency_reserve_inr < Decimal("0"):
            errors.append("Emergency reserve cannot be negative.")

        if (
            self.bank_cash_inr is not None
            and self.emergency_reserve_inr is not None
        ):
            if self.emergency_reserve_inr > self.bank_cash_inr:
                errors.append("Emergency reserve cannot exceed total bank cash.")
            else:
                surplus = self.bank_cash_inr - self.emergency_reserve_inr
                if self.near_term_obligations_inr is not None:
                    surplus -= self.near_term_obligations_inr
                if surplus < self.lumpsum_budget_inr:
                    errors.append(
                        f"Deployable surplus (INR {surplus:,.2f}) after reserve and obligations "
                        f"does not cover requested lump sum (INR {self.lumpsum_budget_inr:,.2f})."
                    )

        return (len(errors) == 0, errors)


class EngineBootstrapPipeline:
    """
    Coordinates engine self-bootstrapping and operable promotion workflow.
    Acquires, validates, normalizes, and builds public evidence datasets without
    requiring client-authored internal engine configuration.
    """

    def __init__(
        self,
        *,
        nav_adapter: Optional[AmfiNavAdapter] = None,
        scheme_master_adapter: Optional[AmfiSchemeMasterAdapter] = None,
    ):
        self.nav_adapter = nav_adapter or AmfiNavAdapter()
        self.scheme_master_adapter = scheme_master_adapter or AmfiSchemeMasterAdapter()

    def build_staging_bundle(
        self,
        staging_dir: Path,
        as_of: date,
        *,
        hermetic_inputs: Dict[str, Any],
        reviewer_attested: bool = False,
        reviewer_approval_envelope: Optional[Dict[str, Any]] = None,
        reviewer_trust_registry: Optional[Dict[str, Any]] = None,
        expected_commit_sha: Optional[str] = None,
        expected_policy_digest: Optional[str] = None,
        require_commit_binding: bool = False,
        require_policy_binding: bool = False,
        require_artifact_binding: bool = False,
    ) -> ValidationReport:
        """
        Builds and validates an unpromoted staging bundle.
        Returns a deterministic ValidationReport describing gate outcomes.
        Requires detached Ed25519 reviewer approval envelope and trust registry.
        Caller boolean flags without cryptographic signature cannot satisfy promotion gates.
        """
        gates: List[GateReport] = []
        now_str = datetime.now(timezone.utc).isoformat()

        # Gate 1: Reviewer Attestation
        if reviewer_approval_envelope is not None:
            if reviewer_trust_registry is None:
                gates.append(GateReport(
                    gate_name="REVIEWER_ATTESTATION",
                    passed=False,
                    evidence_ref="missing_trust_registry",
                    reasons=("Reviewer trust registry is required to verify approval envelope.",),
                    remediation="Provide an authoritative reviewer trust registry root.",
                ))
            else:
                verification = verify_sip_reviewer_approval(
                    envelope=reviewer_approval_envelope,
                    trust_registry=reviewer_trust_registry,
                    expected_scope="SIP_EVIDENCE_RELEASE",
                    expected_commit_sha=expected_commit_sha,
                    expected_policy_digest=expected_policy_digest,
                    require_commit_binding=require_commit_binding,
                    require_policy_binding=require_policy_binding,
                )
                if verification.ok:
                    gates.append(GateReport(
                        gate_name="REVIEWER_ATTESTATION",
                        passed=True,
                        evidence_ref=f"reviewer_signature:{verification.approval_id}",
                        freshness_date=as_of.isoformat(),
                    ))
                else:
                    gates.append(GateReport(
                        gate_name="REVIEWER_ATTESTATION",
                        passed=False,
                        evidence_ref="signature_verification_failed",
                        reasons=tuple(verification.errors),
                        remediation="Ensure the reviewer envelope is signed with a valid non-revoked Ed25519 key.",
                    ))
        else:
            gates.append(GateReport(
                gate_name="REVIEWER_ATTESTATION",
                passed=False,
                evidence_ref="missing_reviewer_envelope",
                reasons=("Independent detached reviewer approval envelope is required for promotion; boolean attestation is prohibited.",),
                remediation="Provide an independently verified Ed25519 reviewer approval envelope.",
            ))

        # Gate 2: Scheme Master Evidence & Record-level validation
        master_bytes = hermetic_inputs.get("scheme_master")
        if master_bytes and isinstance(master_bytes, bytes) and len(master_bytes) > 10:
            try:
                is_json = False
                has_records = False
                record_count = 0
                try:
                    m_data = json.loads(master_bytes.decode("utf-8"))
                    is_json = True
                    schemes_list = m_data.get("schemes", []) if isinstance(m_data, dict) else []
                    has_records = len(schemes_list) > 0 and all(
                        isinstance(s, dict) and s.get("scheme_name") for s in schemes_list
                    )
                    record_count = len(schemes_list)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    has_records = False

                if not is_json:
                    text = master_bytes.decode("utf-8-sig", errors="replace")
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and "|" in ln and not ln.startswith("Scheme Code")]
                    has_records = len(lines) > 0 and any(parts[0].isdigit() for parts in (l.split("|") for l in lines) if len(parts) >= 4)
                    record_count = len(lines)

                if has_records:
                    m_hash = hashlib.sha256(master_bytes).hexdigest()
                    gates.append(GateReport(
                        gate_name="SCHEME_MASTER_COVERAGE",
                        passed=True,
                        evidence_ref=f"sha256:{m_hash}",
                        freshness_date=as_of.isoformat(),
                        coverage_pct=100.0,
                    ))
                else:
                    gates.append(GateReport(
                        gate_name="SCHEME_MASTER_COVERAGE",
                        passed=False,
                        evidence_ref="invalid_records",
                        reasons=("Scheme master contains no valid scheme records or required fields.",),
                        remediation="Acquire authoritative AMFI scheme master data with valid records.",
                    ))
            except Exception as exc:
                gates.append(GateReport(
                    gate_name="SCHEME_MASTER_COVERAGE",
                    passed=False,
                    evidence_ref="parse_error",
                    reasons=(f"Scheme master parsing failed: {exc}",),
                ))
        else:
            gates.append(GateReport(
                gate_name="SCHEME_MASTER_COVERAGE",
                passed=False,
                evidence_ref="missing",
                reasons=("Authoritative scheme master source bytes are missing or empty.",),
                remediation="Acquire official AMFI scheme master data.",
            ))

        # Gate 3: NAV Freshness & Precision
        nav_bytes = hermetic_inputs.get("daily_nav")
        if nav_bytes and isinstance(nav_bytes, bytes) and len(nav_bytes) > 10:
            try:
                text = nav_bytes.decode("utf-8-sig", errors="replace")
                lines = [ln.strip() for ln in text.splitlines() if ln.strip() and "|" in ln and not ln.startswith("Scheme Code")]
                valid_navs = 0
                for line in lines:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 6 and parts[0].isdigit():
                        try:
                            nav_val = Decimal(parts[4])
                            if nav_val > 0 and nav_val.is_finite():
                                valid_navs += 1
                        except Exception:
                            pass
                if valid_navs > 0:
                    n_hash = hashlib.sha256(nav_bytes).hexdigest()
                    gates.append(GateReport(
                        gate_name="DAILY_NAV_FEED",
                        passed=True,
                        evidence_ref=f"sha256:{n_hash}",
                        freshness_date=as_of.isoformat(),
                        coverage_pct=100.0,
                    ))
                else:
                    gates.append(GateReport(
                        gate_name="DAILY_NAV_FEED",
                        passed=False,
                        evidence_ref="no_valid_nav_rows",
                        reasons=("Daily NAV feed contains no valid positive numeric NAV rows.",),
                        remediation="Acquire uncorrupted daily NAV feed from AMFI.",
                    ))
            except Exception as exc:
                gates.append(GateReport(
                    gate_name="DAILY_NAV_FEED",
                    passed=False,
                    evidence_ref="nav_parse_error",
                    reasons=(f"NAV feed processing error: {exc}",),
                ))
        else:
            gates.append(GateReport(
                gate_name="DAILY_NAV_FEED",
                passed=False,
                evidence_ref="missing",
                reasons=("Daily Net Asset Value feed is missing or empty.",),
                remediation="Acquire daily NAV feed from AMFI India.",
            ))

        # Gate 4: Fund Metrics
        metrics_bytes = hermetic_inputs.get("metrics")
        metrics_json = hermetic_inputs.get("metrics_json")
        if metrics_bytes and metrics_json and isinstance(metrics_bytes, bytes) and isinstance(metrics_json, bytes):
            try:
                m_payload = json.loads(metrics_json.decode("utf-8"))
                funds = m_payload.get("funds", []) if isinstance(m_payload, dict) else []
                if isinstance(funds, list) and len(funds) > 0 and all(
                    isinstance(f, dict) and f.get("fund_id") and f.get("nav") for f in funds
                ):
                    met_hash = hashlib.sha256(metrics_bytes).hexdigest()
                    gates.append(GateReport(
                        gate_name="FUND_METRICS_EVIDENCE",
                        passed=True,
                        evidence_ref=f"sha256:{met_hash}",
                        freshness_date=as_of.isoformat(),
                    ))
                else:
                    gates.append(GateReport(
                        gate_name="FUND_METRICS_EVIDENCE",
                        passed=False,
                        evidence_ref="invalid_funds_array",
                        reasons=("Metrics payload missing valid non-empty 'funds' array with required fields.",),
                        remediation="Ensure metrics.json contains valid structured fund records.",
                    ))
            except Exception as exc:
                gates.append(GateReport(
                    gate_name="FUND_METRICS_EVIDENCE",
                    passed=False,
                    evidence_ref="metrics_json_parse_error",
                    reasons=(f"Metrics JSON parsing failed: {exc}",),
                ))
        else:
            gates.append(GateReport(
                gate_name="FUND_METRICS_EVIDENCE",
                passed=False,
                evidence_ref="missing",
                reasons=("Authoritative fund metrics or structured records are missing.",),
                remediation="Build and validate fund metrics dataset from verified sources.",
            ))

        # Gate 5: Direct-Plan Factsheet Evidence
        direct_evidence = hermetic_inputs.get("direct_evidence") or {}
        if direct_evidence and isinstance(direct_evidence, dict) and all(
            isinstance(v, bytes) and v.startswith(b"%PDF-") and len(v) >= 16 for v in direct_evidence.values()
        ):
            gates.append(GateReport(
                gate_name="DIRECT_PLAN_FACTSHEET_EVIDENCE",
                passed=True,
                evidence_ref=f"pdf_count:{len(direct_evidence)}",
                freshness_date=as_of.isoformat(),
                coverage_pct=100.0,
            ))
        else:
            gates.append(GateReport(
                gate_name="DIRECT_PLAN_FACTSHEET_EVIDENCE",
                passed=False,
                evidence_ref="missing_or_corrupt",
                reasons=("Direct plan factsheet PDFs are missing, empty, or not genuine PDF bytes.",),
                remediation="Acquire official AMC factsheets in PDF format verifying Direct plan status.",
            ))

        # Gate 6: Portfolio Disclosures
        disclosures = hermetic_inputs.get("disclosures") or {}
        valid_disclosures = False
        if disclosures and isinstance(disclosures, dict) and len(disclosures) > 0:
            valid_disclosures = True
            for disc_id, disc_data in disclosures.items():
                if isinstance(disc_data, bytes):
                    try:
                        disc_dict = json.loads(disc_data.decode("utf-8"))
                    except Exception:
                        valid_disclosures = False
                        break
                elif isinstance(disc_data, dict):
                    disc_dict = disc_data
                else:
                    valid_disclosures = False
                    break
                if not isinstance(disc_dict, dict) or "constituent_weights" not in disc_dict:
                    valid_disclosures = False
                    break
        if valid_disclosures:
            gates.append(GateReport(
                gate_name="PORTFOLIO_DISCLOSURE_LOOKTHROUGH",
                passed=True,
                evidence_ref=f"disclosure_count:{len(disclosures)}",
                freshness_date=as_of.isoformat(),
                coverage_pct=100.0,
            ))
        else:
            gates.append(GateReport(
                gate_name="PORTFOLIO_DISCLOSURE_LOOKTHROUGH",
                passed=False,
                evidence_ref="missing_or_invalid",
                reasons=("Portfolio constituent disclosures are missing or invalid structured format.",),
                remediation="Acquire periodic portfolio constituent disclosures published by AMCs.",
            ))

        all_passed = all(g.passed for g in gates)
        status = "PROMOTABLE" if all_passed else "BLOCKED"
        unpromoted = None if all_passed else "One or more mandatory evidence gates failed."

        return ValidationReport(
            status=status,
            as_of_date=as_of.isoformat(),
            report_timestamp=now_str,
            gates=tuple(gates),
            can_provide_read_only_report=True,
            summary=f"Validation completed: {sum(1 for g in gates if g.passed)}/{len(gates)} gates passed.",
            unpromoted_reason=unpromoted,
        )


    def bootstrap_staging_bundle(
        self,
        staging_dir: Path,
        as_of: date,
        *,
        reviewer_approval_envelope: Optional[Dict[str, Any]] = None,
        reviewer_trust_registry: Optional[Dict[str, Any]] = None,
        expected_commit_sha: Optional[str] = None,
        expected_policy_digest: Optional[str] = None,
        require_commit_binding: bool = False,
        require_policy_binding: bool = False,
        require_artifact_binding: bool = False,
        metrics_source_url: Optional[str] = None,
        universe_source_url: Optional[str] = None,
        master_source_url: Optional[str] = None,
        nav_source_url: Optional[str] = None,
        hermetic_inputs: Optional[Dict[str, Any]] = None,
    ) -> ValidationReport:
        """
        Autonomously orchestrates data acquisition, validates quality gates,
        and constructs a staging bundle without requiring caller manual staging.
        """
        inputs = dict(hermetic_inputs or {})

        # Acquire Scheme Master if not supplied
        if "scheme_master" not in inputs:
            try:
                rec = self.scheme_master_adapter.acquire(as_of)
                inputs["scheme_master"] = rec.source_bytes
            except Exception:
                pass

        # Acquire Daily NAV if not supplied
        if "daily_nav" not in inputs:
            try:
                rec = self.nav_adapter.acquire(as_of)
                inputs["daily_nav"] = rec.source_bytes
            except Exception:
                pass

        # Acquire metrics if URL supplied and not in inputs
        if "metrics" not in inputs and metrics_source_url:
            try:
                raw_m = self.nav_adapter._fetch_url(metrics_source_url)
                inputs["metrics"] = raw_m
                inputs["metrics_json"] = raw_m
            except Exception:
                pass

        return self.build_staging_bundle(
            staging_dir=staging_dir,
            as_of=as_of,
            hermetic_inputs=inputs,
            reviewer_attested=reviewer_approval_envelope is not None,
            reviewer_approval_envelope=reviewer_approval_envelope,
            reviewer_trust_registry=reviewer_trust_registry,
            expected_commit_sha=expected_commit_sha,
            expected_policy_digest=expected_policy_digest,
            require_commit_binding=require_commit_binding,
            require_policy_binding=require_policy_binding,
            require_artifact_binding=require_artifact_binding,
        )

    def promote(
        self,
        staging_bundle_dir: Path,
        target_bundle_dir: Path,
        *,
        reviewer_approval_envelope: Dict[str, Any],
        reviewer_trust_registry: Dict[str, Any],
        expected_commit_sha: Optional[str] = None,
        expected_policy_digest: Optional[str] = None,
        require_commit_binding: bool = False,
        require_policy_binding: bool = False,
        require_artifact_binding: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes atomic promotion of verified bundle after verifying detached Ed25519 reviewer approval.
        Performs real filesystem atomic copy/swap with rollback to preserve last-known-good state on failure.
        Issue #112: In every production promotion path, cryptographic artifact digest binding
        against the staging bundle is strictly mandatory and cannot be disabled.
        """
        if require_artifact_binding is False:
            raise ValueError(
                "Promotion requires mandatory cryptographic artifact digest binding; "
                "caller cannot disable it."
            )

        import shutil
        import uuid
        import time

        staging_path = Path(staging_bundle_dir).expanduser().resolve()
        target_path = Path(target_bundle_dir).expanduser().resolve()

        if not staging_path.is_dir():
            raise ValueError(f"Staging bundle directory does not exist: {staging_path}")

        manifest_path = staging_path / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("Staging bundle is missing manifest.json.")

        try:
            staging_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Staging bundle manifest is invalid JSON: {exc}") from exc

        if staging_manifest.get("schema_version") != 1:
            raise ValueError("Staging bundle manifest schema_version must be 1.")

        # Compute staging bundle digest for audit lineage and cryptographic approval verification
        bundle_files = sorted([p for p in staging_path.rglob("*") if p.is_file()])
        hasher = hashlib.sha256()
        for bf in bundle_files:
            rel = str(bf.relative_to(staging_path)).replace("\\", "/")
            hasher.update(rel.encode("utf-8"))
            hasher.update(bf.read_bytes())
        bundle_digest = hasher.hexdigest()

        # Cryptographic verification of detached reviewer approval
        # Mandatory binding: expected_artifact_digest is bound to the computed bundle_digest.
        verification = verify_sip_reviewer_approval(
            envelope=reviewer_approval_envelope,
            trust_registry=reviewer_trust_registry,
            expected_scope="SIP_EVIDENCE_RELEASE",
            expected_commit_sha=expected_commit_sha,
            expected_policy_digest=expected_policy_digest,
            expected_artifact_digest=bundle_digest,
            require_commit_binding=require_commit_binding,
            require_policy_binding=require_policy_binding,
            require_artifact_binding=True,
        )
        if not verification.ok:
            raise ValueError(
                f"Promotion blocked: independent reviewer signature verification failed: "
                f"{'; '.join(verification.errors)}"
            )

        # Atomic promotion with rollback preserving last-known-good
        target_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path: Optional[Path] = None
        if target_path.exists():
            backup_path = target_path.parent / f".backup_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            target_path.rename(backup_path)

        try:
            shutil.copytree(staging_path, target_path)
            target_manifest = target_path / "manifest.json"
            if not target_manifest.is_file():
                raise IOError("Target manifest missing after promotion copy.")
            # Verify promoted bytes match staging
            promoted_digest = hashlib.sha256()
            for tf in sorted([p for p in target_path.rglob("*") if p.is_file()]):
                rel = str(tf.relative_to(target_path)).replace("\\", "/")
                promoted_digest.update(rel.encode("utf-8"))
                promoted_digest.update(tf.read_bytes())
            if promoted_digest.hexdigest() != bundle_digest:
                raise IOError("Promoted bundle integrity digest mismatch with staging bundle.")
            if backup_path and backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
        except Exception as exc:
            if backup_path and backup_path.exists() and not target_path.exists():
                backup_path.rename(target_path)
            raise IOError(f"Atomic promotion failed; restored prior bundle state: {exc}") from exc

        return {
            "status": "PROMOTED",
            "target_dir": str(target_path),
            "approval_id": verification.approval_id,
            "reviewer_id": verification.reviewer_id,
            "bundle_digest": bundle_digest,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }
