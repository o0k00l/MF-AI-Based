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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class ScoringWeights:
    """Configurable weights for institutional fiduciary scoring (sums to 1.0)."""
    w_alpha: float = 0.25               # Risk-Adjusted Alpha & Return Pillar
    w_sharpe: float = 0.20              # Sharpe Volatility Efficiency Pillar
    w_ter: float = 0.15                 # Direct Plan Cost Efficiency Pillar (Inverted)
    w_downside_buffer: float = 0.15     # Capital Preservation & Defensive Buffer Pillar
    w_international: float = 0.15       # Geographic / International Moat Pillar
    w_mpb_overlap: float = 0.10         # Marginal Portfolio Benefit / Overlap Inverted Pillar

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
CATEGORY_BENCHMARK_ANCHORS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "Healthcare": {
        "alpha": (0.0, 10.0),       # Alpha % range
        "ret1y": (30.0, 52.0),      # 1Y return % range
        "sharpe": (0.70, 1.10),     # 3Y Sharpe ratio
        "ter": (0.50, 1.10),        # Direct TER %
        "buffer": (0.0, 10.0),      # Cash/Debt Buffer %
        "intl": (0.0, 25.0),        # International %
        "overlap": (0.0, 15.0)      # Look-through stock overlap % against portfolio
    },
    "Flexi Cap": {
        "alpha": (0.0, 8.0),
        "sharpe": (0.40, 1.20),
        "ter": (0.40, 1.20),
        "buffer": (0.0, 25.0),
        "intl": (0.0, 35.0),
        "overlap": (10.0, 50.0)
    },
    "Mid Cap": {
        "alpha": (0.0, 8.0),
        "sharpe": (0.40, 1.20),
        "ter": (0.40, 1.20),
        "buffer": (0.0, 15.0),
        "intl": (0.0, 10.0),
        "overlap": (5.0, 40.0)
    },
    "Large Cap": {
        "alpha": (0.0, 5.0),
        "sharpe": (0.40, 1.00),
        "ter": (0.10, 1.00),
        "buffer": (0.0, 15.0),
        "intl": (0.0, 10.0),
        "overlap": (20.0, 60.0)
    }
}


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


def calculate_candidate_6_pillar_score(
    cand: Dict[str, Any],
    category_key: str = "Healthcare",
    portfolio_overlap_pct: Optional[float] = None,
    weights: Optional[ScoringWeights] = None
) -> Tuple[float, Dict[str, float]]:
    """
    Computes deterministic, reproducible 6-pillar score bounded in [0.0, 100.0].
    Pillar 1 blends 3Y Jensen's Alpha (60%) with 1Y Total Return (40%) to reward outperformance
    while capping momentum contribution to 25% of total score.
    """
    if weights is None:
        weights = ScoringWeights()

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

    # Optional explanatory pillars are neutral when evidence is absent. They
    # must never be fabricated as zero, 12%, or another assumed observation.
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
    overlap_raw = portfolio_overlap_pct
    if overlap_raw is None:
        overlap_raw = optional_metric("overlap_pct")
    elif isinstance(overlap_raw, bool):
        raise ValueError("Malformed portfolio overlap percentage")
    else:
        overlap_raw = float(overlap_raw)
        if not math.isfinite(overlap_raw):
            raise ValueError("Non-finite portfolio overlap percentage")

    if not weights.validate():
        raise ValueError("Scoring weights must be finite and sum to 1.0")

    if category_key not in CATEGORY_BENCHMARK_ANCHORS:
        raise ValueError(
            f"Unsupported scoring category {category_key!r}; refusing to substitute Healthcare anchors"
        )
    anchors = CATEGORY_BENCHMARK_ANCHORS[category_key]
    alpha_bounds = anchors.get("alpha", (0.0, 10.0))
    ret_bounds = anchors.get("ret1y", (30.0, 52.0))
    sharpe_bounds = anchors.get("sharpe", (0.70, 1.10))
    ter_bounds = anchors.get("ter", (0.50, 1.10))
    buf_bounds = anchors.get("buffer", (0.0, 10.0))
    intl_bounds = anchors.get("intl", (0.0, 25.0))
    ovl_bounds = anchors.get("overlap", (0.0, 25.0))

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
    p_buf = 50.0 if buffer_pct is None else normalize_metric(buffer_pct, buf_bounds[0], buf_bounds[1])

    # 5. Geographic Moat Pillar (Neutral 0.0 for pure domestic sectors)
    p_intl = 50.0 if intl_pct is None else normalize_metric(intl_pct, intl_bounds[0], intl_bounds[1])

    # 6. Marginal Portfolio Benefit / Overlap Inverted Pillar (lower overlap is better)
    p_ovl = 50.0 if overlap_raw is None else normalize_metric(overlap_raw, ovl_bounds[0], ovl_bounds[1], invert=True)

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
    category_key: str = "Healthcare"
) -> Dict[str, Any]:
    """
    Stress-tests candidate rankings across 4 different weight regimes:
    1. Baseline Balanced: (0.25, 0.20, 0.15, 0.15, 0.15, 0.10)
    2. Cost-Heavy: (0.15, 0.15, 0.35, 0.15, 0.10, 0.10)
    3. Alpha/Momentum-Heavy: (0.35, 0.25, 0.10, 0.10, 0.10, 0.10)
    4. Capital Preservation-Heavy: (0.15, 0.20, 0.15, 0.30, 0.10, 0.10)
    """
    regimes = {
        "baseline": ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10),
        "cost_heavy": ScoringWeights(0.15, 0.15, 0.35, 0.15, 0.10, 0.10),
        "alpha_heavy": ScoringWeights(0.35, 0.25, 0.10, 0.10, 0.10, 0.10),
        "buffer_heavy": ScoringWeights(0.15, 0.20, 0.15, 0.30, 0.10, 0.10)
    }

    results = {}
    for name, w in regimes.items():
        ranked = []
        for c in candidates:
            score, pillars = calculate_candidate_6_pillar_score(c, category_key, weights=w)
            c_name = c.get("scheme_name", c.get("fund_name", c.get("name", "Unknown")))
            ranked.append({"name": c_name, "score": score})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        results[name] = ranked

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 2. MORNINGSTAR PRICE SCORE & MARGINAL PORTFOLIO BENEFIT (MPB)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_morningstar_price_score(ter_direct_pct: float, category_median_ter: float = 0.75) -> float:
    delta_bps = (category_median_ter - ter_direct_pct) * 100
    multiplier = 1.0 + (delta_bps / 100.0) * 0.25
    return max(0.80, min(1.25, round(multiplier, 4)))


