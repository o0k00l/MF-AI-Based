# pytest: no_rewrite
"""
Decision engine: applies the published screening criteria to a fund's metrics.

The criteria file (.agents/knowledge/fund_screening_criteria.json) is the single
source of truth. Rule text lives there, not here, so that the policy an adviser
reads is exactly the policy the machine applies. This module only interprets the
tiny test grammar used by that file.

Two properties matter more than speed:

1. MISSING is a first-class verdict. A missing input never silently becomes a
   pass and never silently becomes a fail; it makes the conclusion INCONCLUSIVE
   and names the field that is absent.
2. REJECT is a blocking verdict. It must be resolved or explicitly overridden
   in writing before a fund is recommended.

Nothing here may be bypassed by a caller that wants a cleaner answer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date, datetime
from typing import Dict, List, Optional, Any, FrozenSet

# Import evidence catalogue
from engine.evidence_catalogue import EvidenceCatalogue, EvidenceQuality, DecisionBlocking

# Import models for RuleClassification (ARCH-GAP-02)
from engine.models import RuleFinding, RuleClassification
from decimal import Decimal
logger = logging.getLogger(__name__)

# Logging constants
OK, BAD, WARN, INFO = "[ok]", "[!!]", "[..]", "[..]"

class PolicyError(Exception):
    """Raised when required policy data is missing or malformed."""
    pass


KNOWLEDGE = Path(__file__).resolve().parents[1] / ".agents" / "knowledge"

def _load_severities() -> dict[str, int]:
    try:
        data = json.loads((KNOWLEDGE / "fund_screening_criteria.json").read_text(encoding="utf-8"))
        if "verdict_severities" in data:
            return data["verdict_severities"]
    except Exception as e:
        logger.warning(r"Failed to load verdict severities: {e}")
    return {"REJECT": 3, "QUARANTINE": 2, "CONSOLIDATE_CANDIDATE": 2,
            "FLAG": 1, "DISCOUNT_TRACK_RECORD": 1, "PASS": 0, "INCONCLUSIVE": 0}

# verdict ordering, worst first. Loaded from policy JSON per Requirement 2.1a.
SEVERITY = _load_severities()

_CMP = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}
# Test grammar: ``field OP value`` joined by AND, where value is a number or a
# boolean literal. Deliberately tiny so that a policy author cannot smuggle
# executable logic into the criteria file.
_VALUE = r"(?i:true|false|[-+]?\d+(?:\.\d+)?)"
_TOKEN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|==|!=|<|>)\s*(" + _VALUE + r")")


def _as_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "y", "1"}
    return bool(v)


def load_criteria(path: Path | None = None) -> dict:
    """Load the screening policy. Path is overridable for tests."""
    p = path or KNOWLEDGE / "fund_screening_criteria.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def load_tax_rules(path: Path | None = None) -> dict:
    p = path or KNOWLEDGE / "tax_rules_india.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def load_asset_allocation_policy(path: Path | None = None) -> dict:
    p = path or KNOWLEDGE / "asset_allocation_policy.json"
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


@dataclass
class Finding:
    rule_id: str
    action: str
    rationale: str = ""
    detail: str = ""
    rule_classification: str = "RESEARCH_HEURISTIC"  # STATUTORY, INVESTOR_POLICY, RESEARCH_HEURISTIC

    @property
    def is_flag(self) -> bool:
        """Non-blocking advisory finding (CAUTION)."""
        return self.action in {"FLAG", "DISCOUNT_TRACK_RECORD",
                               "CONSOLIDATE_CANDIDATE"}

    @property
    def is_blocking(self) -> bool:
        """Blocking finding (CRITICAL): must be resolved before recommendation."""
        return self.action in {"REJECT", "QUARANTINE"}


@dataclass
class ScreenResult:
    fund_id: str
    verdict: str = "PASS"  # Legacy field, kept for compatibility
    fund_quality: str = "PASS"  # APPROVED, MONITOR, INCONCLUSIVE, REJECT
    portfolio_action: str = "HOLD"  # BUY, HOLD, STOP SIP, SWITCH, EXIT
    confidence_score: float = 0.0  # 0 to 100
    findings: list[Finding] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    benchmark_basis: str | None = None
    metrics: dict = field(default_factory=dict)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.is_blocking]

    def calculate_confidence(self, metrics: dict):
        """
        Calculate evidence confidence score (0-100).
        Based on presence of critical fiduciary metrics and data freshness.
        """
        critical_fields = [
            "benchmark_delta_3y", "benchmark_delta_5y",
            "rolling_3y_beat_rate", "down_capture", "up_capture",
            "sharpe_3y", "fund_manager_tenure_years", "ter_direct_pct"
        ]
        present = [f for f in critical_fields if metrics.get(f) is not None]
        base_score = (len(present) / len(critical_fields)) * 100
        
        # Data Freshness Penalty
        # Any metric ending in '_as_of' is expected to be an ISO date string (YYYY-MM-DD)
        stale_penalty = 0.0
        as_of_fields = [v for k, v in metrics.items() if k.endswith("_as_of") and v]
        if as_of_fields:
            try:
                # Use the oldest date if multiple are present
                dates = []
                for d_str in as_of_fields:
                    try:
                        dates.append(datetime.fromisoformat(str(d_str)).date())
                    except Exception:
                        print(f"  {WARN} Failed to parse date string: %s", d_str)
                        continue
                if dates:
                    oldest = min(dates)
                    age_days = (date.today() - oldest).days
                    staleness_cfg = load_criteria().get("staleness_policy", {})
                    penalties = sorted(staleness_cfg.get("confidence_penalties", []),
                                       key=lambda p: p.get("min_age_days", 0))
                    for p in penalties:
                        if age_days > p.get("min_age_days", 0):
                            stale_penalty = float(p.get("penalty_pts", 0.0))
            except Exception as e:
                logger.warning(r"Staleness check failed: {e}")
        self.confidence_score = max(0.0, base_score - stale_penalty)

    def to_dict(self) -> dict:
        return {
            "fund_id": self.fund_id,
            "verdict": self.verdict,
            "findings": [
                {"rule_id": f.rule_id, "action": f.action,
                 "rationale": f.rationale, "detail": f.detail}
                for f in self.findings
            ],
            "missing_fields": self.missing,
            "blocking": [f.rule_id for f in self.blocking],
        }


def _eval_clause(clause: str, metrics: dict) -> tuple[bool, list[str]]:
    m = _TOKEN.search(clause.strip())
    if not m:
        raise ValueError(f"unsupported test clause: {clause.strip()!r}")
    name, op, raw = m.group(1), m.group(2), m.group(3).lower()
    if name not in metrics or metrics[name] is None:
        return False, [name]
    lhs = metrics[name]
    if raw in {"true", "false"}:
        rhs = raw == "true"
        lhs = _as_bool(lhs)
    else:
        rhs = float(raw)
        lhs = float(lhs)
    return _CMP[op](lhs, rhs), []


def _eval(test: str, metrics: dict) -> tuple[bool, list[str]]:
    """
    Evaluate a criterion test string.

    Grammar supports clauses joined by 'OR' (any true) or 'AND' (all true),
    each clause of the form ``field OP value``. Returns (result, fields_referenced).
    Raises if the grammar is violated so a malformed policy cannot pass silently.
    """
    if " OR " in test:
        missing: list[str] = []
        result = False
        for part in test.split(" OR "):
            r, miss = _eval(part.strip(), metrics)
            missing.extend(miss)
            result = result or r
        return result, missing

    missing: list[str] = []
    result = True
    for clause in test.split("AND"):
        r, miss = _eval_clause(clause, metrics)
        missing.extend(miss)
        result = result and r
    return result, missing
def screen_fund(fund_id: str, metrics: dict, criteria: dict | None = None,
                portfolio_weight_pct: float | None = None,
                untrusted: frozenset | set = frozenset(),
                tri_proxy: dict | None = None,
                is_held: bool = False,
                fund_name: str | None = None) -> ScreenResult:
    """
    Screen one fund. ``metrics`` keys are the canonical metric names used in
    fund_screening_criteria.json.

    ``untrusted`` names fields whose provenance is known to be deficient, for
    example overlay entries marked ``proxy_not_tri``. Those fields are treated as
    MISSING for rule evaluation rather than as evidence.

    This matters most for the benchmark rules. A price index excludes dividends
    while a fund NAV reinvests them, so comparing the two flatters the fund by
    roughly the index dividend yield. Trusting such a figure would let a genuine
    underperformer pass the gate on a measurement artefact. An untrusted field
    produces INCONCLUSIVE, never a pass.
    """
    crit = criteria or load_criteria()
    res = ScreenResult(fund_id=fund_id)
    m = dict(metrics)

    # A few rules depend on the client portfolio, not just the fund.
    if portfolio_weight_pct is not None:
        m["portfolio_weight_pct"] = portfolio_weight_pct
    if is_held is not None:
        m["is_held"] = is_held

    all_missing: list[str] = []
    # Check conditional requirements based on category
    conditional_reqs = crit.get("data_sufficiency", {}).get("conditional_requirements", {})
    # m.get returns None both when the key is missing and when its value is
    # None. Either means "no category known", so coerce to "" before .lower().
    fund_cat = m.get("category") or ""

    for metric, requirements in conditional_reqs.items():
        if fund_cat in requirements.get("mandatory_for", []):
            if metric not in m or m[metric] is None:
                all_missing.append(metric)

    # Benchmark identity requirement (Requirement 3.2, fund_metrics_schema.json:43)
    # TRAP-01 / GAP-150 FIX: If benchmark_id is missing but category is known,
    # resolve the statutory SEBI TRI benchmark proxy (e.g. NIFTY MIDCAP 150 TRI for Mid Cap).
    if not m.get("benchmark_id") and fund_cat:
        try:
            from engine.benchmark import _resolve_benchmark_for_category
            resolved_bench = _resolve_benchmark_for_category(fund_cat, None)
            if resolved_bench:
                m["benchmark_id"] = resolved_bench
                m["_benchmark_inferred"] = True
        except Exception as e:
            logger.warning(r"Benchmark identity resolution failed: {e}")

    if not m.get("benchmark_id"):
        if "benchmark_id" not in all_missing:
            all_missing.append("benchmark_id")
        res.findings.append(Finding(
            rule_id="BENCHMARK_IDENTITY_MISSING",
            action="INCONCLUSIVE",
            rationale="Missing benchmark identity (TRI index): no relative claim may be made per fiduciary mandate",
            detail="benchmark_id missing",
            rule_classification="STATUTORY",
        ))

    # Handle Thematic IMMEDIATE_EXIT
    cat_rules = crit.get("category_rules") or crit.get("data_sufficiency", {}).get("category_rules") or {}
    thematic_rule = cat_rules.get("thematic_sectoral_liquidation", {})
    cat_l = fund_cat.lower()
    # GAP-DEEP-04 FIX: Also match "sectoral" since SEBI categories like
    # "Sectoral - Technology" don't contain "thematic" and bypassed RULE-M8.
    if ("thematic" in cat_l or "sectoral" in cat_l) and thematic_rule.get("action") == "IMMEDIATE_EXIT":
        res.findings.append(Finding("RULE-M8", "REJECT", thematic_rule.get("rationale", "Thematic/Sectoral fund detected: IMMEDIATE_EXIT enforced"), "Thematic/Sectoral", rule_classification="INVESTOR_POLICY"))



    # An untrusted price-index comparison is normally deleted, which is the
    # safe answer but throws away something usable. Subtracting the index
    # dividend yield turns it into a LOWER BOUND on the true TRI delta:
    # measuring against the adjusted figure can only understate performance,
    # so if the lower bound clears a threshold the fund genuinely clears it.
    # A lower bound that merely fails proves nothing, and must not reject.
    if tri_proxy:
        adj = apply_tri_adjustment(tri_proxy["delta_pct"],
                                   tri_proxy["horizon_years"],
                                   tri_proxy["index_dividend_yield_pct"])
        m["benchmark_delta_pct_lower_bound"] = adj["adjusted"]
        m["benchmark_basis"] = "tri_lower_bound"
        # adjusted is conservative by construction: it can only understate a
        # fund, so a pass on this figure is provable and a fail is not.
        if tri_proxy.get("key") in untrusted:
            m.pop("benchmark_delta_pct_lower_bound", None)
            all_missing.append("benchmark_delta_pct")

    #: a pass here is provable; a fail is not, because the figure can only
    #: understate a fund.
    res.benchmark_basis = m.get("benchmark_basis")

    # Drop untrusted values so they read as MISSING rather than as evidence.
    for name in untrusted:
        if name in m:
            del m[name]
            if name not in all_missing:
                all_missing.append(name)
    # Evidence readiness check using Evidence Catalogue
    catalogue = EvidenceCatalogue()
    # Determine fields to check: union of blocking fields for fund_quality and overlap_analysis
    fields_to_check = set()
    for decision_type in ["fund_quality", "overlap_analysis"]:
        decision = catalogue.decisions.get(decision_type)
        if decision:
            fields_to_check.update(decision["blocking_fields"])
    # Compute evidence quality for each field
    available_evidence = {}
    for field in fields_to_check:
        # Check if field is present in m and not None (resolving schema aliases)
        field_val = None
        if field == "scheme_identity":
            field_val = m.get("scheme_identity") or m.get("id") or m.get("name") or fund_id
        elif field == "holdings_data":
            field_val = m.get("holdings_data") or m.get("holdings_top10") or m.get("h") or m.get("holdings")
        elif field == "returns_1y_3y_5y":
            for k in ("returns_1y_3y_5y", "returns", "cagr_3y", "cagr_1y", "cagr_5y",
                      "rolling_3y_beat_rate", "benchmark_delta_3y"):
                if m.get(k) is not None:
                    field_val = m[k]
                    break
        else:
            field_val = m.get(field)

        if field_val is not None:
            # Check for staleness if there is an associated _as_of field
            as_of_val = None
            as_candidates = [field + "_as_of"]
            if field == "holdings_data":
                as_candidates.extend(["top10_holdings_as_of", "h_as_of", "as_of_holdings", "as_of"])
            elif field == "returns_1y_3y_5y":
                as_candidates.extend(["returns_as_of", "performance_as_of", "as_of"])
            for c_as in as_candidates:
                if c_as in m and m[c_as] is not None:
                    as_of_val = m[c_as]
                    break

            if as_of_val is not None:
                try:
                    as_of_str = str(as_of_val).split("T")[0]
                    as_of_date = datetime.fromisoformat(as_of_str).date()
                    age_days = (date.today() - as_of_date).days
                    # Get max_age_days from the requirement (if available)
                    max_age = None
                    for decision_type in ["fund_quality", "overlap_analysis"]:
                        decision = catalogue.decisions.get(decision_type)
                        if decision and field in decision["requirements"]:
                            max_age = decision["requirements"][field].max_age_days
                            break
                    if max_age is not None and age_days > max_age:
                        available_evidence[field] = EvidenceQuality.STALE
                    else:
                        available_evidence[field] = EvidenceQuality.VERIFIED
                except Exception as e:
                    logger.warning(r"Date parsing failed for evidence field {field}: {e}")
                    available_evidence[field] = EvidenceQuality.MISSING
            else:
                # No _as_of field, assume it's current if present
                available_evidence[field] = EvidenceQuality.VERIFIED
        else:
            available_evidence[field] = EvidenceQuality.MISSING
    # Validate each decision
    for decision_type in ["fund_quality", "overlap_analysis"]:
        validation_result = catalogue.validate(decision_type, available_evidence)
        if not validation_result["valid"]:
            for field in validation_result["blocking_gaps"]:
                # Get the consequence from the requirement
                consequence = "Evidence missing or insufficient"
                for dec_type in ["fund_quality", "overlap_analysis"]:
                    decision = catalogue.decisions.get(dec_type)
                    if decision and field in decision["requirements"]:
                        consequence = decision["requirements"][field].consequence_if_missing
                        break
                finding = Finding(
                    rule_id=f"EVIDENCE_GAP_{field.upper()}",
                    action="INCONCLUSIVE",
                    rationale=f"Evidence gap: {field} - {consequence}",
                    detail=f"Field {field} is {available_evidence[field].value}",
                    rule_classification="STATUTORY",
                )
                res.findings.append(finding)

    for rule in crit.get("reject_rules", []) + crit.get("flag_rules", []):
        rid, test = rule["id"], rule.get("test", "")
        action = rule.get("action", "FLAG")
        rule_classification = rule.get("rule_classification", "RESEARCH_HEURISTIC")

        if test == "category_specific":
            ok, detail = _aum_out_of_band(rule, m)
            if ok:
                res.findings.append(
                    Finding(rid, action, rule.get("rationale", ""), detail, rule_classification=rule_classification))
            continue

        # A rule may be scoped to certain categories. If the category is
        # unknown the rule cannot be judged, so it is reported as missing
        # rather than quietly skipped.
        cats = rule.get("applies_to_categories") or rule.get("categories")
        if cats is not None:
            cat = m.get("category")
            if cat is None:
                if "category" not in all_missing:
                    all_missing.append("category")
                continue
            cat_norm = str(cat).lower().replace("&", "and").strip()
            cats_norm = [str(c).lower().replace("&", "and").strip() for c in cats]
            matched = any(c == cat_norm or c in cat_norm or cat_norm in c for c in cats_norm)
            if not matched:
                continue


        try:
            ok, missed = _eval(test, m)
        except ValueError as exc:                     # malformed policy
            raise ValueError(f"rule {rid}: {exc}") from exc

        for name in missed:
            if name not in all_missing:
                all_missing.append(name)

        if ok:
            detail = _describe(test, m)
            if rid == "OVERLAP_HIGH" and portfolio_weight_pct is not None:
                detail = f"{detail} (weight {portfolio_weight_pct:.1f}%)"
            res.findings.append(
                Finding(rid, action, rule.get("rationale", ""), detail, rule_classification=rule_classification))

    res.missing = sorted(all_missing)
    res.verdict = reduce_verdict([f.action for f in res.findings])

    # GAP-ENG-03 FIX: When category is blank/unmapped, enforce mandatory baseline
    # even if res.missing is empty (no rules ran). A blank fund with zero data
    # must NOT receive a clean PASS.
    if not res.findings:
        mandatory_for_cat = set()
        fund_cat = fund_cat or ""

        # If category is blank or unmapped, enforce a mandatory baseline
        if not fund_cat.strip():
            mandatory_for_cat = {"aum_cr", "ter_direct_pct", "benchmark_id", "category"}
            # Add missing mandatory fields to res.missing
            for field in mandatory_for_cat:
                val = m.get(field)
                if field in ("aum_cr", "aum_crore") and val is None:
                    val = m.get("aum_crore") or m.get("aum_cr")
                if field not in res.missing and val is None:
                    res.missing.append(field)
        else:
            for mand_cat, ml in crit.get("data_sufficiency", {}).get("conditional_requirements", {}).get("mandatory_for", {}).items():
                mand_lower = mand_cat.lower()
                fund_lower = fund_cat.lower()
                # Match if: exact match, or both contain "index", or mand_cat is contained in fund_cat (e.g., "Large Cap" in "Index - Large Cap")
                if (mand_lower == fund_lower or
                    ("index" in mand_lower and "index" in fund_lower) or
                    mand_lower in fund_lower):
                    mandatory_for_cat.update(ml)

        # Define statutory mandatory fields that are blocking if missing
        STATUTORY_MANDATORY_FIELDS = {
            "aum_cr", "aum_crore", "ter_direct_pct", "er", "fund_manager_tenure_years", "benchmark_id"
        }

        # Fields that are KNOWN to be unavailable from mfapi.in (require overlay)
        # If overlay is missing, don't force INCONCLUSIVE for these - flag as MISSING with note
        FIELDS_REQUIRING_OVERLAY = {
            "aum_cr", "aum_crore", "ter_direct_pct", "er", "fund_manager_tenure_years", "benchmark_id", "category"
        }

        all_conditional = set()
        for ml in crit.get("data_sufficiency", {}).get("conditional_requirements", {}).get("mandatory_for", {}).values():
            all_conditional.update(ml)
        for ml in crit.get("data_sufficiency", {}).get("conditional_requirements", {}).get("optional_for", {}).values():
            all_conditional.update(ml)

        # Check if this fund has overlay data
        has_overlay = m.get("_has_overlay", False)

        # A missing field is blocking ONLY if:
        # 1. It's in STATUTORY_MANDATORY_FIELDS AND fund has overlay, OR
        # 2. It's in mandatory_for_cat for this category
        # Advisory metrics (sortino_3y, recovery_days, riskometer_score, fund_age_years, etc.) 
        # are recorded in res.missing for transparency but do NOT trigger INCONCLUSIVE
        # For funds WITHOUT overlay, don't force INCONCLUSIVE for fields known to require overlay
        blocking_missing = []
        for m_name in res.missing:
            if m_name in mandatory_for_cat:
                blocking_missing.append(m_name)
            elif m_name in STATUTORY_MANDATORY_FIELDS:
                if has_overlay:
                    blocking_missing.append(m_name)
                # else: fund has no overlay, this field requires overlay - don't block, just note as MISSING
        
        if blocking_missing:
            res.verdict = "INCONCLUSIVE"
        else:
            res.verdict = "PASS" 
        
    # Rule 15: Qualitative Verification Mandate (Manager Change Override)
    if any(f.action == "DISCOUNT_TRACK_RECORD" for f in res.findings):
        if res.verdict in ("REJECT", "SELL", "REPLACE"):
            # Check if probation period has expired (365 days from override)
            probation_key = "probation_" + res.fund_id
            probation_expiry = res.metrics.get(probation_key)
            if probation_expiry:
                try:
                    from datetime import date
                    expiry_date = date.fromisoformat(probation_expiry)
                    if date.today() > expiry_date:
                        # Probation expired, lift the shield
                        pass
                    else:
                        res.verdict = "HOLD + STOP SIP"
                        res.findings.append(Finding("RULE_15_MANAGER_OVERRIDE", "HOLD + STOP SIP", "Historical underperformance belongs to previous manager. Awaiting new manager track record.", "", rule_classification="INVESTOR_POLICY"))
                        return res
                except Exception as e:
                    logger.warning(r"Probation date parsing failed: {e}")
            else:
                # No probation expiry set, set it to 365 days from now
                res.metrics[probation_key] = str(date.today().replace(year=date.today().year + 1))
            res.verdict = "HOLD + STOP SIP"
            res.findings.append(Finding("RULE_15_MANAGER_OVERRIDE", "HOLD + STOP SIP", "Historical underperformance belongs to previous manager. Awaiting new manager track record.", "", rule_classification="INVESTOR_POLICY"))
            return res
            
    # GAP-157: SEBII Categorization Mandate Style Drift Check
    is_drift, drift_reason = check_sebi_mandate_style_drift(fund_cat, m)
    if is_drift:
        res.findings.append(Finding("STYLE_DRIFT_DETECTED", "REJECT", "SEBI mandate style drift detected.", drift_reason, rule_classification="STATUTORY"))
        res.verdict = reduce_verdict([f.action for f in res.findings])

    # GAP-120 / GAP-193: Wire FivePillarsEvaluator directly into primary screening loop
    try:
        from engine.five_pillars import FivePillarsEvaluator
        evaluator = FivePillarsEvaluator()
        eval_res = evaluator.evaluate_from_metrics(res.fund_id, m.get("id", res.fund_id), m)
        res.metrics["five_pillars"] = eval_res.report_section
        if eval_res.veto_activated:
            res.findings.append(Finding("FIVE_PILLARS_VETO", "REJECT", "Morningstar 5-Pillars Fiduciary Veto Activated.", eval_res.people.justification, rule_classification="RESEARCH_HEURISTIC"))
            res.verdict = reduce_verdict([f.action for f in res.findings])
    except Exception as e:
            logger.warning(r"Five Pillars evaluation failed: {e}")

    # Populating new two-tier verdicts and confidence
    res.fund_quality = map_quality(res.verdict)
    res.portfolio_action = derive_action(res.fund_quality, m, is_held=is_held)
    res.calculate_confidence(m)

    return res


# ---------------------------------------------------------------------------
# SEBI Style Drift & Category Quintile Percentile Ranking (GAP-157, GAP-177)
# ---------------------------------------------------------------------------

def check_sebi_mandate_style_drift(category: str, metrics: dict) -> Tuple[bool, str]:
    """Logic 3.13 / GAP-157: SEBI Categorization Style Drift Detection (Mandate Tracking).
    Checks market cap percentages against statutory floors.
    
    Thresholds are loaded from asset_allocation_policy.json (allocation_thresholds section)
    to maintain single-source-of-truth configuration.
    """
    cat = (category or "").lower()
    # GAP-251 FIX: Support both portfolio_* and short alias keys
    lc = float(
        metrics.get("portfolio_large_cap_pct") 
        or metrics.get("large_cap_pct") 
        or metrics.get("lc") 
        or 0.0
    )
    mc = float(
        metrics.get("portfolio_mid_cap_pct") 
        or metrics.get("mid_cap_pct") 
        or metrics.get("mc") 
        or 0.0
    )
    sc = float(
        metrics.get("portfolio_small_cap_pct") 
        or metrics.get("small_cap_pct") 
        or metrics.get("sc") 
        or 0.0
    )

    # Only evaluate if market cap breakdown is present
    if lc + mc + sc <= 0.01:
        return False, ""

    # Load thresholds from policy (single source of truth)
    thresholds = load_asset_allocation_policy().get("allocation_thresholds", {})
    large_floor = thresholds.get("large_cap_statutory_floor_pct", 80.0)
    mid_floor = thresholds.get("mid_cap_statutory_floor_pct", 65.0)
    small_floor = thresholds.get("small_cap_statutory_floor_pct", 65.0)
    multi_floor = thresholds.get("multi_cap_statutory_floor_pct", 25.0)

    if "large cap" in cat and "mid" not in cat and "flexi" not in cat and "multi" not in cat:
        if lc < large_floor:
            return True, f"Large Cap mandate breach: Large cap holding is {lc:.1f}% (statutory floor is {large_floor:.1f}%). Style drift detected."
    elif "mid cap" in cat and "small" not in cat and "large" not in cat:
        if mc < mid_floor:
            return True, f"Mid Cap mandate breach: Mid cap holding is {mc:.1f}% (statutory floor is {mid_floor:.1f}%). Style drift detected."
    elif "small cap" in cat:
        if sc < small_floor:
            return True, f"Small Cap mandate breach: Small cap holding is {sc:.1f}% (statutory floor is {small_floor:.1f}%). Style drift detected."
    elif "multi cap" in cat:
        if lc < multi_floor or mc < multi_floor or sc < multi_floor:
            return True, f"Multi Cap mandate breach: Allocation (L:{lc:.1f}%, M:{mc:.1f}%, S:{sc:.1f}%) breaches {multi_floor:.1f}/{multi_floor:.1f}/{multi_floor:.1f} statutory floor. Style drift detected."

    return False, ""


def compute_category_quintile_rankings(
    category_funds: list[dict],
    metric_key: str = "rolling_return_3y",
) -> dict[str, dict]:
    """Logic 4.3 / GAP-177: Category-Relative Quintile Percentile Ranking.
    Ranks peer universe (N >= 5) 1 to 5 Stars based on performance/risk-adjusted metric:
      - 5 Stars: Top 10% (>= 90th percentile)
      - 4 Stars: Next 22.5% (67.5th to 90th percentile)
      - 3 Stars: Middle 35% (32.5th to 67.5th percentile)
      - 2 Stars: Next 22.5% (10th to 32.5th percentile)
      - 1 Star: Bottom 10% (< 10th percentile)
    """
    if len(category_funds) < 5:
        # Insufficient peer size for robust quintile ranking
        return {
            f.get("id", str(i)): {
                "star_rating": 3,
                "percentile": 50.0,
                "quintile": "Average",
                "action": "HOLD",
            }
            for i, f in enumerate(category_funds)
        }

    valid_funds = []
    for f in category_funds:
        val = f.get(metric_key) or f.get("sharpe_3y") or f.get("cagr_3y_pct") or 0.0
        try:
            val = float(val)
        except Exception as e:
            logger.warning(r"Failed to convert metric to float: {e}")
            val = 0.0
        valid_funds.append((f.get("id"), val, f))

    valid_funds.sort(key=lambda x: x[1])
    n = len(valid_funds)
    rankings: dict[str, dict] = {}

    for rank_idx, (fid, val, fund_dict) in enumerate(valid_funds):
        pct = (rank_idx / (n - 1)) * 100.0 if n > 1 else 50.0
        if pct >= 90.0:
            stars = 5
            q_name = "Top 10%"
            act = "PASS"
        elif pct >= 67.5:
            stars = 4
            q_name = "Above Average"
            act = "PASS"
        elif pct >= 32.5:
            stars = 3
            q_name = "Average"
            act = "HOLD"
        elif pct >= 10.0:
            stars = 2
            q_name = "Below Average"
            act = "REPLACE"
        else:
            stars = 1
            q_name = "Bottom 10%"
            act = "EXIT"

        rankings[fid] = {
            "star_rating": stars,
            "percentile": round(pct, 1),
            "quintile": q_name,
            "metric_value": round(val, 2),
            "action": act,
        }

    return rankings



def _any_true(metrics: dict, tests: list[str]) -> tuple[bool, list[str]]:
    ok, missing = False, []
    for t in tests:
        r, miss = _eval(t, metrics)
        ok = ok or r
        missing.extend(miss)
    return ok, missing


def _aum_out_of_band(rule: dict, m: dict) -> tuple[bool, str]:
    limits = rule.get("limits_crore", {})
    floors = rule.get("floors_crore", {})
    aum = m.get("aum_crore") if m.get("aum_crore") is not None else m.get("aum_cr")
    cat = m.get("category")
    if aum is None or cat is None:
        return False, ""
    # Ceiling check (capacity degradation)
    cap = limits.get(cat)
    if cap is not None and aum > cap:
        return True, f"{cat} AUM {aum:,.0f}cr exceeds {cap:,.0f}cr"
    # GAP-VR-02 FIX: Minimum AUM floor check (zombie/illiquidity risk per Value Research / CRISIL)
    floor = floors.get(cat)
    if floor is None:
        is_debt = is_debt_category(metrics=m)
        floor = 250.0 if is_debt else 500.0
    if floor is not None and aum < floor:
        return True, f"{cat} AUM {aum:,.0f}cr is below viability floor {floor:,.0f}cr (Zombie Fund Risk)"
    return False, ""


def _describe(test: str, m: dict) -> str:
    out = []
    clauses = re.split(r'\s+(?:AND|OR)\s+', test)
    for clause in clauses:
        mt = _TOKEN.search(clause.strip())
        if mt:
            out.append(f"{mt.group(1)}={m.get(mt.group(1))} "
                       f"{mt.group(2)} {mt.group(3)}")
    return "; ".join(out)


def reduce_verdict(actions: list[str]) -> str:
    """Worst finding wins. Ties broken by first appearance."""
    if not actions:
        return "PASS"
    return max(actions, key=lambda a: (SEVERITY.get(a, 0), -actions.index(a)))


def map_quality(verdict: str) -> str:
    if verdict == "PASS":
        return "APPROVED"
    if verdict in ("FLAG", "QUARANTINE", "CONSOLIDATE_CANDIDATE", "DISCOUNT_TRACK_RECORD"):
        return "MONITOR"
    if verdict == "INCONCLUSIVE":
        return "INCONCLUSIVE"
    if verdict == "REJECT":
        return "REJECT"
    return "MONITOR"


def derive_action(quality: str, metrics: dict, is_held: bool = False) -> str:
    # Basic action logic, to be refined by fit and economics
    if quality == "REJECT":
        return "EXIT" if is_held else "REJECT"
    
    # Check for regular plan
    is_regular = False
    plan = metrics.get("plan", "").lower()
    name = metrics.get("name", "").lower()
    if "regular" in plan or "regular" in name:
        is_regular = True
    
    if is_regular:
        return "SWITCH"
        
    if quality == "APPROVED":
        return "HOLD" if is_held else "BUY"
    
    if quality == "MONITOR":
        return "HOLD"
        
    return "HOLD"


# ---------------------------------------------------------------------------
# Dataset field mapping
# ---------------------------------------------------------------------------
# fund_metrics files use compact column names. This maps them onto the canonical
# policy names used in fund_screening_criteria.json, so the policy refers to one
# vocabulary and the dataset is allowed to be terse.
#
# Provenance matters as much as the mapping: several of these carry an
# UNVERIFIED qualifier below. A mapped value is not the same as a trustworthy
# value, and conflating the two is how a confident wrong number gets published.
FIELD_MAP = {
    "cat": "category",
    "aum_cr": "aum_crore",
    "er": "ter_direct_pct",
    "sharpe": "sharpe_3y",          # UNVERIFIED horizon, see below
    "alpha": "alpha_3y",            # UNVERIFIED horizon, see below
    "lc": "portfolio_large_cap_pct",
    "mc": "portfolio_mid_cap_pct",
    "sc": "portfolio_small_cap_pct",
    "debt": "portfolio_debt_pct",
    "eq": "portfolio_equity_pct",
    "fin": "single_sector_weight_pct",
    "top10": "top10_concentration_pct",
    "up_capture": "upside_capture_ratio",
    "down_capture": "downside_capture_ratio",
    "rolling_3y_beat_rate": "rolling_3y_beat_rate_pct",
}

# Mapped, but the source does not establish what it means well enough to rely on.
# These are surfaced, not silently consumed.
UNVERIFIED = {
    "sharpe_3y": "measurement horizon not stated in the source dataset",
    "alpha_3y": "measurement horizon not stated; may be annualised or cumulative",
    "ter_direct_pct": "regular vs direct plan basis not stated in the row",
    "top_sector_weight_pct": "reported for the Financial sector only, so it is a "
                             "lower bound on true sector concentration",
}



def normalise_metrics(row: dict) -> dict:
    """Translate one dataset row into canonical policy field names.
    Also retains any canonical fields that are already present in the row."""
    out: dict = {}
    for src, dst in FIELD_MAP.items():
        v = row.get(src)
        if v is not None:
            out[dst] = v
            
    # Also copy any keys that match the canonical schema (to support injected metrics)
    for k, v in row.items():
        if k not in FIELD_MAP and v is not None:
            out[k] = v

    # GAP-240: Ensure aum_cr and aum_crore are synchronized aliases
    if "aum_crore" in out and "aum_cr" not in out:
        out["aum_cr"] = out["aum_crore"]
    elif "aum_cr" in out and "aum_crore" not in out:
        out["aum_crore"] = out["aum_cr"]

    if "portfolio_equity_pct" not in out:
        lc = float(out.get("portfolio_large_cap_pct") or 0.0)
        mc = float(out.get("portfolio_mid_cap_pct") or 0.0)
        sc = float(out.get("portfolio_small_cap_pct") or 0.0)
        if lc + mc + sc > 0:
            out["portfolio_equity_pct"] = round(lc + mc + sc, 2)
        elif "portfolio_debt_pct" in out and out["portfolio_debt_pct"] is not None:
            out["portfolio_equity_pct"] = round(100.0 - float(out["portfolio_debt_pct"]), 2)

    # Data Quality: Guarantee non-negative sleeves and asset balance
    eq_val = float(out.get("portfolio_equity_pct") or 0.0)
    debt_val = float(out.get("portfolio_debt_pct") or 0.0)
    re_val = float(out.get("portfolio_real_estate_pct") or out.get("re") or 0.0)
    other_val = out.get("portfolio_other_pct") if "portfolio_other_pct" in out else out.get("other")
    if other_val is not None:
        other_val = float(other_val)
        if other_val < 0.0 or (eq_val + debt_val + re_val + other_val > 100.01):
            corrected_other = max(0.0, round(100.0 - (eq_val + debt_val + re_val), 2))
            out["portfolio_other_pct"] = corrected_other
            if "other" in out:
                out["other"] = corrected_other

    return out


def get_fund_tax_class(fund_metrics: dict, tax_rules: dict | None = None) -> str:
    """Derive tax class from allocation field per Rule T1.
    Requires >=65% Indian equity for equity_oriented treatment.
    Never infers tax class from fund name or category string alone.
    """
    if tax_rules is None:
        tax_rules = load_tax_rules()
    threshold = float(tax_rules.get("classification_test", {}).get("equity_oriented_threshold_pct", 65.0))
    eq_pct = fund_metrics.get("portfolio_equity_pct")
    if eq_pct is None:
        eq_pct = fund_metrics.get("eq")
    if eq_pct is None:
        lc = float(fund_metrics.get("portfolio_large_cap_pct") or fund_metrics.get("lc") or 0.0)
        mc = float(fund_metrics.get("portfolio_mid_cap_pct") or fund_metrics.get("mc") or 0.0)
        sc = float(fund_metrics.get("portfolio_small_cap_pct") or fund_metrics.get("sc") or 0.0)
        if lc + mc + sc > 0:
            eq_pct = lc + mc + sc
        elif "portfolio_debt_pct" in fund_metrics and fund_metrics["portfolio_debt_pct"] is not None:
            eq_pct = 100.0 - float(fund_metrics["portfolio_debt_pct"])
        elif "debt" in fund_metrics and fund_metrics["debt"] is not None:
            eq_pct = 100.0 - float(fund_metrics["debt"])

    if eq_pct is not None and float(eq_pct) >= threshold:
        return "equity_oriented"
    return "debt_purchased_on_or_after_2023_04_01"



# ---------------------------------------------------------------------------
# Overlap, computed from actual holdings
# ---------------------------------------------------------------------------

_PLAN_WORDS = re.compile(r"\b(direct|regular)\b", re.IGNORECASE)


def plan_free_identity(fid: str) -> str:
    """Scheme identity with Direct/Regular plan qualifiers removed.

    "X" and "X Direct" are two folios of ONE scheme: identical mandate,
    identical holdings. The metrics dataset normally carries one id per
    scheme, but nothing structurally prevents it from carrying both plans
    as two ids - and when it does, those two rows score 100% against each
    other by construction. Grouping goes through the FundMatcher normaliser
    (synonyms, parentheticals, separator collapse) AFTER plan words are
    stripped, so one scheme is one identity everywhere identity matters.
    """
    from engine import fundmatch        # sibling import kept lazy: no cycle
    return fundmatch.key(_PLAN_WORDS.sub(" ", str(fid)))


# ---------------------------------------------------------------------------
# Stock Name Normalization & Weighted Overlap (GAP-220, GAP-192)
# ---------------------------------------------------------------------------

_CORP_SUFFIXES = re.compile(
    r"\b(limited|ltd|inc|incorporated|corp|corporation|llc|pvt|private|co|company)\b\.?",
    re.IGNORECASE,
)
_PUNCTUATION = re.compile(r"[,.\-_/\\()\[\]]")


def normalize_stock_name(name: str) -> str:
    """Normalize company name by stripping legal entity suffixes and punctuation.
    Prevents false negatives (e.g. 'HDFC Bank Ltd.' vs 'HDFC Bank Limited').
    """
    if not name:
        return ""
    cleaned = _PUNCTUATION.sub(" ", str(name).strip().upper())
    cleaned = _CORP_SUFFIXES.sub("", cleaned)
    return " ".join(cleaned.split())


def _extract_stock_weights(fund_dict: dict, top_n: int = 10) -> Dict[str, float]:
    """Extract normalized stock names and their portfolio weights (%) from a fund dict."""
    raw_list = (
        fund_dict.get("h")
        or fund_dict.get("holdings")
        or fund_dict.get("top10_holdings")
        or []
    )
    weights: Dict[str, float] = {}
    items = raw_list[:top_n]
    if not items:
        return weights

    # Check if items provide explicit weights
    has_weights = any(isinstance(x, dict) and ("weight" in x or "weight_pct" in x) for x in items)
    default_weight = 100.0 / len(items) if items else 0.0

    for x in items:
        if not x:
            continue
        if isinstance(x, str):
            s_name = normalize_stock_name(x)
            if s_name:
                weights[s_name] = weights.get(s_name, 0.0) + default_weight
        elif isinstance(x, dict):
            val = x.get("name") or x.get("company") or x.get("stock") or x.get("holding")
            s_name = normalize_stock_name(val)
            if not s_name:
                continue
            if has_weights:
                w = float(x.get("weight") or x.get("weight_pct") or default_weight)
            else:
                w = default_weight
            weights[s_name] = weights.get(s_name, 0.0) + w

    return weights


def overlap_details(a: dict, b: dict, top_n: int = 10) -> Tuple[float, Set[str]]:
    """RULE-M7 & GAP-220: Minimum-weight stock overlap between two funds.
    Score is sum(min(w_a, w_b)) across normalized common holdings.
    Returns (overlap_pct, set_of_common_stock_names).
    
    DEPRECATED: Use calculate_overlap() instead for new code.
    """
    result = calculate_overlap(a, b, top_n=top_n)
    if result["status"] == "MISSING":
        return 0.0, set()
    return result["overlap_pct"] or 0.0, result["common_holdings"]


def calculate_overlap(fund_a: dict, fund_b: dict, top_n: int = 10) -> 'OverlapResult':
    """
    REVIEW-P0-3: Single authoritative overlap metric - Minimum-Weight Stock Overlap.
    
    Calculates sum(min(w_a, w_b)) across common holdings with proper handling
    for missing/stale data. Does NOT renormalize partial holdings to 100%.
    
    Returns:
        OverlapResult with overlap_pct, residual fields, and effective_overlap_range.
    """
    from datetime import date
    from engine.models import OverlapResult, DataState
    
    def _extract_holdings_with_source(fund: dict):
        """Returns (weights_dict, source, as_of_date, total_weight_pct)"""
        # Priority 1: portfolio_holdings (detailed with weights and dates)
        if "portfolio_holdings" in fund and fund["portfolio_holdings"]:
            ph = fund["portfolio_holdings"]
            weights = {}
            as_of = None
            for h in ph:
                name = normalize_stock_name(h.get("name") or h.get("company") or h.get("stock"))
                if not name:
                    continue
                weight = float(h.get("weight") or h.get("weight_pct") or 0)
                if weight > 0:
                    weights[name] = weights.get(name, 0.0) + weight
            total = sum(weights.values())
            # Do NOT renormalize - keep actual weights to track residual
            if ph and "date" in ph[0]:
                try:
                    as_of = date.fromisoformat(str(ph[0]["date"]))
                except Exception:
                    pass
            return weights, "portfolio_holdings", as_of, total
        
        # Priority 2: top10_holdings / h / holdings (top-N with weights)
        for key in ("top10_holdings", "h", "holdings"):
            if key in fund and fund[key]:
                items = fund[key][:top_n]
                weights = {}
                as_of = None
                has_explicit_weights = False
                item_count = 0
                for x in items:
                    if not x:
                        continue
                    if isinstance(x, dict):
                        name = normalize_stock_name(
                            x.get("name") or x.get("company") or x.get("stock") or x.get("holding")
                        )
                        if name:
                            w = float(x.get("weight") or x.get("weight_pct") or 0)
                            if w > 0:
                                has_explicit_weights = True
                            weights[name] = weights.get(name, 0.0) + w
                            item_count += 1
                    elif isinstance(x, str):
                        name = normalize_stock_name(x)
                        if name:
                            weights[name] = weights.get(name, 0.0) + 1.0  # Count occurrences
                            item_count += 1
                total = sum(weights.values())
                # Do NOT renormalize - keep actual weights to track residual
                # For string items without explicit weights, assign equal weight based on count
                if not has_explicit_weights and item_count > 0:
                    equal_weight = 100.0 / item_count
                    weights = {k: equal_weight for k in weights.keys()}
                    total = sum(weights.values())
                if "holdings_as_of" in fund:
                    try:
                        as_of = date.fromisoformat(str(fund["holdings_as_of"]))
                    except Exception:
                        pass
                return weights, key, as_of, total
        
        return {}, "none", None, 0.0
    
    wa, src_a, as_of_a, total_a = _extract_holdings_with_source(fund_a)
    wb, src_b, as_of_b, total_b = _extract_holdings_with_source(fund_b)
    
    # Check for missing data
    if not wa or not wb:
        return OverlapResult(
            fund_a=fund_a.get("id", "unknown"),
            fund_b=fund_b.get("id", "unknown"),
            overlap_pct=0.0,
            shared_holdings=[],
            data_status="MISSING",
            fund_a_residual_pct=100.0 - total_a if total_a > 0 else 100.0,
            fund_b_residual_pct=100.0 - total_b if total_b > 0 else 100.0,
        )
    
    # Check for stale data (>180 days)
    data_status = "OK"
    today = date.today()
    for as_of, src in [(as_of_a, src_a), (as_of_b, src_b)]:
        if as_of and src != "none":
            if (today - as_of).days > 180:
                data_status = "STALE"
                break
    
    # Calculate overlap: sum of minimum weights (using actual weights, not renormalized)
    common = set(wa.keys()) & set(wb.keys())
    if not common:
        overlap_pct = 0.0
    else:
        overlap_pct = sum(min(wa[s], wb[s]) for s in common)
        overlap_pct = round(overlap_pct, 2)
    
    # Calculate residuals (unclassified portion)
    fund_a_residual = max(0.0, 100.0 - total_a)
    fund_b_residual = max(0.0, 100.0 - total_b)
    
    # Estimate overlap in residual portion (conservative: assume max possible overlap)
    residual_overlap_estimate = min(fund_a_residual, fund_b_residual)
    
    # Determine if partial
    is_partial = fund_a_residual > 0 or fund_b_residual > 0
    if is_partial:
        data_status = "PARTIAL"
    
    return OverlapResult(
        fund_a=fund_a.get("id", "unknown"),
        fund_b=fund_b.get("id", "unknown"),
        overlap_pct=overlap_pct,
        shared_holdings=list(common),
        fund_a_residual_pct=round(fund_a_residual, 2),
        fund_b_residual_pct=round(fund_b_residual, 2),
        residual_overlap_estimate_pct=round(residual_overlap_estimate, 2),
        data_status=data_status,
    )


def overlap_score(fund_a: dict, fund_b: dict) -> float:
    """Compatibility wrapper returning minimum-weight stock overlap percentage (0.0 - 100.0)."""
    res = calculate_overlap(fund_a, fund_b)
    # OverlapResult is a Pydantic model, use attribute access
    return float(res.overlap_pct or 0.0)



# Module-level cache for overlap_matrix (FIX #4: O(N²) Infinite Loop prevention)
_overlap_matrix_cache: dict[str, list[dict]] = {}

def overlap_matrix(rows: list[dict], threshold: float = None) -> list[dict]:
    """
    All distinct fund pairs above the overlap threshold, worst first.

    Rows are deduplicated by resolved scheme identity, not by list position:
    one fund held through several folios contributes exactly one row, and the
    direct and the regular plan of the same scheme are ONE fund as well. Those
    folios score 100% against each other by construction; that is not a
    diversification problem and must never be reported as one. A row without
    any usable identity is excluded rather than guessed at, in keeping with
    the engine's refusal to guess.

    Args:
        rows: List of fund dicts with 'id' and 'h' (holdings) keys
        threshold: Overlap threshold percentage. If None, loads from policy JSON.
    
    Caching: Results are cached by content hash of input rows to prevent
    O(N²) recomputation on repeated calls with same portfolio.
    """
    # Generate cache key from rows content
    import hashlib
    import json
    cache_key = hashlib.sha256(
        json.dumps([{"id": r.get("id"), "h": r.get("h")} for r in rows], sort_keys=True).encode()
    ).hexdigest()[:16]
    if threshold:
        cache_key += f"_t{threshold}"
    
    if cache_key in _overlap_matrix_cache:
        return _overlap_matrix_cache[cache_key]
    
    crit = load_criteria()
    if threshold is None:
        threshold = crit.get("_overlap_threshold_pct")
        if threshold is None:
            raise PolicyError("_overlap_threshold_pct missing from policy")
    seen: dict[str, dict] = {}
    for r in rows:
        fid = r.get("id")
        if fid:
            seen.setdefault(plan_free_identity(fid), r)   # first folio wins
    uniq = list(seen.values())

    out = []
    for i, a in enumerate(uniq):
        aid = a.get("id")
        for b in uniq[i + 1:]:
            # Strictly block self-comparison. The i+1 slice already guarantees
            # distinct positions; the identity check below is defence in depth
            # so a future refactor of the dedup cannot reintroduce the bug.
            if a is b or aid == b.get("id"):
                continue
            result = calculate_overlap(a, b)
            # Skip if missing data (cannot determine overlap)
            if result.data_status == "MISSING":
                continue
            s = result.overlap_pct
            if s is None or s < threshold:
                continue
            common_stocks = result.shared_holdings
            # Determine overlap tier and action
            crit = load_criteria()
            tier1 = crit.get('_overlap_tier1_pct', 20.0)
            tier2 = crit.get('_overlap_tier2_pct', 25.0)
            tier3 = crit.get('_overlap_threshold_pct', 40.0)
            
            if s >= tier3:
                tier = 3
                action = "STRUCTURAL_REVIEW"
            elif s >= tier2:
                tier = 2
                action = "CONCENTRATION_WARNING"
            elif s >= tier1:
                tier = 1
                action = "MONITOR"
            else:
                tier = 0
                action = "NONE"
            
            # GAP-137 FIX: Pass actual shared holdings count instead of hardcoded 0
            try:
                from engine.logging_config import log_overlap_pair
                log_overlap_pair(aid, b.get('id'), round(s, 1), tier, len(common_stocks), action)
            except Exception as e:
                logger.warning(r"Overlap pair logging failed: {e}")
            
            out.append({"a": aid, "b": b.get("id"),
                        "overlap_pct": round(s, 1),
                        "tier": tier,
                        "shared_holdings_count": len(common_stocks),
                        "shared_holdings": sorted(list(common_stocks)),
                        "data_status": result.data_status,  # OK | STALE | PARTIAL
                        "data_source_a": getattr(result, 'data_source_a', None),
                        "data_source_b": getattr(result, 'data_source_b', None),
                        "decomposition": decompose_overlap_4part(a, b),
                        "action": action})
    result = sorted(out, key=lambda r: -r["overlap_pct"])
    _overlap_matrix_cache[cache_key] = result  # Cache result
    return result



def graduated_overlap(rows: list[dict], crit: dict = None) -> dict:
    """
    Three-tier graduated overlap analysis per Requirement.md 4.2 A2b.

    Tier 1 (>20%): Early warning - monitoring only, no action
    Tier 2 (>25%): Concentration warning - requires documented rationale
    Tier 3 (>=40%): Structural breach - mandatory review with XIRR arbiter

    Returns dict with tier classifications and recommendations.
    """
    if crit is None:
        crit = load_criteria()

    tier1_thresh = crit.get('_overlap_tier1_pct', 20.0)
    tier2_thresh = crit.get('_overlap_tier2_pct', 25.0)
    tier3_thresh = crit.get('_overlap_threshold_pct', 40.0)

    # Deduplicate by plan-free identity (same logic as overlap_matrix)
    seen: dict[str, dict] = {}
    for r in rows:
        fid = r.get('id')
        if fid:
            seen.setdefault(plan_free_identity(fid), r)
    uniq = list(seen.values())

    results = {
        'tier1_monitoring': [],
        'tier2_warning': [],
        'tier3_breach': [],
        'recommendations': []
    }

    for i, a in enumerate(uniq):
        aid = a.get('id')
        for b in uniq[i + 1:]:
            if a is b or aid == b.get('id'):
                continue
            s = overlap_score(a, b)

            if s >= tier3_thresh:
                results['tier3_breach'].append({
                    'a': aid, 'b': b.get('id'),
                    'overlap_pct': round(s, 1),
                    'severity': 'structural_breach'
                })
                results['recommendations'].append({
                    'type': 'structural_review',
                    'funds': [aid, b.get('id')],
                    'overlap_pct': round(s, 1),
                    'action': 'review_xirrbased_exit'
                })
            elif s >= tier2_thresh:
                results['tier2_warning'].append({
                    'a': aid, 'b': b.get('id'),
                    'overlap_pct': round(s, 1),
                    'severity': 'concentration_warning'
                })
                results['recommendations'].append({
                    'type': 'concentration_warning',
                    'funds': [aid, b.get('id')],
                    'overlap_pct': round(s, 1),
                    'action': 'document_rationale'
                })
            elif s >= tier1_thresh:
                results['tier1_monitoring'].append({
                    'a': aid, 'b': b.get('id'),
                    'overlap_pct': round(s, 1),
                    'severity': 'early_warning'
                })
                results['recommendations'].append({
                    'type': 'monitoring',
                    'funds': [aid, b.get('id')],
                    'overlap_pct': round(s, 1),
                    'action': 'monitor'
                })

    return results



def aggregate_stock_overlap(
    rows: list[dict],
    portfolio_weights: dict[str, float],
    top_n: int = 10,
    direct_equity_holdings: list[dict] = None,
) -> list[dict]:
    """
    Aggregate stock-level look-through overlap across the portfolio.
    
    For each stock appearing in any fund's top-N holdings, compute:
    - count: number of funds holding the stock
    - portfolio_weight: sum of (fund_weight * stock_weight_in_fund)
    
    Since we only have stock names (not individual weights), we approximate
    stock_weight_in_fund as (fund's top10_concentration_pct / 10) per stock,
    which assumes equal weight across the top 10 holdings.
    
    Args:
        rows: Fund metric rows with 'id', 'h' (holdings list), 'top10_concentration_pct'
        portfolio_weights: fund_id -> weight in portfolio (0-100 scale)
        top_n: Number of top holdings to consider (default 10)
        direct_equity_holdings: Optional list of dicts with keys 'stock', 'quantity', 'value'
    
    Returns:
        List of dicts: {stock, fund_count, funds_list, approx_portfolio_weight_pct}
        Sorted by approx_portfolio_weight_pct descending.
    """
    from collections import defaultdict
    
    stock_funds = defaultdict(list)
    stock_weights = defaultdict(float)
    
    # Process mutual fund holdings
    for row in rows:
        fid = row.get("id")
        if not fid:
            continue
        
        fund_weight = portfolio_weights.get(fid, 0.0)
        if fund_weight <= 0:
            continue
        
        holdings = row.get("h", [])[:top_n]
        top10_conc = row.get("top10_concentration_pct", 0.0)
        
        if not holdings or top10_conc <= 0:
            continue
        
        # Approximate per-stock weight within this fund's top-N
        # Assumption: equal weight across top-N
        per_stock_weight = top10_conc / len(holdings) if holdings else 0.0
        
        for stock in holdings:
            stock_clean = stock.strip()
            if not stock_clean:
                continue
            stock_funds[stock_clean].append(fid)
            # Look-through weight = fund_weight * stock_weight_in_fund
            stock_weights[stock_clean] += fund_weight * (per_stock_weight / 100.0)
    
    # Process direct equity holdings
    if direct_equity_holdings:
        total_direct_value = sum(h.get('value', 0) for h in direct_equity_holdings)
        for h in direct_equity_holdings:
            stock = h.get('stock', '').strip()
            value = h.get('value', 0)
            if stock and value > 0:
                stock_clean = stock.strip()
                if stock_clean:
                    weight_pct = (value / total_direct_value * 100) if total_direct_value > 0 else 0
                    stock_funds[stock_clean].append('DIRECT_EQUITY')
                    stock_weights[stock_clean] += weight_pct
    
    # Build result
    result = []
    for stock, funds in stock_funds.items():
        if len(funds) <= 1:
            continue  # Only report stocks held in multiple funds
        result.append({
            "stock": stock,
            "fund_count": len(funds),
            "funds_list": sorted(set(funds)),
            "approx_portfolio_weight_pct": round(stock_weights[stock], 2),
        })
    
    return result



# ---------------------------------------------------------------------------
# Morningstar 4-Part Overlap Decomposition (GAP-MS-03)
# ---------------------------------------------------------------------------

def decompose_overlap_4part(
    fund_a_metrics: dict,
    fund_b_metrics: dict,
    top_n: int = 10
) -> Dict[str, float]:
    """Decompose portfolio overlap into 4 parts per Morningstar Direct methodology (GAP-101).
    1. Name Overlap: sum(min(w_A, w_B)) across normalized common stocks.
    2. Sector Overlap: common sector exposure excluding direct stock overlap.
    3. Factor Overlap: market cap / style box similarity.
    4. Residual Overlap: idiosyncratic variance.
    """
    wa = _extract_stock_weights(fund_a_metrics, top_n=top_n)
    wb = _extract_stock_weights(fund_b_metrics, top_n=top_n)

    if not wa or not wb:
        return {
            "name_overlap_pct": 0.0,
            "sector_overlap_pct": 0.0,
            "factor_overlap_pct": 0.0,
            "residual_overlap_pct": 0.0,
            "total_overlap_pct": 0.0,
            "name_overlap_stocks": [],
        }

    # 1. Name Overlap: Minimum weight stock overlap
    common_stocks = set(wa.keys()) & set(wb.keys())
    name_overlap_pct = sum(min(wa[s], wb[s]) for s in common_stocks) if common_stocks else 0.0

    # 2. Sector Overlap: Common sector weights minus name overlap already accounted for
    sector_a = fund_a_metrics.get("sector", {}) or fund_a_metrics.get("sectors", {}) or {}
    sector_b = fund_b_metrics.get("sector", {}) or fund_b_metrics.get("sectors", {}) or {}
    raw_sector_overlap = 0.0
    if isinstance(sector_a, dict) and isinstance(sector_b, dict):
        common_sectors = set(sector_a.keys()) & set(sector_b.keys())
        raw_sector_overlap = sum(min(float(sector_a.get(s, 0) or 0), float(sector_b.get(s, 0) or 0)) for s in common_sectors)
    elif isinstance(sector_a, (str, list)) or isinstance(sector_b, (str, list)):
        secs_a = set(sector_a) if isinstance(sector_a, list) else {str(sector_a).strip().lower()}
        secs_b = set(sector_b) if isinstance(sector_b, list) else {str(sector_b).strip().lower()}
        common_sectors = secs_a & secs_b
        if common_sectors and secs_a and secs_b:
            raw_sector_overlap = (len(common_sectors) / max(len(secs_a), len(secs_b))) * 100.0
    sector_overlap_pct = max(0.0, raw_sector_overlap - (name_overlap_pct * 0.7))

    # 3. Factor Overlap: Size / Style box alignment
    mc_a = float(fund_a_metrics.get("mc", 0) or 0) + float(fund_a_metrics.get("lc", 0) or 0)
    sc_a = float(fund_a_metrics.get("sc", 0) or 0)
    mc_b = float(fund_b_metrics.get("mc", 0) or 0) + float(fund_b_metrics.get("lc", 0) or 0)
    sc_b = float(fund_b_metrics.get("sc", 0) or 0)

    factor_overlap_pct = 0.0
    if (mc_a + sc_a > 0) and (mc_b + sc_b > 0):
        mc_ratio_a = mc_a / (mc_a + sc_a)
        mc_ratio_b = mc_b / (mc_b + sc_b)
        size_similarity = max(0.0, 1.0 - abs(mc_ratio_a - mc_ratio_b))
        factor_overlap_pct = size_similarity * 100.0

    total_overlap = min(100.0, name_overlap_pct + sector_overlap_pct)
    residual_overlap_pct = max(0.0, 100.0 - total_overlap)

    return {
        "name_overlap_pct": round(name_overlap_pct, 2),
        "sector_overlap_pct": round(sector_overlap_pct, 2),
        "factor_overlap_pct": round(factor_overlap_pct, 2),
        "residual_overlap_pct": round(residual_overlap_pct, 2),
        "total_overlap_pct": round(total_overlap, 2),
        "name_overlap_stocks": sorted(list(common_stocks)),
    }



def detect_style_drift(
    current_holdings: list[dict],
    historical_holdings: list[dict],
    top_n: int = 10,
    drift_threshold: float = 0.10,
) -> dict:
    """
    Detect style drift by comparing current fund holdings with historical holdings.
    
    Analyzes changes in:
    - Market cap allocation (large/mid/small cap shifts)
    - Sector allocation shifts
    - Top holdings turnover
    - Factor exposure changes (value/growth/momentum)
    
    Args:
        current_holdings: List of fund dicts with current 'h' (holdings) and metadata
        historical_holdings: List of fund dicts with historical 'h' (holdings) and metadata
        top_n: Number of top holdings to compare
        drift_threshold: Minimum change to flag as drift (default 10%)
    
    Returns:
        Dict with drift analysis results including alerts and recommendations.
    """
    from collections import defaultdict
    
    def get_fund_identity(fund: dict) -> str:
        return plan_free_identity(fund.get('id', ''))
    
    def get_top_holdings(fund: dict) -> list[str]:
        return [h.strip().lower() for h in (fund.get('h') or [])[:top_n] if h]
    
    def get_sector_allocation(fund: dict) -> dict[str, float]:
        # Placeholder: would need sector mapping data
        return {}
    
    def get_market_cap_allocation(fund: dict) -> dict[str, float]:
        # Placeholder: would need market cap data
        return {}
    
    # Build historical lookup by fund identity
    hist_lookup = {}
    for fund in historical_holdings:
        fid = get_fund_identity(fund)
        if fid:
            hist_lookup[fid] = fund
    
    alerts = []
    fund_drift_scores = {}
    
    for curr_fund in current_holdings:
        fid = get_fund_identity(curr_fund)
        if not fid or fid not in hist_lookup:
            continue
        
        hist_fund = hist_lookup[fid]
        curr_holdings = get_top_holdings(curr_fund)
        hist_holdings = get_top_holdings(hist_fund)
        
        # Calculate holding turnover
        curr_set = set(curr_holdings)
        hist_set = set(hist_holdings)
        turnover = len(curr_set.symmetric_difference(hist_set)) / max(len(curr_set), len(hist_set), 1)
        
        # Calculate sector allocation drift (placeholder)
        curr_sectors = get_sector_allocation(curr_fund)
        hist_sectors = get_sector_allocation(hist_fund)
        sector_drift = 0.0
        all_sectors = set(curr_sectors.keys()) | set(hist_sectors.keys())
        if all_sectors:
            sector_drift = sum(
                abs(curr_sectors.get(s, 0) - hist_sectors.get(s, 0))
                for s in all_sectors
            ) / 2.0  # Normalize to 0-1
        
        # Calculate market cap drift (placeholder)
        curr_caps = get_market_cap_allocation(curr_fund)
        hist_caps = get_market_cap_allocation(hist_fund)
        cap_drift = 0.0
        all_caps = set(curr_caps.keys()) | set(hist_caps.keys())
        if all_caps:
            cap_drift = sum(
                abs(curr_caps.get(c, 0) - hist_caps.get(c, 0))
                for c in all_caps
            ) / 2.0
        
        # Overall drift score
        drift_score = (turnover + sector_drift + cap_drift) / 3.0
        fund_drift_scores[curr_fund.get('id', 'unknown')] = drift_score
        
        if drift_score >= drift_threshold:
            alerts.append({
                'fund_id': curr_fund.get('id', 'unknown'),
                'drift_score': round(drift_score * 100, 1),
                'turnover_pct': round(turnover * 100, 1),
                'sector_drift_pct': round(sector_drift * 100, 1),
                'cap_drift_pct': round(cap_drift * 100, 1),
                'severity': 'high' if drift_score > 0.2 else 'medium',
                'recommendation': 'Review fund mandate adherence. Consider replacing if drift persists.'
            })
    
    return {
        'fund_drift_scores': {k: round(v * 100, 1) for k, v in fund_drift_scores.items()},
        'alerts': alerts,
        'overall_drift_detected': len(alerts) > 0,
        'drift_threshold_pct': drift_threshold * 100
    }

def duplicate_plan_folios(rows: list[dict]) -> list[str]:

    """Funds held through more than one folio. Informational, not a finding.

    Counted per resolved scheme identity, so the Direct and the Regular plan
    of one scheme are flagged as duplicates of each other even where the
    metrics dataset carries them as two ids. Returns one representative id
    per duplicated fund.
    """
    counts: dict[str, int] = {}
    rep: dict[str, str] = {}
    for r in rows:
        fid = r.get("id")
        if not fid:
            continue
        k = plan_free_identity(fid)
        rep.setdefault(k, fid)
        counts[k] = counts.get(k, 0) + 1
    return sorted(rep[k] for k, v in counts.items() if v > 1)



def satellite_prefixes(criteria: dict) -> list:
    """Satellite categories come from the policy file, never from a literal."""
    return [s.lower() for s in
            criteria.get("category_taxonomy", {})
            .get("satellite_prefixes", [])]


def hybrid_prefixes(criteria: dict | None = None) -> list[str]:
    """Hybrid equity categories come from the policy file."""
    crit = criteria or load_criteria()
    return [s.lower() for s in
            crit.get("category_taxonomy", {})
            .get("hybrid_equity_prefixes", [])]


def debt_prefixes(criteria: dict | None = None) -> list[str]:
    """Debt categories come from the policy file."""
    crit = criteria or load_criteria()
    return [s.lower() for s in
            crit.get("category_taxonomy", {})
            .get("debt_prefixes", [])]


def is_satellite(category: str, prefixes: list) -> bool:
    """Prefix match, so 'Thematic-Defence' and 'Sectoral: Bank' both classify."""
    c = str(category).lower().split(":")[0].strip()
    return any(c.startswith(p) for p in prefixes)


def is_hybrid_category(category: str, criteria: dict | None = None) -> bool:
    """Check if category is a hybrid equity stabilizer."""
    prefixes = hybrid_prefixes(criteria)
    c = str(category).lower().strip()
    return any(p in c for p in prefixes)


def is_debt_category(category: str = "", debt_pct: float | None = None, criteria: dict | None = None, equity_pct: float | None = None, metrics: dict | None = None) -> bool:
    """Check if fund is a debt / cash equivalent.
    Rule T1: Classification strictly governed by allocation field (>=65% equity for equity treatment)."""
    if metrics:
        return get_fund_tax_class(metrics) != "equity_oriented"
    if equity_pct is not None:
        return float(equity_pct) < 65.0
    if debt_pct is not None and float(debt_pct) > 35.0:
        return True
    prefixes = debt_prefixes(criteria)
    c = str(category).lower().strip()
    return any(p in c for p in prefixes)


def normalize_sebi_category(category: str) -> str:
    """Normalize fund category to canonical SEBI category per Rule 4.4.
    Strips prefix before colon (e.g. 'Equity: Mid Cap' -> 'Mid Cap') and harmonizes labels."""
    if not category:
        return ""
    c = str(category).strip()
    if ":" in c:
        c = c.split(":")[-1].strip()
    c_lower = c.lower()
    if "large & mid" in c_lower or "large and mid" in c_lower:
        return "Large & Mid Cap"
    if "large" in c_lower and not any(k in c_lower for k in ("mid", "small", "flexi", "multi")):
        return "Large Cap"
    if "mid" in c_lower and "small" not in c_lower and "large" not in c_lower:
        return "Mid Cap"
    if "small" in c_lower and "mid" not in c_lower:
        return "Small Cap"
    if "flexi" in c_lower:
        return "Flexi Cap"
    if "multi" in c_lower and "cap" in c_lower:
        return "Multi Cap"
    if "elss" in c_lower or "tax saver" in c_lower:
        return "ELSS"
    if "focused" in c_lower:
        return "Focused"
    if "dividend" in c_lower:
        return "Dividend Yield"
    if "value" in c_lower:
        return "Value"
    if "contra" in c_lower:
        return "Contra"
    return c



def apply_tri_adjustment(measured_delta_pct: float, horizon_years: float,
                         benchmark_dividend_yield_pct: float) -> dict:
    """
    Convert a PRICE-index comparison into a TRI-equivalent comparison.

    Why this exists. A TRI series is unobtainable here: NSE returns 503 with
    browser headers and 403 behind a session cookie, and no TRI symbol is
    published on the accessible feed. But the price-index series IS available,
    so the engine can measure a comparison against it.

    The measured comparison is not the real one. A fund NAV reinvests
    dividends and a price index does not, so the fund looks better by roughly
    the benchmark's dividend yield, compounded over the horizon.

    Given that ONE sourced yield, the engine applies the correction itself
    rather than requiring the analyst to transcribe a delta for every fund -
    which is where transcription error would enter.

    The result is still an ESTIMATE and must be labelled as such. The error is
    one-directional: it never understates a fund's own performance.
    """
    if horizon_years <= 0:
        return {"adjusted": measured_delta_pct, "error_pct": 0.0,
                "basis": "invalid horizon"}
    error = benchmark_dividend_yield_pct * horizon_years
    return {
        "adjusted": round(measured_delta_pct - error, 2),
        "error_pct": round(error, 2),
        "horizon_years": horizon_years,
        "basis": "price index adjusted by a sourced dividend yield",
        "exact": False,
        "direction": "always flatters the fund; the true TRI delta is lower or equal",
    }


def screen_portfolio(holdings: list[dict],
                     criteria: dict | None = None) -> dict:
    """
    Screen a set of holdings and apply the PORTFOLIO-LEVEL rules.

    The per-fund screen cannot see concentration, so the macro rules live here
    and are computed from actual weights. They were previously declared in the
    policy file and never evaluated, which is worse than not declaring them: a
    rule that reads as a control but is inert gives false assurance.
    """
    crit = criteria or load_criteria()
    rows = [screen_fund(h.get("fund_id", "?"), h, crit,
                        h.get("portfolio_weight_pct")).to_dict() for h in holdings]

    weights = [float(h.get("portfolio_weight_pct") or 0.0) for h in holdings]
    total = sum(weights)
    findings: list[dict] = []

    def pct(part: float) -> float:
        return (part / total * 100.0) if total else 0.0

    # CORE-SATELLITE: broad diversified funds must dominate the equity core.
    # Threshold extracted from portfolio_level_rules in fund_screening_criteria.json
    p_rules = crit.get("portfolio_level_rules", [])
    if isinstance(p_rules, dict):
        p_rules = list(p_rules.values())
    cs_rule = next((r for r in p_rules if isinstance(r, dict) and r.get("id") == "CORE_SATELLITE_RATIO"), {})
    cs_threshold = cs_rule.get("threshold_pct")
    if cs_threshold is None and cs_rule.get("test"):
        _m = re.search(r'>(\s*)([\d.]+)', cs_rule["test"])
        if _m:
            cs_threshold = float(_m.group(2))
    if cs_threshold is None:
        raise PolicyError("CORE_SATELLITE_RATIO threshold missing from policy")
    sat_cats = satellite_prefixes(crit)
    sat = pct(sum(w for w, h in zip(weights, holdings)
                  if is_satellite(str(h.get("category", "")), sat_cats)))
    if total and sat > cs_threshold:
        findings.append({
            "rule_id": "CORE_SATELLITE_RATIO",
            "detail": f"thematic/sector share {sat:.1f}% exceeds the {cs_threshold:.0f}% core-satellite cap",
            "severity": "FLAG"})

    # SINGLE-THEME: a single thematic or sector scheme is a satellite, not core.
    st_rule = next((r for r in p_rules if isinstance(r, dict) and r.get("id") == "SINGLE_THEME_CAP"), {})
    st_threshold = st_rule.get("threshold_pct")
    if st_threshold is None and st_rule.get("test"):
        _m = re.search(r'>(\s*)([\d.]+)', st_rule["test"])
        if _m:
            st_threshold = float(_m.group(2))
    if st_threshold is None:
        raise PolicyError("SINGLE_THEME_CAP threshold missing from policy")
    by_name: dict[str, float] = {}
    for w, h in zip(weights, holdings):
        cat = str(h.get("category", "")).lower().split(":")[0]
        if is_satellite(str(h.get("category", "")), sat_cats):
            by_name[str(h.get("category"))] = by_name.get(str(h.get("category")), 0.0) + w
    for cat, w in by_name.items():
        if total and pct(w) > st_threshold:
            findings.append({
                "rule_id": "SINGLE_THEME_CAP",
                "detail": f"{cat} at {pct(w):.1f}% exceeds the {st_threshold:.0f}% single-theme cap",
                "severity": "FLAG"})

    # EQUITY ALLOCATION: only checkable when the portfolio declares a band.
    band = crit.get("portfolio_level_rules", {})
    band_cfg = {}
    if isinstance(band, list):
        for r in band:
            if isinstance(r, dict) and r.get("id") == "EQUITY_ALLOCATION_BAND":
                band_cfg = r
                break
    elif isinstance(band, dict):
        band_cfg = band.get("EQUITY_ALLOCATION_BAND", {})
    lo, hi = band_cfg.get("min_pct"), band_cfg.get("max_pct")
    if total and lo is not None and hi is not None:
        eq = pct(sum(w for w, h in zip(weights, holdings)
                     if str(h.get("category", "")).lower().find("debt") < 0))
        if not (lo <= eq <= hi):
            findings.append({
                "rule_id": "EQUITY_ALLOCATION_BAND",
                "detail": f"equity {eq:.1f}% outside the client band {lo}-{hi}%",
                "severity": "FLAG"})

    return {
        "screened": len(rows),
        "total_weight_pct": round(total, 2),
        "weights_present": bool(total),
        "verdicts": {v: sum(1 for r in rows if r["verdict"] == v)
                     for v in {r["verdict"] for r in rows}},
        "results": rows,
        "portfolio_findings": findings,
        "policy_version": crit.get("version"),
        "policy_as_of": crit.get("as_of"),
    }
