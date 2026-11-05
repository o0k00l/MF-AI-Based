"""
core/candidate_scoring.py
Institutional Multi-Factor Fiduciary Fund Scoring & Candidate Comparison Engine.

Evaluates candidate mutual funds across 6 objective, quantitative fiduciary pillars:
  1. Risk-Adjusted Alpha & Return (3Y Jensen's Alpha, 1Y Trailing Return, 6M Momentum)
  2. Sharpe Efficiency Ratio (3Y Sharpe Ratio, 1Y Sharpe Ratio)
  3. Direct Expense Ratio Efficiency (TER drag vs category benchmark / Morningstar Price Score)
  4. Downside Protection & Defensive Cushion (Cash, Sovereign Debt, Arbitrage)
  5. Geographic & International Diversification (Global/US equity mandate & currency hedge)
  6. Marginal Portfolio Benefit (MPB - Stock overlap penalty against surviving portfolio)
"""
from __future__ import annotations

import json
import math
import hashlib
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class ScoringWeights:
    """Configurable weights for institutional fiduciary scoring (sums to 1.0)."""
    # Weights are mandatory external policy inputs. Do not bake a composite
    # weighting scheme into the scoring code.
    w_alpha: float
    w_sharpe: float
    w_ter: float
    w_downside_buffer: float
    w_international: float
    w_mpb_overlap: float

    def validate(self) -> bool:
        values = (
            self.w_alpha, self.w_sharpe, self.w_ter,
            self.w_downside_buffer, self.w_international, self.w_mpb_overlap,
        )
        if any(isinstance(value, bool) for value in values):
            return False
        try:
            numeric = tuple(float(value) for value in values)
        except (TypeError, ValueError):
            return False
        if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in numeric):
            return False
        return abs(sum(numeric) - 1.0) < 1e-5


# ─────────────────────────────────────────────────────────────────────────────
# 1. CATEGORY BENCHMARK ANCHORS & WINSORIZATION BOUNDS
# ─────────────────────────────────────────────────────────────────────────────
# Regulatory and economic anchors to prevent universe-dependence (sample rank reversal)
_CATEGORY_ANCHORS_CACHE: Dict[str, Any] = {}


def load_category_benchmark_anchors(
    policy_path: Optional[Path] = None,
    force_reload: bool = False,
) -> Dict[str, Dict[str, Tuple[float, float]]]:
    """
    Loads approved category benchmark anchors from authoritative policy configuration.
    Binds policy version and digest, and validates 7-pillar metric bounds.
    """
    path = policy_path or (Path(__file__).resolve().parents[1] / "data" / "policy" / "category_benchmark_anchors.json")
    cache_key = str(path.resolve()) if path.exists() else str(path)
    if not force_reload and cache_key in _CATEGORY_ANCHORS_CACHE and policy_path is None:
        return _CATEGORY_ANCHORS_CACHE[cache_key]

    if not path.is_file():
        raise RuntimeError(f"Authoritative category benchmark anchors policy is missing at {path}")

    try:
        raw_bytes = path.read_bytes()
        data = json.loads(raw_bytes.decode("utf-8"))
        categories = data.get("categories", {})
        anchors_map: Dict[str, Dict[str, Tuple[float, float]]] = {}
        for cat_name, cat_data in categories.items():
            anchor_set = cat_data.get("anchor_set", {})
            cat_bounds: Dict[str, Tuple[float, float]] = {}
            for metric, bounds in anchor_set.items():
                cat_bounds[metric] = (float(bounds[0]), float(bounds[1]))
            anchors_map[cat_name] = cat_bounds
        _CATEGORY_ANCHORS_CACHE[cache_key] = anchors_map
        return anchors_map
    except Exception as exc:
        raise RuntimeError(f"Failed to load category benchmark anchors from {path}: {exc}") from exc


class _DynamicCategoryBenchmarkAnchors(dict):
    """Dynamic mapping resolving approved category anchors from authoritative policy configuration."""

    def _get_map(self):
        try:
            return load_category_benchmark_anchors()
        except Exception:
            return {}

    def __getitem__(self, item):
        m = self._get_map()
        if item in m:
            return m[item]
        raise KeyError(item)

    def __contains__(self, item):
        return item in self._get_map()

    def __iter__(self):
        return iter(self._get_map())

    def __len__(self):
        return len(self._get_map())

    def get(self, item, default=None):
        return self._get_map().get(item, default)

    def items(self):
        return self._get_map().items()

    def values(self):
        return self._get_map().values()

    def keys(self):
        return self._get_map().keys()


