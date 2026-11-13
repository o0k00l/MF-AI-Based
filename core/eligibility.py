"""
core/eligibility.py — Module 4: Hard Binary Selection Gates & NO ACTION Engine.
Implements the 10 Binary Fiduciary Gates and the Mandatory NO ACTION decision branch.
"""
from __future__ import annotations
import os
import math
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import date, datetime
from core.models import EligibilityGateResult, NOActionResult, RiskTier


def _load_default_trust_registry() -> Optional[dict]:
    """Load the default SIP reviewer trust registry from environment.
    
    The trust registry is a JSON structure mapping reviewer_id -> public_key.
    Set SIP_REVIEWER_TRUST_REGISTRY_JSON as an env var containing the registry JSON.
    Returns None if not configured (falls back to hash-only verification).
    """
    env_val = os.environ.get("SIP_REVIEWER_TRUST_REGISTRY_JSON")
    if env_val is None:
        return None
    try:
        registry = json.loads(env_val)
        if isinstance(registry, dict) and "keys" in registry:
            return registry
        return None
    except (json.JSONDecodeError, TypeError):
        return None


# Module-level default trust registry (lazy-loaded)
_default_trust_registry: Optional[dict] = None


def _get_default_trust_registry() -> Optional[dict]:
    """Get or initialize the default trust registry (cached)."""
    global _default_trust_registry
    if _default_trust_registry is None:
        _default_trust_registry = _load_default_trust_registry()
    return _default_trust_registry


def _reviewed_direct_plan_evidence_status(
    fund_data: dict,
    *,
    as_of_date: Optional[date] = None,
    trust_registry: Optional[dict] = None,
) -> str:
    """Verify Direct-plan evidence with optional Ed25519 signature verification.
    
    Performs hash integrity + field validation. Signature verification is automatically
    enabled when both an envelope and a trust registry are present. In development
    or testing environments without a trust registry, falls back to hash-only verification.
    
    The trust registry can be loaded from the SIP_REVIEWER_TRUST_REGISTRY_JSON
    environment variable. In production, set this to enable cryptographic verification.
    
    Returns one of:
        MISSING_AS_OF_DATE, MISSING, INVALID, STALE,
        SIGNATURE_MISSING, TRUST_REGISTRY_MISSING, SIGNATURE_INVALID,
        REVIEWER_ATTESTED_HASH_MATCH
    """
    import hashlib
    import re
    from datetime import date, datetime

    target_as_of = as_of_date
    if target_as_of is None and isinstance(fund_data, dict):
        raw_as_of = (
            fund_data.get("as_of_date")
            or fund_data.get("decision_as_of_date")
            or fund_data.get("disclosure_as_of_date")
        )
        if isinstance(raw_as_of, date) and not isinstance(raw_as_of, datetime):
            target_as_of = raw_as_of
        elif isinstance(raw_as_of, str) and raw_as_of.strip():
            try:
                target_as_of = date.fromisoformat(raw_as_of.strip())
            except ValueError:
                return "INVALID"
    elif isinstance(target_as_of, str) and target_as_of.strip():
        # Also parse string as_of_date when passed directly as parameter
        try:
            target_as_of = date.fromisoformat(target_as_of.strip())
        except ValueError:
            return "INVALID"
    if target_as_of is None or not isinstance(target_as_of, date) or isinstance(target_as_of, datetime):
        return "MISSING_AS_OF_DATE"

    evidence = fund_data.get("direct_plan_evidence")
    evidence_root_value = fund_data.get("_evidence_root")
    if not isinstance(evidence, dict) or not evidence_root_value:
        return "MISSING"
    try:
        root = Path(evidence_root_value).expanduser().resolve()
        relative_source = evidence.get("source_file")
        if not isinstance(relative_source, str) or not relative_source.strip():
            return "MISSING"
        relative_path = Path(relative_source)
        if relative_path.is_absolute():
            return "INVALID"
        source_path = (root / relative_path).resolve()
        source_path.relative_to(root)
        if not source_path.is_file():
            return "MISSING"
        actual_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except (OSError, ValueError, RuntimeError):
        return "INVALID"

    declared_sha = evidence.get("source_document_sha256")
    source_url = evidence.get("source_url")
    source_type = evidence.get("source_type")
    reviewed_at_raw = evidence.get("reviewed_at")
    scheme_name = fund_data.get("fund_name") or fund_data.get("name")
    if (
        not isinstance(declared_sha, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha)
        or actual_sha.lower() != declared_sha.lower()
        or not isinstance(source_url, str)
        or not re.fullmatch(r"https://\S+", source_url)
        or source_type not in {"AMC_FACTSHEET", "AMFI_SCHEME_MASTER", "REGISTRAR_SCHEME_MASTER"}
        or evidence.get("reviewer_attested") is not True
        or evidence.get("plan") != "Direct"
        or evidence.get("scheme_name") != scheme_name
        # Bind plan evidence to the exact scheme identity, not a display name.
        or not isinstance(fund_data.get("scheme_id"), str)
        or not fund_data.get("scheme_id", "").strip()
        or evidence.get("scheme_id") != fund_data.get("scheme_id")
        or not isinstance(fund_data.get("isin"), str)
        or not fund_data.get("isin", "").strip()
        or evidence.get("isin") != fund_data.get("isin")
        or not isinstance(fund_data.get("amc_name"), str)
        or not fund_data.get("amc_name", "").strip()
        or evidence.get("amc_name") != fund_data.get("amc_name")
        or not isinstance(reviewed_at_raw, str)
    ):
        return "INVALID"
    try:
        reviewed_at = date.fromisoformat(reviewed_at_raw)
    except ValueError:
        return "INVALID"
    age_days = (target_as_of - reviewed_at).days
    if age_days < 0 or age_days > 180:
        return "STALE"

    envelope = evidence.get("reviewer_approval_envelope")
    # Signature verification path: triggered when envelope present OR trust_registry provided
    # Behavior:
    #   - envelope + trust_registry → verify signature (secure)
    #   - envelope + no trust_registry → TRUST_REGISTRY_MISSING (config error)
    #   - no envelope + trust_registry → SIGNATURE_MISSING (signature expected)
    #   - no envelope + no trust_registry → fall through to hash-only (dev mode)
    if envelope is not None:
        if trust_registry is None:
            return "TRUST_REGISTRY_MISSING"
        from services.sip_reviewer_approval import verify_sip_reviewer_approval
        plan_records = {
            "scheme_id": fund_data.get("scheme_id"),
            "isin": fund_data.get("isin"),
            "plan": "Direct",
            "amc_name": fund_data.get("amc_name"),
        }
        res = verify_sip_reviewer_approval(
            envelope,
            trust_registry,
            expected_scope="SIP_DIRECT_PLAN_EVIDENCE",
            expected_source_sha256=actual_sha,
            structured_records=plan_records,
            expected_scheme_id=fund_data.get("scheme_id"),
        )
        if not res.ok:
            return "SIGNATURE_INVALID"
        return "REVIEWER_ATTESTED_HASH_MATCH"
    
    if trust_registry is not None and envelope is None:
        # Trust registry configured but no envelope in evidence - signature required
        return "SIGNATURE_MISSING"
    
    # No envelope, no trust registry → hash-only verification (dev/test mode)
    # In production with trust_registry configured, signature verification is mandatory.
    return "REVIEWER_ATTESTED_HASH_MATCH"



def _resolve_field(fund_data: dict, *names, default=None):
    """Resolve a field from either expanded or abbreviated names.
    
    Checks expanded names first, then abbreviated forms.
    Returns (value, source_name) or (default, None) if not found.
    """
    for name in names:
        if name in fund_data:
            return fund_data[name], name
    return default, None


def _require_field(fund_data: dict, gate: str, *names):
    """Require a field; append failure message if missing. Returns (value, is_missing)."""
    val, source = _resolve_field(fund_data, *names)
    if source is None:
        return None, True
    return val, False