def compute_marginal_portfolio_benefit(
    base_score: float,
    overlap_pct: float,
    ter_direct_pct: float,
    category_median_ter: float = 0.75
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
            fund_metrics_path = Path(__file__).resolve().parents[1] / "data" / "lalit_portfolio" / "fund_metrics.json"
        self.fund_metrics_path = fund_metrics_path
        self.weights = weights or ScoringWeights()
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
        results = {}
        # Parag Parikh Flexi Cap Direct
        ppfas_raw = self.fund_metrics.get("PPFAS Flexi Cap", {})
        ppfas_score, ppfas_pillars = calculate_candidate_6_pillar_score(ppfas_raw, "Flexi Cap", weights=self.weights)
        results["ppfas_flexi"] = FundScorecard(
            fund_id="PPFAS Flexi Cap",
            scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            category="Flexi Cap",
            plan_type="Direct",
            aum_crore=float(ppfas_raw.get("aum_crore", 147404)),
            ter_direct_pct=float(ppfas_raw.get("ter_direct_pct", 0.69)),
            alpha_3y=float(ppfas_raw.get("alpha_3y", 3.83)),
            sharpe_3y=float(ppfas_raw.get("sharpe_3y", 0.64)),
            equity_pct=82.25,
            debt_cash_buffer_pct=17.75,
            has_international_exposure=True,
            international_exposure_details="Holds US tech leaders (Alphabet, Meta, Microsoft); provides USD currency hedge.",
            mid_small_cap_pct=7.61,
            composite_score=ppfas_score,
            pillar_breakdown=ppfas_pillars,
            pros=["Lowest direct expense ratio in category (0.69%).", "Built-in 17.8% defensive cushion."],
            cons=["Foreign investment cap restricts new US deployment."],
            fiduciary_verdict="RECOMMENDED FOR BALANCED COMPOUNDING & DOWNSIDE PROTECTION"
        )

        # HDFC Flexi Cap Direct
        hdfc_raw = self.fund_metrics.get("HDFC Flexi Cap", {})
        hdfc_score, hdfc_pillars = calculate_candidate_6_pillar_score(hdfc_raw, "Flexi Cap", weights=self.weights)
        results["hdfc_flexi"] = FundScorecard(
            fund_id="HDFC Flexi Cap",
            scheme_name="HDFC Flexi Cap Fund - Direct Plan - Growth Option",
            category="Flexi Cap",
            plan_type="Direct",
            aum_crore=float(hdfc_raw.get("aum_crore", 113606)),
            ter_direct_pct=float(hdfc_raw.get("ter_direct_pct", 0.77)),
            alpha_3y=float(hdfc_raw.get("alpha_3y", 5.27)),
            sharpe_3y=float(hdfc_raw.get("sharpe_3y", 0.66)),
            equity_pct=94.89,
            debt_cash_buffer_pct=5.11,
            has_international_exposure=False,
            international_exposure_details="0% International Exposure (100% domestic Indian securities).",
            mid_small_cap_pct=24.48,
            composite_score=hdfc_score,
            pillar_breakdown=hdfc_pillars,
            pros=["Superior 3-year trailing alpha (+5.27%).", "Reuses verified Folio #44678193."],
            cons=["Zero foreign exposure.", "AUM bloat > ₹1,13,000 Cr."],
            fiduciary_verdict="RECOMMENDED FOR DOMESTIC HIGH-BETA ALPHA"
        )

        return results

    def get_comparison_summary(self) -> Dict[str, Any]:
        scores = self.score_flexi_cap_candidates()
        p = scores["ppfas_flexi"]
        h = scores["hdfc_flexi"]
        return {
            "scores": scores,
            "winner_overall": "ppfas_flexi" if p.composite_score >= h.composite_score else "hdfc_flexi"
        }