CATEGORY_BENCHMARK_ANCHORS = _DynamicCategoryBenchmarkAnchors()


def normalize_metric(val: Optional[float], val_min: float, val_max: float, invert: bool = False) -> float:
    """
    Min-Max normalizer bounded strictly to [0.0, 100.0].
    Handles zero-variance / equal-value degenerate cases (|val_max - val_min| < 1e-6)
    by returning a neutral baseline of 50.0.
    Supports inversion for cost (TER), downside capture, and stock overlap.
    """
    if val is None:
        return 0.0

    if isinstance(val, bool):
        raise ValueError("Scoring metric must be numeric, not boolean")
    if isinstance(val_min, bool) or isinstance(val_max, bool):
        raise ValueError("Scoring bounds must be numeric")
    try:
        v = float(val)
        lower = float(val_min)
        upper = float(val_max)
    except (TypeError, ValueError) as exc:
        raise ValueError("Scoring metric and bounds must be numeric") from exc
    if not all(math.isfinite(x) for x in (v, lower, upper)):
        raise ValueError("Scoring metric and bounds must be finite")
    if upper < lower:
        raise ValueError("Scoring upper bound cannot be below lower bound")
    val_clamped = min(max(v, lower), upper)
    range_span = upper - lower

    if range_span <= 1e-6:
        return 50.0  # Equal peer baseline

    norm = ((val_clamped - lower) / range_span) * 100.0
    res = 100.0 - norm if invert else norm
    return round(min(100.0, max(0.0, res)), 1)



_REQUIRED_ANCHOR_KEYS = frozenset({
    "alpha", "ret1y", "sharpe", "ter", "buffer", "intl", "overlap"
})