def _risk_tier_to_int(tier: Any) -> int:
    """Parse a SEBI riskometer tier without ambiguous substring matching."""
    if isinstance(tier, bool):
        raise ValueError("Risk tier must be an integer from 1 to 6, not boolean")
    if isinstance(tier, int):
        if 1 <= tier <= 6:
            return tier
        raise ValueError(f"Risk tier out of range: {tier}")
    if isinstance(tier, RiskTier):
        if tier == RiskTier.CUSTOM:
            raise ValueError("RiskTier.CUSTOM requires an explicit custom suitability policy")
        mapping = {
            RiskTier.CONSERVATIVE: 2,
            RiskTier.MODERATE: 4,
            RiskTier.AGGRESSIVE: 6,
        }
        return mapping[tier]
    tier_str = str(tier).strip().lower()
    import re
    match = re.search(r"\btier\s*([1-6])\b", tier_str)
    if match:
        return int(match.group(1))
    # Match the most specific labels first.
    if "very high" in tier_str or "aggressive" in tier_str:
        return 6
    if "moderately high" in tier_str:
        return 4
    if tier_str in {"high", "5_high"} or tier_str.endswith("_high"):
        return 5
    if "low to moderate" in tier_str:
        return 2
    if tier_str in {"moderate", "risk_tier.moderate", "moderate risk"}:
        # The product's three-profile "Moderate" maps to its approved middle
        # profile (Tier 4). Literal SEBI Tier 3 remains expressible as "Tier 3".
        return 4
    if tier_str in {"low", "very low"}:
        return 1
    if tier_str in {"conservative", "preservation"}:
        return 2
    raise ValueError(f"Unrecognized risk tier: {tier!r}")


def _finite_number(value: Any, field: str) -> float:
    """Convert a required numeric input; reject booleans, blanks and non-finite values."""
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field} is missing or malformed")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result