def _iso_date(raw: Any, field_name: str) -> date:
    if not isinstance(raw, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string") from exc
    if parsed.isoformat() != raw:
        raise ValueError(f"{field_name} must use canonical YYYY-MM-DD format")
    return parsed


def _validate_portfolio_score_evidence(
    candidate: Dict[str, Any],
    *,
    category_key: str,
    overlap_evidence: Optional[Dict[str, Any]],
    anchor_evidence: Optional[Dict[str, Any]],
    as_of_date: Optional[str],
    max_evidence_age_days: int,
) -> Tuple[float, Dict[str, Tuple[float, float]]]:
    """Require source-backed overlap and a complete approved category anchor set."""
    if isinstance(max_evidence_age_days, bool) or not isinstance(max_evidence_age_days, int) or max_evidence_age_days < 0:
        raise ValueError("max_evidence_age_days must be a non-negative integer")
    if as_of_date is None:
        raise ValueError("Portfolio-aware scoring requires an explicit decision as-of date")
    decision_date = _iso_date(as_of_date, "as_of_date")

    candidate_id = candidate.get("fund_id") or candidate.get("scheme_id") or candidate.get("id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("Portfolio-aware scoring requires a stable candidate identity")

    if not isinstance(overlap_evidence, dict) or overlap_evidence.get("status") != "VERIFIED":
        raise ValueError("Verified portfolio overlap evidence is required; missing overlap cannot receive a neutral score")
    if overlap_evidence.get("reviewer_attested") is not True:
        raise ValueError("Portfolio overlap evidence requires reviewer attestation")
    if overlap_evidence.get("candidate_id") != candidate_id:
        raise ValueError("Portfolio overlap evidence candidate identity mismatch")
    try:
        overlap_pct = float(overlap_evidence.get("overlap_pct"))
        coverage_pct = float(overlap_evidence.get("coverage_pct"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Portfolio overlap and look-through coverage must be numeric") from exc
    if not math.isfinite(overlap_pct) or not 0.0 <= overlap_pct <= 100.0:
        raise ValueError("Portfolio overlap must be finite and between 0 and 100")
    if not math.isfinite(coverage_pct) or not 99.5 <= coverage_pct <= 100.0:
        raise ValueError("Portfolio overlap look-through coverage must be at least 99.5 percent")
    overlap_bytes = overlap_evidence.get("source_bytes")
    overlap_digest = overlap_evidence.get("source_document_sha256")
    overlap_ref = overlap_evidence.get("source_ref")
    if not isinstance(overlap_bytes, bytes) or not overlap_bytes:
        raise ValueError("Original portfolio overlap source bytes are required")
    actual_overlap_digest = hashlib.sha256(overlap_bytes).hexdigest()
    if overlap_digest != actual_overlap_digest or overlap_ref != "sha256:" + actual_overlap_digest:
        raise ValueError("Portfolio overlap source digest does not match original bytes")
    overlap_date = _iso_date(overlap_evidence.get("as_of_date"), "overlap_evidence.as_of_date")
    overlap_age = (decision_date - overlap_date).days
    if overlap_age < 0 or overlap_age > max_evidence_age_days:
        raise ValueError("Portfolio overlap evidence is stale or future-dated")

    if not isinstance(anchor_evidence, dict) or anchor_evidence.get("status") != "APPROVED":
        raise ValueError("Independently approved category benchmark anchors are required")
    if anchor_evidence.get("reviewer_attested") is not True:
        raise ValueError("Category benchmark anchors require reviewer attestation")
    if anchor_evidence.get("category") != category_key:
        raise ValueError("Approved category anchor identity does not match candidate category")
    if not isinstance(anchor_evidence.get("benchmark_identity"), str) or not anchor_evidence["benchmark_identity"].strip():
        raise ValueError("Category anchor benchmark identity is required")
    for field_name in ("reviewer_id", "policy_version", "source_ref"):
        if not isinstance(anchor_evidence.get(field_name), str) or not anchor_evidence[field_name].strip():
            raise ValueError(f"Category anchor {field_name} is required")
    anchor_bytes = anchor_evidence.get("source_bytes")
    anchor_digest = anchor_evidence.get("source_document_sha256")
    if not isinstance(anchor_bytes, bytes) or not anchor_bytes:
        raise ValueError("Original category anchor source bytes are required")
    actual_anchor_digest = hashlib.sha256(anchor_bytes).hexdigest()
    if anchor_digest != actual_anchor_digest or anchor_evidence["source_ref"] != "sha256:" + actual_anchor_digest:
        raise ValueError("Category anchor source digest does not match original bytes")
    anchor_date = _iso_date(anchor_evidence.get("effective_date"), "category_anchor.effective_date")
    anchor_age = (decision_date - anchor_date).days
    if anchor_age < 0 or anchor_age > max_evidence_age_days:
        raise ValueError("Category anchor evidence is stale or future-dated")

    bounds = anchor_evidence.get("anchor_set")
    if not isinstance(bounds, dict) or set(bounds) != _REQUIRED_ANCHOR_KEYS:
        raise ValueError("Approved category anchor set must define every required metric bound")
    normalized_bounds: Dict[str, Tuple[float, float]] = {}
    for key in sorted(_REQUIRED_ANCHOR_KEYS):
        pair = bounds.get(key)
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"Category anchor {key} must have exactly two bounds")
        if any(isinstance(item, bool) for item in pair):
            raise ValueError(f"Category anchor {key} bounds must be numeric")
        try:
            lower, upper = float(pair[0]), float(pair[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Category anchor {key} bounds must be numeric") from exc
        if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
            raise ValueError(f"Category anchor {key} bounds must be finite and increasing")
        normalized_bounds[key] = (lower, upper)
    return overlap_pct, normalized_bounds


def calculate_candidate_6_pillar_score(
    cand: Dict[str, Any],
    category_key: str,
    portfolio_overlap_pct: Optional[float] = None,
    weights: Optional[ScoringWeights] = None,
    *,
    portfolio_aware: bool = False,
    portfolio_overlap_evidence: Optional[Dict[str, Any]] = None,
    approved_category_anchor_evidence: Optional[Dict[str, Any]] = None,
    as_of_date: Optional[str] = None,
    max_evidence_age_days: int = 45,
) -> Tuple[float, Dict[str, float]]:
    """
    Computes deterministic, reproducible 6-pillar score bounded in [0.0, 100.0].
    Pillar 1 blends 3Y Jensen's Alpha (60%) with 1Y Total Return (40%) to reward outperformance
    while capping momentum contribution to 25% of total score.
    """
    if not isinstance(category_key, str) or not category_key.strip():
        raise ValueError("Explicit approved category_key is required; defaulting to Healthcare is prohibited.")
    if not isinstance(weights, ScoringWeights):
        raise ValueError("Explicit approved scoring weights are required; no default composite is permitted.")

    # Issue #25: Mandatory eligibility gates must pass before scoring (strictly fail-closed)
    elig_status = cand.get("eligibility_status")
    is_eligible = cand.get("is_eligible")
    if elig_status not in ("PASS", "ELIGIBLE", "PASSED"):
        raise ValueError(f"Candidate '{cand.get('fund_id', 'unknown')}' has invalid, missing, or unvetted eligibility status ({elig_status!r}); scoring before positive eligibility is prohibited.")
    if is_eligible is not True:
        raise ValueError(f"Candidate '{cand.get('fund_id', 'unknown')}' does not have verified positive eligibility (is_eligible={is_eligible!r}); scoring before eligibility is prohibited.")

    approved_bounds: Optional[Dict[str, Tuple[float, float]]] = None
    verified_overlap_pct: Optional[float] = None
    if portfolio_aware:
        verified_overlap_pct, approved_bounds = _validate_portfolio_score_evidence(
            cand,
            category_key=category_key,
            overlap_evidence=portfolio_overlap_evidence,
            anchor_evidence=approved_category_anchor_evidence,
            as_of_date=as_of_date,
            max_evidence_age_days=max_evidence_age_days,
        )

    # Required selection metrics must be supplied explicitly. Zero is a valid
    # observation; missing, blank, boolean and non-finite values are not.
    def required_metric(*keys: str) -> float:
        raw = next((cand[key] for key in keys if key in cand), None)
        if raw is None or isinstance(raw, bool) or (isinstance(raw, str) and not raw.strip()):
            raise ValueError(f"Missing required scoring metric: {keys[0]}")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Malformed required scoring metric: {keys[0]}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Non-finite required scoring metric: {keys[0]}")
        return value

    alpha_3y = required_metric("alpha_3y", "alpha")
    ret_1y = required_metric("return_1y", "ret_1y")
    sharpe_3y = required_metric("sharpe_3y", "sharpe")
    ter = required_metric("ter_direct_pct", "er")

    if not weights.validate():
        raise ValueError("Scoring weights must be finite and sum to 1.0")

    if portfolio_aware:
        anchors = approved_bounds or {}
    else:
        if category_key not in CATEGORY_BENCHMARK_ANCHORS:
            raise ValueError(
                f"Unsupported scoring category {category_key!r}; refusing to substitute Healthcare anchors"
            )
        anchors = CATEGORY_BENCHMARK_ANCHORS[category_key]
        missing_anchor_keys = _REQUIRED_ANCHOR_KEYS - set(anchors)
        if missing_anchor_keys:
            raise ValueError(
                f"Category {category_key!r} has no complete approved anchor set; missing: "
                + ", ".join(sorted(missing_anchor_keys))
            )


    # Defensive, international and overlap pillars are required evidence.
    # A verified zero is a valid observation; missing evidence is not neutral.
    def optional_metric(*keys: str) -> Optional[float]:
        raw = next((cand[key] for key in keys if key in cand), None)
        if raw is None:
            return None
        if isinstance(raw, bool):
            raise ValueError(f"Malformed optional scoring metric: {keys[0]}")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Malformed optional scoring metric: {keys[0]}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Non-finite optional scoring metric: {keys[0]}")
        return value

    buffer_pct = optional_metric("cash_debt_buffer_pct", "debt")
    intl_pct = optional_metric("international_equity_pct")
    if buffer_pct is None:
        raise ValueError("Scoring requires verified cash/debt buffer evidence")
    if intl_pct is None:
        raise ValueError("Scoring requires verified international exposure evidence")
    overlap_raw = verified_overlap_pct if portfolio_aware else portfolio_overlap_pct
    if not portfolio_aware:
        if overlap_raw is None:
            overlap_raw = optional_metric("overlap_pct")
        elif isinstance(overlap_raw, bool):
            raise ValueError("Malformed portfolio overlap percentage")
        else:
            overlap_raw = float(overlap_raw)
            if not math.isfinite(overlap_raw):
                raise ValueError("Non-finite portfolio overlap percentage")
    if overlap_raw is None:
        raise ValueError("Scoring requires verified portfolio overlap evidence")
    for metric_name, metric_value in (
        ("cash/debt buffer", buffer_pct),
        ("international exposure", intl_pct),
        ("portfolio overlap", overlap_raw),
    ):
        if isinstance(metric_value, bool) or not 0.0 <= float(metric_value) <= 100.0:
            raise ValueError(f"{metric_name} percentage must be between 0 and 100")

    alpha_bounds = anchors["alpha"]
    ret_bounds = anchors["ret1y"]
    sharpe_bounds = anchors["sharpe"]
    ter_bounds = anchors["ter"]
    buf_bounds = anchors["buffer"]
    intl_bounds = anchors["intl"]
    ovl_bounds = anchors["overlap"]

    # 1. Alpha & Return Pillar (60% Alpha, 40% 1Y Return Momentum)
    p_alpha = normalize_metric(alpha_3y, alpha_bounds[0], alpha_bounds[1])
    # Negative and zero returns are valid observations and must score against
    # the return anchors; substituting alpha would hide a poor 1Y outcome.
    p_ret = normalize_metric(ret_1y, ret_bounds[0], ret_bounds[1])
    p_alpha_ret = round((p_alpha * 0.6) + (p_ret * 0.4), 1)

    # 2. Sharpe Volatility Efficiency Pillar
    p_sharpe = normalize_metric(sharpe_3y, sharpe_bounds[0], sharpe_bounds[1])

    # 3. Cost Discipline Pillar (Inverted: lower TER yields higher score)
    p_ter = normalize_metric(ter, ter_bounds[0], ter_bounds[1], invert=True)

    # 4. Capital Preservation & Defensive Buffer Pillar
    p_buf = normalize_metric(buffer_pct, buf_bounds[0], buf_bounds[1])

    # 5. Geographic Moat Pillar (Neutral 0.0 for pure domestic sectors)
    p_intl = normalize_metric(intl_pct, intl_bounds[0], intl_bounds[1])

    # 6. Marginal Portfolio Benefit / Overlap Inverted Pillar (lower overlap is better).
    # Only standalone diagnostics may use a neutral fallback; portfolio-aware
    # scores cannot reach this point without verified overlap source evidence.
    p_ovl = normalize_metric(overlap_raw, ovl_bounds[0], ovl_bounds[1], invert=True)

    pillars = {
        "alpha_return": p_alpha_ret,
        "sharpe_efficiency": p_sharpe,
        "cost_efficiency": p_ter,
        "downside_buffer": p_buf,
        "geographic_moat": p_intl,
        "portfolio_overlap": p_ovl
    }

    composite = (
        pillars["alpha_return"] * weights.w_alpha +
        pillars["sharpe_efficiency"] * weights.w_sharpe +
        pillars["cost_efficiency"] * weights.w_ter +
        pillars["downside_buffer"] * weights.w_downside_buffer +
        pillars["geographic_moat"] * weights.w_international +
        pillars["portfolio_overlap"] * weights.w_mpb_overlap
    )

    return round(composite, 1), pillars


def run_scoring_sensitivity_test(
    candidates: List[Dict[str, Any]],
    regimes: Dict[str, ScoringWeights],
    category_key: str = "Healthcare",
) -> Dict[str, Any]:
    """Evaluate only explicitly supplied, reviewed scoring-weight scenarios."""
    if not isinstance(regimes, dict) or not regimes:
        raise ValueError("Explicit, versioned scoring regimes are required")
    for name, weights in regimes.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(weights, ScoringWeights):
            raise ValueError("Every scoring regime requires a stable name and explicit ScoringWeights")
        if not weights.validate():
            raise ValueError(f"Scoring regime {name!r} has invalid or non-reconciling weights")

    results = {}
    for name, weights in regimes.items():
        ranked = []
        for candidate in candidates:
            score, _ = calculate_candidate_6_pillar_score(
                candidate, category_key, weights=weights
            )
            candidate_name = candidate.get(
                "scheme_name", candidate.get("fund_name", candidate.get("name", "Unknown"))
            )
            ranked.append({"name": candidate_name, "score": score})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        results[name] = ranked
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 2. MORNINGSTAR PRICE SCORE & MARGINAL PORTFOLIO BENEFIT (MPB)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_morningstar_price_score(ter_direct_pct: float, category_median_ter: float) -> float:
    delta_bps = (category_median_ter - ter_direct_pct) * 100
    multiplier = 1.0 + (delta_bps / 100.0) * 0.25
    return max(0.80, min(1.25, round(multiplier, 4)))


def compute_marginal_portfolio_benefit(
    base_score: float,
    overlap_pct: float,
    ter_direct_pct: float,
    category_median_ter: float,
) -> float:
    mps = calculate_morningstar_price_score(ter_direct_pct, category_median_ter)
    overlap_discount = max(0.0, 1.0 - (overlap_pct / 100.0))
    mpb = base_score * overlap_discount * mps
    return round(mpb, 2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. LEGACY DATACLASSES & CANDIDATE COMPARISONS (COMPATIBILITY HARNESS)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReverseFedModelResult:
    equity_yield_pct: float
    gsec_10y_yield_pct: float
    spread_pct: float
    valuation_verdict: str
    recommended_stp_months: int
    rationale: str


@dataclass
class FundScorecard:
    fund_id: str
    scheme_name: str
    category: str
    plan_type: str
    aum_crore: float
    ter_direct_pct: float
    alpha_3y: Optional[float]
    sharpe_3y: Optional[float]
    equity_pct: float
    debt_cash_buffer_pct: float
    has_international_exposure: bool
    international_exposure_details: str
    mid_small_cap_pct: float
    composite_score: float
    pillar_breakdown: Dict[str, float]
    pros: List[str]
    cons: List[str]
    fiduciary_verdict: str


class FiduciaryFundSelector:
    """Evaluates candidates using the institutional 6-pillar framework."""
    def __init__(self, fund_metrics_path: Optional[Path] = None, weights: Optional[ScoringWeights] = None):
        if fund_metrics_path is None:
            raise ValueError(
                "fund_metrics_path is required; defaulting to repository-local client data is prohibited."
            )
        self.fund_metrics_path = fund_metrics_path
        self.weights = weights
        self.fund_metrics = self._load_metrics()

    def _load_metrics(self) -> Dict[str, Any]:
        if not self.fund_metrics_path.is_file():
            raise FileNotFoundError(
                f"Required fund metrics evidence file is missing: {self.fund_metrics_path}"
            )
        try:
            with open(self.fund_metrics_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Fund metrics evidence file is unreadable or invalid JSON: {self.fund_metrics_path}"
            ) from exc

        if not isinstance(data, dict) or not isinstance(data.get("funds"), list):
            raise ValueError("Fund metrics evidence must contain a 'funds' list")

        indexed: Dict[str, Any] = {}
        for index, record in enumerate(data["funds"]):
            if not isinstance(record, dict):
                raise ValueError(f"Fund metrics record {index} must be an object")
            identity = str(record.get("id") or record.get("name") or "").strip()
            if not identity:
                raise ValueError(f"Fund metrics record {index} has no stable id or name")
            if identity in indexed:
                raise ValueError(f"Duplicate fund metrics identity: {identity}")
            indexed[identity] = record

        if not indexed:
            raise ValueError("Fund metrics evidence contains no fund records")
        return indexed

    def score_flexi_cap_candidates(self) -> Dict[str, FundScorecard]:
        """Retired hardcoded investor example; never return recommendation facts."""
        raise LegacyFundSelectorDisabledError(
            "The legacy named-fund selector is disabled. Use the source-verified "
            "candidate universe, approved scoring contract and portfolio-aware SIP service."
        )

    def get_comparison_summary(self) -> Dict[str, Any]:
        """Retired named-fund comparison path."""
        raise LegacyFundSelectorDisabledError(
            "The legacy named-fund comparison is disabled; no hardcoded fund ranking is available."
        )


class LegacyFundSelectorDisabledError(RuntimeError):
    """Raised by quarantined legacy fund recommendation interfaces."""