def validate_fund_screening_policy(data: Any, policy_path: Optional[Path] = None) -> Dict[str, Any]:
    """Authoritatively validate a screening policy object.

    Validates schema identity ('fiduciary.screening_criteria.v1'), version presence,
    gate_thresholds mapping with all required numeric finite thresholds, rule uniqueness,
    and non-contradictory category rules. Computes or verifies _policy_digest.
    Fails closed if the policy object is invalid, incomplete, or tampered with.
    """
    if not isinstance(data, dict):
        raise ValueError("Screening policy root must be a JSON object (dict)")

    gt = data.get("gate_thresholds")
    if not isinstance(gt, dict):
        raise ValueError("Screening policy missing 'gate_thresholds' mapping")

    if data.get("_schema") != "fiduciary.screening_criteria.v1":
        raise ValueError("Screening policy schema must be fiduciary.screening_criteria.v1")

    if not isinstance(data.get("version"), str) or not data["version"].strip():
        raise ValueError("Screening policy must declare an authoritative version string")
    status = data.get("status")
    if not isinstance(status, str) or status.strip().lower() not in {"reviewed", "approved"}:
        raise ValueError("Screening policy status must be reviewed or approved")
    effective_date = data.get("as_of")
    if not isinstance(effective_date, str) or not effective_date.strip():
        raise ValueError("Screening policy must declare an effective as_of date")
    try:
        parsed_effective_date = date.fromisoformat(effective_date)
    except ValueError as exc:
        raise ValueError("Screening policy as_of must be a valid ISO-8601 date") from exc
    if parsed_effective_date > date.today():
        raise ValueError("Screening policy as_of date cannot be in the future")

    required_thresholds = {
        "amc_max_limit_pct", "min_aum_crore", "max_top10_concentration_pct",
        "max_sector_concentration_pct", "min_sharpe", "min_manager_tenure_years",
        "min_confidence_score", "max_overlap_candidate_pct"
    }
    missing_thresholds = required_thresholds - set(gt.keys())
    if missing_thresholds:
        raise ValueError(f"Screening policy gate_thresholds missing required keys: {sorted(missing_thresholds)}")
    for k in required_thresholds:
        v = gt[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or float(v) < 0:
            raise ValueError(f"Screening policy gate_thresholds[{k!r}] must be a finite non-negative number")
    for key in (
        "amc_max_limit_pct", "max_top10_concentration_pct",
        "max_sector_concentration_pct", "max_overlap_candidate_pct",
    ):
        if float(gt[key]) > 100:
            raise ValueError(f"Screening policy gate_thresholds[{key!r}] must be between 0 and 100")
    if float(gt["min_aum_crore"]) <= 0:
        raise ValueError("Screening policy gate_thresholds['min_aum_crore'] must be greater than zero")
    if float(gt["min_confidence_score"]) > 1:
        raise ValueError("Screening policy gate_thresholds['min_confidence_score'] must be between 0 and 1")

    seen_rule_ids = set()
    for rule_set_key in ("quarantine_rules", "reject_rules", "flag_rules"):
        rules = data.get(rule_set_key, [])
        if not isinstance(rules, list):
            raise ValueError(f"Screening policy rule set {rule_set_key!r} must be a list")
        for rule in rules:
            if isinstance(rule, dict) and "id" in rule:
                rid = rule["id"]
                if rid in seen_rule_ids:
                    raise ValueError(f"Duplicate screening rule ID detected: {rid!r}")
                seen_rule_ids.add(rid)

    cat_rules = data.get("category_rules")
    if not isinstance(cat_rules, dict):
        raise ValueError("Screening policy category_rules must be an object")
    thematic = cat_rules.get("thematic_sectoral_liquidation")
    if not isinstance(thematic, dict):
        raise ValueError("Screening policy thematic_sectoral_liquidation rule is required")
    if thematic.get("action") not in ("REVIEW_REQUIRED", "FLAG"):
        raise ValueError(
            f"Contradictory action {thematic.get('action')!r} in category_rules.thematic_sectoral_liquidation; "
            "must be REVIEW_REQUIRED per fiduciary non-automatic liquidation policy"
        )

    lookthrough_policy = data.get("portfolio_lookthrough_policy")
    if not isinstance(lookthrough_policy, dict) or set(lookthrough_policy) != {
        "required_coverage_pct", "constituent_weight_reconciliation_tolerance_pct", "note"
    }:
        raise ValueError("Screening policy portfolio_lookthrough_policy is missing or has an invalid schema")
    coverage = lookthrough_policy["required_coverage_pct"]
    weight_tolerance = lookthrough_policy["constituent_weight_reconciliation_tolerance_pct"]
    for key, value in (
        ("required_coverage_pct", coverage),
        ("constituent_weight_reconciliation_tolerance_pct", weight_tolerance),
    ):
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or float(value) < 0 or float(value) > 100
        ):
            raise ValueError(f"portfolio_lookthrough_policy[{key!r}] must be finite and between 0 and 100")
    if float(coverage) <= 0:
        raise ValueError("portfolio_lookthrough_policy.required_coverage_pct must be greater than zero")
    if not isinstance(lookthrough_policy["note"], str) or not lookthrough_policy["note"].strip():
        raise ValueError("portfolio_lookthrough_policy.note must explain the governed parameter")

    import hashlib
    import hmac

    # A digest supplied by a caller is a claim, not evidence. When this object
    # originated from a policy file, bind its contents back to those exact
    # source bytes. The loader records _policy_path so repeated validation of
    # the loaded object can perform the same check.
    declared_digest = data.get("_policy_digest")
    source_path = policy_path
    if source_path is None and "_policy_path" in data:
        recorded_path = data.get("_policy_path")
        if not isinstance(recorded_path, (str, Path)) or not str(recorded_path).strip():
            raise ValueError("Screening policy recorded source path is invalid")
        source_path = Path(recorded_path)

    runtime_fields = {"_policy_digest", "_policy_path"}
    policy_content = {key: value for key, value in data.items() if key not in runtime_fields}
    if source_path is not None:
        source_path = Path(source_path)
        if not source_path.is_file():
            raise ValueError(f"Screening policy source file is unavailable: {source_path}")
        try:
            source_bytes = source_path.read_bytes()
            source_policy = json.loads(source_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Screening policy source file cannot be verified") from exc
        if not isinstance(source_policy, dict):
            raise ValueError("Screening policy source file root must be a JSON object")
        source_content = {
            key: value for key, value in source_policy.items()
            if key not in runtime_fields
        }
        if policy_content != source_content:
            raise ValueError(
                "In-memory screening policy content does not match its authoritative source file"
            )
        expected_digest = hashlib.sha256(source_bytes).hexdigest()
    else:
        try:
            canonical_bytes = json.dumps(policy_content, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Screening policy cannot be canonically serialized for digest verification") from exc
        expected_digest = hashlib.sha256(canonical_bytes).hexdigest()

    if declared_digest is not None:
        if (
            not isinstance(declared_digest, str)
            or len(declared_digest) != 64
            or any(char not in "0123456789abcdef" for char in declared_digest)
            or not hmac.compare_digest(declared_digest, expected_digest)
        ):
            raise ValueError("Screening policy digest does not match its validated content")

    data["_policy_digest"] = expected_digest
    return data


def load_fund_screening_policy(policy_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load, validate and bind the central versioned fund-screening policy."""
    if policy_path is None:
        policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "fund_screening.json"
    if not isinstance(policy_path, Path):
        policy_path = Path(policy_path)
    if not policy_path.is_file():
        raise FileNotFoundError(f"Screening policy file not found: {policy_path}")

    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Screening policy file is invalid JSON: {policy_path}") from exc

    import hashlib
    validated = validate_fund_screening_policy(data, policy_path=policy_path)
    validated["_policy_digest"] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    validated["_policy_path"] = str(policy_path)
    return validated


def _load_category_aum_caps(policy: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """Load category AUM limits exclusively from the validated central policy.

    Missing, duplicate, malformed or incomplete policy is a release/configuration
    error. Never substitute hardcoded financial thresholds when policy evidence
    cannot be read.
    """
    if policy is None:
        policy = load_fund_screening_policy()
    if not isinstance(policy, dict):
        raise ValueError("Screening policy must be an object")

    rules = policy.get("flag_rules")
    if not isinstance(rules, list):
        raise ValueError("Screening policy flag_rules must be a list")
    matches = [
        rule for rule in rules
        if isinstance(rule, dict) and rule.get("id") == "AUM_OUT_OF_BAND"
    ]
    if len(matches) != 1:
        raise ValueError("Screening policy must contain exactly one AUM_OUT_OF_BAND rule")

    limits = matches[0].get("limits_crore")
    required_categories = {"Small Cap", "Mid Cap", "Flexi Cap", "Large Cap", "Multi Cap"}
    if not isinstance(limits, dict) or set(limits) != required_categories:
        raise ValueError("AUM_OUT_OF_BAND limits must define the complete approved category set")

    validated: Dict[str, float] = {}
    for category, raw_limit in limits.items():
        if isinstance(raw_limit, bool):
            raise ValueError(f"AUM limit for {category} must be a positive finite number")
        try:
            limit = float(raw_limit)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"AUM limit for {category} must be a positive finite number") from exc
        if not math.isfinite(limit) or limit <= 0:
            raise ValueError(f"AUM limit for {category} must be a positive finite number")
        validated[category] = limit
    return validated


class _DynamicCategoryAumCaps(dict):
    """Dynamic mapping proxy that resolves category AUM caps from the authoritative screening policy."""
    def _current(self) -> Dict[str, float]:
        return _load_category_aum_caps(load_fund_screening_policy())

    def __getitem__(self, key: str) -> float:
        return self._current()[key]

    def get(self, key: str, default=None):
        return self._current().get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._current()

    def __iter__(self):
        return iter(self._current())

    def __len__(self) -> int:
        return len(self._current())

    def keys(self):
        return self._current().keys()

    def values(self):
        return self._current().values()

    def items(self):
        return self._current().items()

CATEGORY_AUM_CAPS = _DynamicCategoryAumCaps()


def check_eligibility_gates(
    fund_data: Dict[str, Any],
    portfolio_holdings: Optional[List[Dict[str, Any]]] = None,
    client_risk_tier_num: Optional[int] = None,
    is_starter: bool = False,
    as_of_date: Optional[date] = None,
    policy: Optional[Dict[str, Any]] = None,
    amc_max_limit_pct: Optional[float] = None,
    min_aum_crore: Optional[float] = None,
    max_top10_concentration_pct: Optional[float] = None,
    max_sector_concentration_pct: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    min_manager_tenure_years: Optional[float] = None,
    min_confidence_score: Optional[float] = None,
    allow_threshold_overrides: bool = False,
    risk_ceiling: Optional[int] = None,
) -> EligibilityGateResult:
    """
    Evaluate the ten fiduciary gates using the validated, versioned screening
    policy supplied by the caller or loaded from the authoritative policy file.
    Numeric thresholds, category caps, overlap coverage and thematic limits are
    policy parameters; this function does not supply investor or scheme defaults.
    Missing investor risk profile or required evidence fails closed.
    """
    failed = []
    details = {}

    fund_id = fund_data.get("fund_id", fund_data.get("id", ""))
    fund_name = str(fund_data.get("fund_name", fund_data.get("name", fund_id)) or "")
    category = str(fund_data.get("category", fund_data.get("cat", "")) or "")

    # Issue #50: Central screening policy binding and authoritative validation
    if policy is None:
        try:
            policy = load_fund_screening_policy()
        except Exception as exc:
            return EligibilityGateResult(
                fund_id=str(fund_id),
                fund_name=str(fund_name),
                passed=False,
                failed_gates=[f"Gate 0 [Policy Validation]: Central screening policy failed load ({exc}) — fail-closed"],
                details={"policy_error": str(exc)},
            )
    else:
        try:
            policy = validate_fund_screening_policy(policy)
        except Exception as exc:
            err_msg = str(exc)
            gt_tag = "missing 'gate_thresholds'" if "gate_thresholds" in err_msg else err_msg
            return EligibilityGateResult(
                fund_id=str(fund_id),
                fund_name=str(fund_name),
                passed=False,
                failed_gates=[f"Gate 0 [Policy Validation]: Central screening policy {gt_tag} — fail-closed"],
                details={"policy_error": str(exc)},
                policy_version=policy.get("version") if isinstance(policy, dict) else None,
                policy_digest=policy.get("_policy_digest") if isinstance(policy, dict) else None,
            )

    gt = policy["gate_thresholds"]

    # Issue #50: Runtime per-call threshold overrides are strictly prohibited.
    # Gate thresholds are governed exclusively by the centrally approved screening policy.
    # Caller-supplied booleans (allow_threshold_overrides=True) cannot authorize policy bypass.
    overrides = {
        "amc_max_limit_pct": amc_max_limit_pct,
        "min_aum_crore": min_aum_crore,
        "max_top10_concentration_pct": max_top10_concentration_pct,
        "max_sector_concentration_pct": max_sector_concentration_pct,
        "min_sharpe": min_sharpe,
        "min_manager_tenure_years": min_manager_tenure_years,
        "min_confidence_score": min_confidence_score,
    }
    supplied_overrides = [k for k, val in overrides.items() if val is not None]
    if supplied_overrides:
        raise ValueError(
            f"Unauthorized per-call threshold override for '{supplied_overrides[0]}'. "
            f"All overrides {supplied_overrides!r} are prohibited; "
            "gate thresholds are governed strictly by central policy."
        )

    cat_caps = _load_category_aum_caps(policy)
    if amc_max_limit_pct is None:
        if "amc_max_limit_pct" not in gt:
            raise ValueError("Screening policy missing 'amc_max_limit_pct' gate threshold")
        amc_max_limit_pct = float(gt["amc_max_limit_pct"])
    if min_aum_crore is None:
        if "min_aum_crore" not in gt:
            raise ValueError("Screening policy missing 'min_aum_crore' gate threshold")
        min_aum_crore = float(gt["min_aum_crore"])
    if max_top10_concentration_pct is None:
        if "max_top10_concentration_pct" not in gt:
            raise ValueError("Screening policy missing 'max_top10_concentration_pct' gate threshold")
        max_top10_concentration_pct = float(gt["max_top10_concentration_pct"])
    if max_sector_concentration_pct is None:
        if "max_sector_concentration_pct" not in gt:
            raise ValueError("Screening policy missing 'max_sector_concentration_pct' gate threshold")
        max_sector_concentration_pct = float(gt["max_sector_concentration_pct"])
    if min_sharpe is None:
        if "min_sharpe" not in gt:
            raise ValueError("Screening policy missing 'min_sharpe' gate threshold")
        min_sharpe = float(gt["min_sharpe"])
    if min_manager_tenure_years is None:
        if "min_manager_tenure_years" not in gt:
            raise ValueError("Screening policy missing 'min_manager_tenure_years' gate threshold")
        min_manager_tenure_years = float(gt["min_manager_tenure_years"])
    if min_confidence_score is None:
        if "min_confidence_score" not in gt:
            raise ValueError("Screening policy missing 'min_confidence_score' gate threshold")
        min_confidence_score = float(gt["min_confidence_score"])

    # --- Gate 1: AMC Concentration Gate ---
    # Never infer an AMC from the first token of a scheme name: many AMCs have
    # multi-word names and unrelated schemes can share the same first token.
    amc_name = str(fund_data.get("amc_name", "") or "").strip()
    amc_exposure_pct = None
    amc_ok = False
    if not amc_name:
        failed.append("Gate 1 [AMC Concentration]: explicit amc_name missing — cannot verify (fail-closed)")
    elif not portfolio_holdings:
        failed.append("Gate 1 [AMC Concentration]: portfolio holdings missing — cannot verify (fail-closed)")
    else:
        try:
            holding_values = []
            amc_values = []
            target_amc = amc_name.casefold()
            for holding in portfolio_holdings:
                raw_value = holding.get("value", holding.get("current_value_inr")) if isinstance(holding, dict) else getattr(holding, "current_value_inr", None)
                raw_amc = holding.get("amc_name", holding.get("amc")) if isinstance(holding, dict) else getattr(holding, "amc_name", None)
                value = _finite_number(raw_value, "portfolio holding value")
                if value < 0:
                    raise ValueError("portfolio holding value cannot be negative")
                if not raw_amc:
                    raise ValueError("portfolio holding AMC metadata missing")
                holding_values.append(value)
                if str(raw_amc).strip().casefold() == target_amc:
                    amc_values.append(value)
            total_val = sum(holding_values)
            if total_val <= 0:
                raise ValueError("portfolio total value must be positive")
            amc_exposure_pct = sum(amc_values) / total_val * 100.0
            amc_ok = amc_exposure_pct < amc_max_limit_pct
            if not amc_ok:
                failed.append(f"Gate 1 [AMC Concentration]: AMC {amc_name} exposure {amc_exposure_pct:.1f}% >= {amc_max_limit_pct}% ceiling")
        except (TypeError, ValueError) as exc:
            failed.append(f"Gate 1 [AMC Concentration]: invalid holdings/AMC data ({exc}) — fail-closed")
    details["amc_name"] = amc_name or None
    details["amc_exposure_pct"] = amc_exposure_pct

    # --- Gate 2: Liquidity & AUM Stability Gate ---
    try:
        aum = _finite_number(fund_data.get("aum_crore", fund_data.get("aum_cr")), "AUM")
        if aum < 0:
            raise ValueError("AUM cannot be negative")
    except ValueError as exc:
        aum = 0.0
        failed.append(f"Gate 2 [AUM]: {exc} — fail-closed")
    aum_min_ok = aum >= min_aum_crore
    if not aum_min_ok:
        failed.append(f"Gate 2 [Liquidity/AUM]: AUM ₹{aum:,.0f} Cr < ₹{min_aum_crore:,.0f} Cr minimum")

    cat_cap = cat_caps.get(category)
    aum_cap_ok = True
    if cat_cap and aum > cat_cap:
        aum_cap_ok = False
        failed.append(f"Gate 2 [AUM Size Drag]: AUM ₹{aum:,.0f} Cr exceeds {category} ceiling ₹{cat_cap:,.0f} Cr")

    aum_stable = fund_data.get("aum_stable")
    if aum_stable is None:
        failed.append("Gate 2 [AUM Stability]: aum_stable field missing — cannot verify liquidity (fail-closed)")
    elif not aum_stable:
        failed.append("Gate 2 [AUM Stability]: Outflows detected compromising liquidity")

    liquidity_and_aum_ok = aum_min_ok and aum_cap_ok and (aum_stable is True)
    details["aum_crore"] = aum

    # --- Gate 3: Top-10 Concentration Gate ---
    top10_raw = fund_data.get("top10_concentration_pct", fund_data.get("concentration_top10_pct", fund_data.get("top10")))
    if top10_raw is None:
        failed.append("Gate 3 [Top-10 Concentration]: top10_concentration_pct field missing — cannot verify (fail-closed)")
        top10 = 0.0
        top10_ok = False
    else:
        try:
            top10 = _finite_number(top10_raw, "top-10 concentration")
            if not 0.0 <= top10 <= 100.0:
                raise ValueError("top-10 concentration must be between 0 and 100")
            top10_ok = top10 <= max_top10_concentration_pct
        except ValueError as exc:
            top10 = None
            top10_ok = False
            failed.append(f"Gate 3 [Top-10 Concentration]: {exc} — fail-closed")
        if not top10_ok and top10 is not None:
            failed.append(f"Gate 3 [Top-10 Concentration]: Top 10 holdings {top10:.1f}% > {max_top10_concentration_pct:.1f}%")
    details["top10_concentration_pct"] = top10

    # Sector concentration check
    # Dedicated thematic/sectoral funds are governed by Gate 9 portfolio allocation limits.
    is_thematic = any(kw in category.lower() or kw in fund_name.lower() for kw in ("thematic", "sectoral", "defence", "energy", "pharma", "health", "tech"))
    sector_raw = fund_data.get("single_sector_weight_pct", fund_data.get("max_sector_concentration_pct", fund_data.get("fin")))
    sector_conc = None
    if not is_thematic:
        try:
            sector_conc = _finite_number(sector_raw, "single-sector concentration")
            if not 0.0 <= sector_conc <= 100.0:
                raise ValueError("single-sector concentration must be between 0 and 100")
        except ValueError as exc:
            failed.append(f"Gate 3 [Sector Concentration]: {exc} — fail-closed")
    elif sector_raw is not None:
        try:
            sector_conc = _finite_number(sector_raw, "single-sector concentration")
        except ValueError:
            sector_conc = None
    if not is_thematic and sector_conc is not None and sector_conc > max_sector_concentration_pct:
        failed.append(f"Gate 3 [Sector Concentration]: Sector weight {sector_conc:.1f}% > {max_sector_concentration_pct:.1f}%")
    details["sector_concentration_pct"] = sector_conc

    # --- Gate 4: Risk-Adjusted Sharpe & Alpha Gate (STRICTLY FAIL-CLOSED) ---
    from core.fund_classifier import is_verified_passive_scheme
    from core.models import InsufficientDataError
    sharpe = fund_data.get("sharpe_3y", fund_data.get("sharpe", None))
    alpha = fund_data.get("alpha_3y", fund_data.get("alpha", None))
    f_name = fund_data.get("fund_name", fund_data.get("name", ""))
    
    # Gate 4: Check if this is a verified passive scheme
    # If ISIN/scheme master unavailable for active fund, Default to False (not passive)
    # Passive verification failure due to missing ISIN should NOT cause gate failure for active funds
    is_passive_cand = False
    try:
        is_passive_cand = is_verified_passive_scheme(fund_data, fund_name=f_name, category=category, require_scheme_master=True)
    except InsufficientDataError:
        # No ISIN/scheme master available - cannot verify passive status
        # For active funds, this is fine - we'll check Sharpe and Alpha below
        # Only fail if fund was explicitly marked as passive but can't be verified
        if fund_data.get("is_passive") is True:
            failed.append(f"Gate 4 [Passive Verification]: Cannot verify passive status - missing scheme master")
            is_passive_cand = False

    sharpe_ok = False
    if is_passive_cand:
        sharpe_ok = True
    elif sharpe is None:
        failed.append("Gate 4 [Sharpe Ratio Missing]: 3Y Sharpe ratio is missing (fail-closed)")
    elif isinstance(sharpe, bool):
        failed.append(f"Gate 4 [Sharpe Malformed]: Boolean value '{sharpe}' is not a numeric Sharpe ratio (fail-closed)")
    elif isinstance(sharpe, str) and not sharpe.strip():
        failed.append("Gate 4 [Sharpe Malformed]: Empty Sharpe ratio string (fail-closed)")
    else:
        try:
            s_val = float(sharpe)
            if math.isnan(s_val) or math.isinf(s_val):
                failed.append("Gate 4 [Sharpe Non-Finite]: 3Y Sharpe ratio is NaN/Infinity (fail-closed)")
            elif s_val < min_sharpe:
                failed.append(f"Gate 4 [Sharpe Ratio]: 3Y Sharpe {s_val:.2f} < {min_sharpe:.2f}")
            else:
                sharpe_ok = True
        except (ValueError, TypeError):
            failed.append(f"Gate 4 [Sharpe Malformed]: Invalid Sharpe ratio value '{sharpe}' (fail-closed)")

    alpha_ok = False
    if is_passive_cand:
        alpha_ok = True
    elif alpha is None:
        failed.append("Gate 4 [Alpha Drag Missing]: 3Y Jensen's Alpha is missing (fail-closed)")
    elif isinstance(alpha, bool):
        failed.append(f"Gate 4 [Alpha Malformed]: Boolean value '{alpha}' is not a numeric Alpha (fail-closed)")
    elif isinstance(alpha, str) and not alpha.strip():
        failed.append("Gate 4 [Alpha Malformed]: Empty Alpha string (fail-closed)")
    else:
        try:
            a_val = float(alpha)
            if math.isnan(a_val) or math.isinf(a_val):
                failed.append("Gate 4 [Alpha Non-Finite]: 3Y Jensen's Alpha is NaN/Infinity (fail-closed)")
            elif a_val <= 0.0:
                failed.append(f"Gate 4 [Alpha Drag]: Non-positive 3Y Jensen's Alpha {a_val:.2f}% vs TRI Benchmark (active funds require > 0.0% to justify active fee drag)")
            else:
                alpha_ok = True
        except (ValueError, TypeError):
            failed.append(f"Gate 4 [Alpha Malformed]: Invalid Alpha value '{alpha}' (fail-closed)")

    sharpe_alpha_ok = sharpe_ok and alpha_ok
    details["sharpe"] = sharpe
    details["alpha"] = alpha

    # --- Gate 5: Downside Capture Ratio Gate ---
    # Gate 5: Capture Ratio Asymmetry Gate (renamed from Downside Capture Ratio Gate)
    # Requires genuine capture ratio data - no mock defaults
    # Passive/index funds are exempt (by definition track index with 100/100 capture)
    downside_capture = fund_data.get("downside_capture_ratio", fund_data.get("downside_capture"))
    upside_capture = fund_data.get("upside_capture_ratio", fund_data.get("upside_capture"))
    
    if is_passive_cand:
        # Passive funds track index - capture ratios are 100/100 by definition
        downside_capture = 100.0
        upside_capture = 100.0
        downside_ok = True
    elif downside_capture is None or upside_capture is None:
        # Fail explicitly if capture ratio data is missing (Zero Mock Defaults mandate)
        failed.append("Gate 5 [Capture Ratio Asymmetry]: Missing downside/upside capture ratio data in fund_metrics.json — required for fiduciary assessment")
        downside_ok = False
    else:
        try:
            downside_capture = _finite_number(downside_capture, "downside capture")
            upside_capture = _finite_number(upside_capture, "upside capture")
            if not (0.0 <= downside_capture <= 500.0 and 0.0 <= upside_capture <= 500.0):
                raise ValueError("capture ratios must be between 0 and 500")
            downside_ok = True
        except ValueError as exc:
            failed.append(f"Gate 5 [Capture Ratio]: {exc} — fail-closed")
            downside_ok = False
            downside_capture = upside_capture = None
        # Capture Ratio Asymmetry Gate: Fund fails if downside capture > 100% AND upside < downside
        if downside_capture is not None and upside_capture is not None and downside_capture > 100.0 and upside_capture < downside_capture:
            downside_ok = False
            failed.append(f"Gate 5 [Inverted Capture Asymmetry]: Downside capture {downside_capture:.1f}% > 100% AND Upside {upside_capture:.1f}% < Downside {downside_capture:.1f}%")
    
    details["downside_capture"] = downside_capture
    details["upside_capture"] = upside_capture

    # --- Gate 6: Mandate Suitability Gate ---
    riskometer_raw = fund_data.get("riskometer_score")
    if riskometer_raw is None:
        failed.append("Gate 6 [Riskometer]: riskometer_score field missing - cannot verify suitability (fail-closed)")
        riskometer_score = 6
        mandate_ok = False
    else:
        try:
            riskometer_num = _finite_number(riskometer_raw, "riskometer_score")
            if not riskometer_num.is_integer() or not 1 <= riskometer_num <= 6:
                raise ValueError("riskometer_score must be an integer from 1 to 6")
            riskometer_score = int(riskometer_num)
            mandate_ok = True
        except ValueError as exc:
            riskometer_score = 6
            mandate_ok = False
            failed.append(f"Gate 6 [Riskometer]: {exc} — fail-closed")
    mandate_suitable_raw = fund_data.get("mandate_suitable")
    if mandate_suitable_raw is None:
        failed.append("Gate 6 [Mandate Suitability]: mandate_suitable field missing - cannot verify (fail-closed)")
        mandate_ok = False
    elif not mandate_suitable_raw:
        mandate_ok = False
    # Investor suitability is mandatory and distinct from scheme Riskometer (D-013, D-014).
    # Investor risk capacity (profile) and scheme Riskometer are separate dimensions.
    # Candidate Riskometer must be within the investor's approved ceiling.
    effective_ceiling = None
    is_custom_tier = (
        client_risk_tier_num == RiskTier.CUSTOM
        or (isinstance(client_risk_tier_num, str) and client_risk_tier_num.strip().lower() == "custom")
        or client_risk_tier_num == 0
    )
    if client_risk_tier_num is None:
        client_tier_int = 0
        mandate_ok = False
        failed.append("Gate 6 [Investor Suitability]: explicit validated investor risk profile missing — fail-closed")
    elif is_custom_tier:
        if risk_ceiling is None:
            client_tier_int = 0
            mandate_ok = False
            failed.append("Gate 6 [Investor Suitability]: Custom risk profile requires an explicit risk ceiling (1 to 6) — fail-closed")
        else:
            try:
                if isinstance(risk_ceiling, bool):
                    raise ValueError("risk_ceiling must not be boolean")
                c_num = int(risk_ceiling)
                if not 1 <= c_num <= 6:
                    raise ValueError("risk_ceiling must be an integer from 1 to 6")
                client_tier_int = c_num
                effective_ceiling = c_num
            except (ValueError, TypeError) as exc:
                client_tier_int = 0
                mandate_ok = False
                failed.append(f"Gate 6 [Investor Suitability]: invalid risk ceiling {risk_ceiling!r} — fail-closed")
    else:
        try:
            client_tier_int = _risk_tier_to_int(client_risk_tier_num)
            if risk_ceiling is not None:
                if isinstance(risk_ceiling, bool):
                    raise ValueError("risk_ceiling must not be boolean")
                c_num = int(risk_ceiling)
                if not 1 <= c_num <= 6:
                    raise ValueError("risk_ceiling must be an integer from 1 to 6")
                effective_ceiling = min(client_tier_int, c_num)
            else:
                effective_ceiling = client_tier_int
        except ValueError as exc:
            client_tier_int = 0
            mandate_ok = False
            failed.append(f"Gate 6 [Investor Suitability]: {exc} — fail-closed")
    
    # Passive/index funds are exempt from riskometer breach (broad market tracking = diversified risk)
    if effective_ceiling is not None and not is_passive_cand and riskometer_score > effective_ceiling:
        mandate_ok = False
        failed.append(f"Gate 6 [Riskometer Breach]: Fund riskometer score {riskometer_score} exceeds client risk ceiling {effective_ceiling}")
    elif effective_ceiling is None and not is_passive_cand:
        mandate_ok = False

    details["effective_risk_ceiling"] = effective_ceiling

    is_thematic = any(kw in category.lower() or kw in fund_name.lower() for kw in ("thematic", "sectoral", "defence", "energy", "pharma", "tech"))
    if is_starter and is_thematic:
        mandate_ok = False
        failed.append("Gate 6 [Mandate Suitability]: Starter portfolios (< INR 5L) are barred from thematic/sectoral funds")
    details["mandate_suitable"] = mandate_ok

    # --- Gate 7: Data Integrity & Provenance Gate ---
    provenance = fund_data.get("_provenance", {})
    # Top-level confidence_score overrides _provenance.confidence_score
    confidence_score = None
    if "confidence_score" in fund_data:
        try:
            confidence_score = _finite_number(fund_data.get("confidence_score"), "confidence_score")
        except ValueError as exc:
            confidence_score = None
            failed.append(f"Gate 7 [Data Integrity]: {exc} — fail-closed")
    elif "confidence_score" in provenance:
        try:
            confidence_score = _finite_number(provenance.get("confidence_score"), "_provenance.confidence_score")
        except ValueError as exc:
            confidence_score = None
            failed.append(f"Gate 7 [Data Integrity]: {exc} — fail-closed")
    
    if confidence_score is not None and not 0.0 <= confidence_score <= 1.0:
        failed.append("Gate 7 [Data Integrity]: confidence_score must be between 0 and 1 — fail-closed")
        confidence_score = None

    if confidence_score is None:
        failed.append("Gate 7 [Data Integrity]: confidence_score missing, malformed or out of range — cannot verify (fail-closed)")
        data_ok = False
    else:
        data_ok = confidence_score >= min_confidence_score
        if not data_ok:
            failed.append(f"Gate 7 [Data Integrity]: Confidence score {confidence_score:.2f} < {min_confidence_score:.2f}")
    
    if "data_complete" not in fund_data:
        failed.append("Gate 7 [Data Integrity]: data_complete field missing - cannot verify (fail-closed)")
        data_ok = False
    elif not fund_data.get("data_complete", False):
        failed.append("Gate 7 [Data Integrity]: data_complete is False - factsheet incomplete")
        data_ok = False
    details["confidence_score"] = confidence_score

    # --- Gate 8: Manager Tenure & Process Continuity Gate ---
    # Evaluates scheme operational history (>= 3.0 yrs) and manager continuity (tenure >= min_manager_tenure_years, default 2.0 yrs).
    # Process-driven index and arbitrage funds are exempted from individual manager tenure.
    if "manager_tenure_years" not in fund_data and "tenure" not in fund_data:
        failed.append("Gate 8 [Manager Tenure]: manager_tenure_years field missing - cannot verify (fail-closed)")
        tenure = 0.0
    else:
        try:
            tenure = _finite_number(fund_data.get("manager_tenure_years", fund_data.get("tenure")), "manager_tenure_years")
            if tenure < 0: raise ValueError("manager tenure cannot be negative")
        except ValueError as exc:
            tenure = 0.0
            failed.append(f"Gate 8 [Manager Tenure]: {exc} — fail-closed")
    if "track_record_years" not in fund_data and "track_record" not in fund_data:
        failed.append("Gate 8 [Track Record]: track_record_years field missing - cannot verify (fail-closed)")
        scheme_track_record = 0.0
    else:
        try:
            scheme_track_record = _finite_number(fund_data.get("track_record_years", fund_data.get("track_record")), "track_record_years")
            if scheme_track_record < 0: raise ValueError("track record cannot be negative")
        except ValueError as exc:
            scheme_track_record = 0.0
            failed.append(f"Gate 8 [Track Record]: {exc} — fail-closed")
    is_process_driven = bool(fund_data.get("is_process_driven", False) or "index" in category.lower() or "arbitrage" in category.lower())

    track_ok = scheme_track_record >= 3.0
    tenure_ok = (tenure >= min_manager_tenure_years) or is_process_driven

    if not track_ok:
        failed.append(f"Gate 8 [Track Record]: Scheme operational history {scheme_track_record:.1f} yrs < 3.0 yrs minimum")
    if not tenure_ok:
        failed.append(f"Gate 8 [Manager Tenure]: Current manager tenure {tenure:.1f} yrs < {min_manager_tenure_years:.1f} yrs minimum without process-driven exemption")

    details["scheme_track_record_years"] = scheme_track_record
    details["manager_tenure_years"] = tenure

    # --- Gate 9: Thematic Satellite Cap Gate ---
    thematic_ok = True
    alloc_pct = 0.0
    if is_thematic:
        try:
            alloc_pct = _finite_number(fund_data.get("allocation_pct"), "allocation_pct")
            if not 0.0 <= alloc_pct <= 100.0:
                raise ValueError("allocation_pct must be between 0 and 100")
        except ValueError as exc:
            thematic_ok = False
            failed.append(f"Gate 9 [Thematic Cap]: {exc} — fail-closed")
    if is_thematic and thematic_ok:
        if is_starter and alloc_pct > 0.0:
            thematic_ok = False
            failed.append("Gate 9 [Thematic Cap]: Thematic satellite must be 0% for starter portfolios")
        elif alloc_pct > 15.0:
            thematic_ok = False
            failed.append(f"Gate 9 [Thematic Cap]: Thematic satellite {alloc_pct:.1f}% exceeds 15% maximum")
    details["thematic_ok"] = thematic_ok

    # --- Gate 10: 100% Direct Plan Mandate Gate (CRYPTOGRAPHICALLY SECURE) ---
    plan_value = str(fund_data.get("plan", "") or "").strip().casefold()
    direct_flag = fund_data.get("is_direct")
    # Recompute the local evidence digest at the decision boundary; never trust
    # a copied/caller-supplied status string as proof of Direct-plan identity.
    eval_as_of = (
        as_of_date
        or (fund_data.get("as_of_date") if isinstance(fund_data, dict) else None)
        or (fund_data.get("decision_as_of_date") if isinstance(fund_data, dict) else None)
        or (fund_data.get("disclosure_as_of_date") if isinstance(fund_data, dict) else None)
    )
    # Use environment-configured trust registry for Ed25519 signature verification
    default_registry = _get_default_trust_registry()
    direct_evidence_status = _reviewed_direct_plan_evidence_status(
        fund_data,
        as_of_date=eval_as_of,
        trust_registry=default_registry,
    )
    if "regular" in plan_value or "distributor" in plan_value or "regular" in fund_name.casefold():
        is_direct = False
    elif direct_evidence_status == "REVIEWER_ATTESTED_HASH_MATCH":
        # Signature verification passed OR trust registry not configured (dev test mode)
        is_direct = direct_flag is True and plan_value.startswith("direct")
    elif direct_evidence_status == "SIGNATURE_MISSING":
        # Trust registry configured but no signed envelope in evidence
        is_direct = False
        failed.append(
            "Gate 10 [Direct Plan Mandate]: Signed evidence envelope required (trust registry configured)"
        )
    elif direct_evidence_status == "TRUST_REGISTRY_MISSING":
        # Envelope present in evidence but no trust registry to verify it
        is_direct = False
        failed.append(
            "Gate 10 [Direct Plan Mandate]: Evidence contains signature but signer trust key unavailable (set SIP_REVIEWER_TRUST_REGISTRY_JSON)"
        )
    elif direct_evidence_status == "SIGNATURE_INVALID":
        # Signature verification failed
        is_direct = False
        failed.append(
            "Gate 10 [Direct Plan Mandate]: Evidence signature verification failed"
        )
    else:
        # INVALID, MISSING, STALE, MISSING_AS_OF_DATE, or any other error
        is_direct = False
        failed.append(
            "Gate 10 [Direct Plan Mandate]: current reviewer-attested source document with matching hash and explicit Direct plan classification is required"
        )
    if not is_direct:
        failed.append("Gate 10 [Direct Plan Mandate]: Scheme is not verified as a Direct plan")
    details["is_direct"] = is_direct

    passed = (len(failed) == 0)

    details["policy_version"] = policy.get("version")
    details["policy_as_of"] = policy.get("as_of")
    details["policy_digest"] = policy.get("_policy_digest")

    return EligibilityGateResult(
        fund_id=str(fund_id),
        fund_name=str(fund_name),
        passed=passed,
        failed_gates=failed,
        amc_concentration_gate=amc_ok,
        aum_stability_gate=liquidity_and_aum_ok,
        concentration_gate=top10_ok,
        sharpe_alpha_gate=sharpe_alpha_ok,
        liquidity_gate=downside_ok,
        mandate_suitability_gate=mandate_ok,
        data_integrity_gate=data_ok,
        manager_tenure_gate=tenure_ok,
        thematic_satellite_gate=thematic_ok,
        direct_plan_gate=is_direct,
        policy_version=policy.get("version"),
        policy_digest=policy.get("_policy_digest"),
        details=details
    )


def _portfolio_weighted_constituent_overlap_pct(
    candidate: Dict[str, Any],
    portfolio_holdings: List[Any],
    *,
    minimum_coverage_pct: Optional[float] = None,
) -> Optional[float]:
    """
    Return weighted constituent overlap (0-100) between a candidate and the
    existing equity portfolio. None means overlap is not safely measurable.

    Existing funds are aggregated by current equity value, not counted equally.
    Both sides require source-verified constituent weights and adequate
    disclosure coverage. Missing look-through is never treated as zero overlap.
    """
    if minimum_coverage_pct is None:
        policy = load_fund_screening_policy()
        minimum_coverage_pct = float(
            policy["portfolio_lookthrough_policy"]["required_coverage_pct"]
        )

    def field(item: Any, name: str, default=None):
        return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)

    def weights_for(item: Any) -> Optional[Dict[str, float]]:
        if field(item, "lookthrough_status", "") != "VERIFIED":
            return None
        coverage = field(item, "constituent_weights_coverage_pct")
        try:
            if isinstance(coverage, bool) or coverage is None:
                return None
            coverage = float(coverage)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(coverage) or coverage < minimum_coverage_pct or coverage > 100.0:
            return None
        raw = field(item, "constituent_weights")
        if not isinstance(raw, dict) or not raw:
            return None
        parsed = {}
        for name, value in raw.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool):
                return None
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number) or number < 0.0 or number > 100.0:
                return None
            if number > 0:
                parsed[name.strip().casefold()] = parsed.get(name.strip().casefold(), 0.0) + number
        total = sum(parsed.values())
        if not parsed or total <= 0.0 or total > 100.5:
            return None
        return {name: value * 100.0 / total for name, value in parsed.items()}

    candidate_weights = weights_for(candidate)
    if candidate_weights is None:
        return None

    portfolio_exposure: Dict[str, float] = {}
    equity_value_total = 0.0
    for holding in portfolio_holdings or []:
        raw_value = field(holding, "current_value_inr", field(holding, "value"))
        raw_equity_pct = field(holding, "equity_pct")
        asset_class = str(field(holding, "asset_class", "") or "").casefold()
        if raw_value is None or isinstance(raw_value, bool) or raw_equity_pct is None:
            return None
        try:
            value = float(raw_value)
            equity_pct = float(raw_equity_pct)
        except (TypeError, ValueError):
            return None
        if (not math.isfinite(value) or value < 0.0
                or not math.isfinite(equity_pct) or not 0.0 <= equity_pct <= 100.0):
            return None
        equity_value = value * equity_pct / 100.0
        if equity_value <= 0.0:
            continue
        # Equity exposure must be explicitly classified; unknown asset classes
        # cannot be silently treated as a fully understood equity holding.
        if not any(token in asset_class for token in (
            "large", "mid", "small", "flexi", "multi", "equity", "international"
        )):
            return None
        holding_weights = weights_for(holding)
        if holding_weights is None:
            return None
        equity_value_total += equity_value
        for stock, weight_pct in holding_weights.items():
            portfolio_exposure[stock] = portfolio_exposure.get(stock, 0.0) + equity_value * weight_pct / 100.0

    if equity_value_total <= 0.0:
        return None
    portfolio_total = sum(portfolio_exposure.values())
    if portfolio_total <= 0.0:
        return None
    portfolio_weights = {
        stock: exposure * 100.0 / portfolio_total
        for stock, exposure in portfolio_exposure.items()
    }
    return sum(
        min(weight, portfolio_weights.get(stock, 0.0))
        for stock, weight in candidate_weights.items()
    )


def filter_candidates(
    candidate_universe: List[Dict[str, Any]],
    current_portfolio: List[Dict[str, Any]],
    amc_max_limit_pct: Optional[float] = None,
    max_overlap_limit_pct: Optional[float] = None,
    client_risk_tier_num: Optional[int] = None,
    is_starter: bool = False,
    policy: Optional[Dict[str, Any]] = None,
    allow_threshold_overrides: bool = False,
    risk_ceiling: Optional[int] = None,
) -> List[str]:
    """
    Apply the binary eligibility gates and a portfolio-weighted look-through
    overlap ceiling bound to the authoritative screening policy.
    """
    if policy is None:
        policy = load_fund_screening_policy()
    else:
        policy = validate_fund_screening_policy(policy)

    # Issue #50: Per-call threshold overrides are prohibited at runtime.
    # Caller-controlled booleans (allow_threshold_overrides=True) cannot authorize policy bypass.
    if amc_max_limit_pct is not None:
        raise ValueError(
            "Unauthorized per-call threshold override for 'amc_max_limit_pct'. "
            "Gate thresholds are governed strictly by central policy; "
            "caller overrides are prohibited."
        )
    if max_overlap_limit_pct is not None:
        raise ValueError(
            "Unauthorized per-call threshold override for 'max_overlap_limit_pct'. "
            "Gate thresholds are governed strictly by central policy; "
            "caller overrides are prohibited."
        )

    gt = policy["gate_thresholds"]
    lookthrough_policy = policy["portfolio_lookthrough_policy"]
    minimum_coverage_pct = float(lookthrough_policy["required_coverage_pct"])
    amc_max_limit_pct = float(gt["amc_max_limit_pct"])
    raw_overlap = gt["max_overlap_candidate_pct"]

    if isinstance(raw_overlap, bool):
        raise ValueError("max_overlap_candidate_pct must be numeric")
    try:
        overlap_limit = float(raw_overlap)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_overlap_candidate_pct must be numeric") from exc
    if not math.isfinite(overlap_limit) or not 0.0 <= overlap_limit <= 100.0:
        raise ValueError("max_overlap_candidate_pct must be finite and between 0 and 100")

    eligible = []
    for cand in candidate_universe:
        cand_name = cand.get("name", cand.get("fund_name", cand.get("id", "")))
        fund_data = dict(cand)
        fund_data["fund_name"] = cand_name

        gate_result = check_eligibility_gates(
            fund_data=fund_data,
            portfolio_holdings=current_portfolio,
            client_risk_tier_num=client_risk_tier_num,
            is_starter=is_starter,
            policy=policy,
            risk_ceiling=risk_ceiling,
        )
        if not gate_result.passed:
            continue

        overlap_pct = _portfolio_weighted_constituent_overlap_pct(
            fund_data, current_portfolio,
            minimum_coverage_pct=minimum_coverage_pct,
        )
        if overlap_pct is None or overlap_pct > overlap_limit:
            continue
        eligible.append(cand_name)

    return eligible

def evaluate_no_action(
    current_portfolio: List[Any],
    candidate_funds: List[Dict[str, Any]],
    min_improvement_threshold: float = 5.0,
    client_risk_tier_num: Optional[int] = None,
    policy: Optional[Dict[str, Any]] = None,
    risk_ceiling: Optional[int] = None,
) -> NOActionResult:
    """
    Mandatory Fiduciary NO ACTION decision branch:
    If no candidate scheme demonstrates statistically validated improvement (composite score >= 5.0),
    emits an explicit verdict: NO ACTION / HOLD. Retain existing holdings.
    """
    if client_risk_tier_num is None:
        return NOActionResult(
            action="NO_ACTION",
            reason="Explicit investor suitability profile is missing; no candidate was evaluated.",
            current_portfolio_adequate=False,
            no_improvement_found=True,
            hold_recommendation="HOLD — obtain and validate the investor risk profile before eligibility review.",
            sip_deployment_pause=True,
        )
    is_custom = (
        client_risk_tier_num == RiskTier.CUSTOM
        or (isinstance(client_risk_tier_num, str) and client_risk_tier_num.strip().lower() == "custom")
        or client_risk_tier_num == 0
    )
    if not is_custom:
        try:
            _risk_tier_to_int(client_risk_tier_num)
        except ValueError as exc:
            return NOActionResult(
                action="NO_ACTION",
                reason=f"Investor suitability profile is invalid: {exc}",
                current_portfolio_adequate=False,
                no_improvement_found=True,
                hold_recommendation="HOLD — obtain a valid investor risk profile before eligibility review.",
                sip_deployment_pause=True,
            )
    elif risk_ceiling is None:
        return NOActionResult(
            action="NO_ACTION",
            reason="Custom risk profile requires an explicit risk ceiling (1 to 6).",
            current_portfolio_adequate=False,
            no_improvement_found=True,
            hold_recommendation="HOLD — obtain a valid risk ceiling for custom SAA before review.",
            sip_deployment_pause=True,
        )
    best_improvement = 0.0
    best_fund = None

    for fund in candidate_funds:
        is_passed = fund.get("eligibility", {}).get("passed", False)
        if not is_passed and "eligibility" not in fund:
            # Evaluate on the fly if not pre-evaluated
            gate_res = check_eligibility_gates(
                fund, client_risk_tier_num=client_risk_tier_num, policy=policy, risk_ceiling=risk_ceiling
            )
            is_passed = gate_res.passed

        if not is_passed:
            continue

        score = float(fund.get("composite_score", fund.get("score", 0.0)) or 0.0)
        if score > best_improvement:
            best_improvement = score
            best_fund = fund

    no_improvement = (best_improvement < min_improvement_threshold)
    current_adequate = no_improvement

    if no_improvement:
        best_name = best_fund.get("fund_name", best_fund.get("name", "None")) if best_fund else "None"
        best_score = best_improvement if best_fund else 0.0
        reason = (
            f"No candidate fund offers demonstrable, statistically validated improvement (>={min_improvement_threshold} pts) "
            f"over current portfolio. Best candidate: {best_name} (+{best_score:.1f} pts). "
            f"Fiduciary mandate: NO ACTION / HOLD existing assets."
        )
        hold_rec = "Retain current verified holdings. Pause fresh deployment until qualifying candidates emerge. Review quarterly."
    else:
        best_name = best_fund.get("fund_name", best_fund.get("name", "Unknown"))
        reason = f"Demonstrated improvement candidate found: {best_name} (+{best_improvement:.1f} pts over hurdle)."
        hold_rec = "Proceed with deployment into verified candidate."

    return NOActionResult(
        action="NO_ACTION" if no_improvement else "PROCEED",
        reason=reason,
        current_portfolio_adequate=current_adequate,
        no_improvement_found=no_improvement,
        hold_recommendation=hold_rec,
        sip_deployment_pause=no_improvement
    )


def load_candidate_universe(
    metrics_path: Path,
    screening_policy_path: Optional[Path] = None,
    portfolio_disclosures_by_scheme_id: Optional[Dict[str, Dict[str, Any]]] = None,
    portfolio_disclosure_source_bytes_by_scheme_id: Optional[Dict[str, bytes]] = None,
    disclosure_as_of_date: Optional[date] = None,
    disclosure_max_age_days: int = 45,
) -> List[Dict[str, Any]]:
    """
    Loads candidate universe from fund_metrics.json and enriches with screening policy rules.
    """
    candidates = []
    if not metrics_path.exists():
        return candidates

    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return candidates

    funds = data.get("funds", [])
    for m in funds:
        # Preserve missing values as None — eligibility gates will fail closed
        aum_crore = m.get("aum_crore", m.get("aum_cr"))
        top10_raw = m.get("top10_concentration_pct", m.get("concentration_top10", m.get("top10")))
        sector_raw = m.get("single_sector_weight_pct", m.get("max_sector_concentration", m.get("fin")))
        sharpe_3y_raw = m.get("sharpe_3y", m.get("sharpe"))
        sharpe_1y_raw = m.get("sharpe_1y")
        alpha_3y_raw = m.get("alpha_3y", m.get("alpha"))
        return_1y_raw = m.get("return_1y", m.get("ret_1y"))
        return_6m_raw = m.get("return_6m", m.get("ret_6m"))
        return_3y_raw = m.get("return_3y", m.get("ret_3y"))
        ter_raw = m.get("ter_direct_pct", m.get("er"))
        er_raw = m.get("er", m.get("ter_direct_pct"))
        riskometer_raw = m.get("riskometer_score")
        manager_tenure_raw = m.get("manager_tenure_years")
        track_record_raw = m.get("track_record_years")
        composite_raw = m.get("composite_score")
        downside_raw = m.get("downside_capture_ratio", m.get("downside_capture"))
        upside_raw = m.get("upside_capture_ratio", m.get("upside_capture"))
        riskometer_raw = m.get("riskometer_score")
        is_passive_raw = m.get("is_passive")
        provenance_raw = m.get("_provenance")
        fund_name = m.get("name", m.get("scheme_name", m.get("id", "")))
        scheme_id = m.get("scheme_id")
        # Eligibility replay must be bound to the caller's decision date.
        # If not provided externally, use the fund record's as_of_date for backward compatibility.
        # Never substitute the process wall clock for missing as-of evidence.
        effective_as_of = disclosure_as_of_date or m.get("as_of_date")

        evidence_context = {
            "direct_plan_evidence": m.get("direct_plan_evidence"),
            "_evidence_root": str(Path(metrics_path).resolve().parent),
            "fund_name": fund_name,
            "scheme_id": scheme_id,
            "isin": m.get("isin"),
            "amc_name": m.get("amc_name"),
            "as_of_date": effective_as_of,
        }
        direct_evidence_status = _reviewed_direct_plan_evidence_status(
            evidence_context,
            as_of_date=effective_as_of,
        )
        source_direct_flag = m.get("is_direct")
        if source_direct_flag is False:
            direct_flag = False
        elif source_direct_flag is True and direct_evidence_status == "REVIEWER_ATTESTED_HASH_MATCH":
            direct_flag = True
        else:
            direct_flag = None

        lookthrough = {
            "constituent_weights": None,
            "constituent_weights_coverage_pct": None,
            "status": "MISSING",
            "reason": "Candidate metrics do not themselves establish source-verified constituents.",
        }
        if (isinstance(scheme_id, str) and scheme_id
                and portfolio_disclosures_by_scheme_id is not None
                and portfolio_disclosure_source_bytes_by_scheme_id is not None
                and disclosure_as_of_date is not None):
            from ingestion.portfolio_disclosure import validate_portfolio_disclosure
            disclosure_record = portfolio_disclosures_by_scheme_id.get(scheme_id)
            disclosure_bytes = portfolio_disclosure_source_bytes_by_scheme_id.get(scheme_id)
            if disclosure_record is not None and disclosure_bytes is not None:
                lookthrough = validate_portfolio_disclosure(
                    disclosure_record, disclosure_bytes,
                    as_of=disclosure_as_of_date,
                    max_age_days=disclosure_max_age_days,
                )
                if lookthrough.get("scheme_id") != scheme_id:
                    lookthrough = {
                        "constituent_weights": None,
                        "constituent_weights_coverage_pct": None,
                        "status": "CONFLICTING",
                        "reason": "Disclosure scheme identifier does not match candidate scheme identifier.",
                    }

        cand = {
            "fund_id": m.get("id", ""),
            "scheme_id": scheme_id,
            "isin": m.get("isin"),
            "amc_name": m.get("amc_name"),
            "constituent_weights": lookthrough.get("constituent_weights"),
            "constituent_weights_coverage_pct": lookthrough.get("constituent_weights_coverage_pct"),
            "lookthrough_status": lookthrough["status"],
            "lookthrough_reason": lookthrough["reason"],
            "fund_name": fund_name,
            "aum_crore": float(aum_crore) if aum_crore is not None else None,
            "aum_stable": m.get("aum_stable"),  # None if missing — gate will fail closed
            "category": m.get("category", m.get("cat", "")),
            # Preserve source-supplied scoring pillars. Missing values remain
            # None so the scoring boundary can withhold a composite score.
            "cash_debt_buffer_pct": m.get("cash_debt_buffer_pct"),
            "international_equity_pct": m.get("international_equity_pct"),
            "overlap_pct": m.get("overlap_pct"),
            "top10_concentration_pct": float(top10_raw) if top10_raw is not None else None,
            "single_sector_weight_pct": float(sector_raw) if sector_raw is not None else None,
            "sharpe_3y": float(sharpe_3y_raw) if sharpe_3y_raw is not None else None,
            "sharpe_1y": float(sharpe_1y_raw) if sharpe_1y_raw is not None else None,
            "alpha_3y": float(alpha_3y_raw) if alpha_3y_raw is not None else None,
            "return_1y": float(return_1y_raw) if return_1y_raw is not None else None,
            "return_6m": float(return_6m_raw) if return_6m_raw is not None else None,
            "return_3y": float(return_3y_raw) if return_3y_raw is not None else None,
            "ter_direct_pct": float(ter_raw) if ter_raw is not None else None,
            "er": float(er_raw) if er_raw is not None else None,
            "downside_capture_ratio": downside_raw,
            "upside_capture_ratio": upside_raw,
            "riskometer_score": int(riskometer_raw) if riskometer_raw is not None else None,
            "mandate_suitable": m.get("mandate_suitable"),  # None if missing — gate will fail closed
            "data_complete": m.get("data_complete"),  # None if missing — gate will fail closed
            "manager_tenure_years": float(manager_tenure_raw) if manager_tenure_raw is not None else None,
            "track_record_years": float(track_record_raw) if track_record_raw is not None else None,
            "composite_score": float(composite_raw) if composite_raw is not None else None,
            # Never synthesize Direct-plan status. Require the source document
            # to be present locally, hash-matched and reviewer-attested.
            "direct_plan_evidence": m.get("direct_plan_evidence"),
            "_evidence_root": str(Path(metrics_path).resolve().parent),
            "direct_plan_evidence_status": direct_evidence_status,
            "is_direct": direct_flag,
            "plan": (
                m.get("direct_plan_evidence", {}).get("plan", "")
                if isinstance(m.get("direct_plan_evidence"), dict)
                else ""
            ),
            "is_passive": is_passive_raw if is_passive_raw is not None else False,
            "_provenance": provenance_raw if provenance_raw is not None else {},
            "eligibility": {}
        }
        candidates.append(cand)

    return candidates


def validate_thematic_satellite_cap(
    sip_plan: Any,
    client_aum: float,
    max_satellite_pct: float = 15.0
) -> bool:
    """
    Enforces Gate 9: Thematic Satellite Cap.
    - If client AUM < INR 5,00,000 (Starter), satellite thematic must be 0%.
    - If client AUM >= INR 5,00,000, satellite thematic must not exceed 15%.
    """
    if not hasattr(sip_plan, "items"):
        return True

    thematic_alloc = sum(
        item.allocation_pct for item in sip_plan.items
        if getattr(item, "rational_code", "") == "SATELLITE_THEME"
    )

    if client_aum > 0 and client_aum < 500000.0 and thematic_alloc > 0.0:
        raise ValueError(f"Fiduciary Gate 9 Violation: Starter portfolios (< INR 5L AUM) cannot hold thematic funds (found {thematic_alloc}%).")

    if thematic_alloc > max_satellite_pct:
        raise ValueError(f"Fiduciary Gate 9 Violation: Thematic satellite allocation {thematic_alloc}% exceeds max allowed {max_satellite_pct}%.")

    return True


def validate_direct_sip_mandate(sip_plan: Any) -> bool:
    """Require explicit Direct-plan metadata for every positive SIP allocation."""
    if not hasattr(sip_plan, "items"):
        raise ValueError("SIP plan is missing recommendation items; Direct-plan status cannot be verified")

    for item in sip_plan.items:
        amount = getattr(item, "monthly_inr", None)
        scheme = str(getattr(item, "scheme_name", "") or "")
        is_direct = getattr(item, "is_direct", None)
        if amount is None or isinstance(amount, bool):
            raise ValueError(f"Invalid SIP amount for recommendation {scheme!r}")
        try:
            amount_value = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid SIP amount for recommendation {scheme!r}") from exc
        if not math.isfinite(amount_value) or amount_value < 0:
            raise ValueError(f"SIP amount must be finite and non-negative for {scheme!r}")
        if amount_value == 0:
            continue
        if is_direct is not True:
            raise ValueError(
                f"Fiduciary Gate 10 Violation: '{scheme}' lacks verified is_direct=True metadata."
            )
        if "regular" in scheme.casefold():
            raise ValueError(
                f"Fiduciary Gate 10 Violation: Fresh SIP recommendation '{scheme}' is a Regular plan."
            )
    return True
