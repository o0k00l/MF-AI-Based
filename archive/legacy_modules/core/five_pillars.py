"""
Morningstar 5-Pillar Composite Decision Matrix
GAP-MS-01: Morningstar 5-Pillar Composite Decision Matrix
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from enum import Enum
from decimal import Decimal


class PillarRating(Enum):
    HIGH = "High"
    ABOVE_AVERAGE = "Above Average"
    AVERAGE = "Average"
    BELOW_AVERAGE = "Below Average"
    LOW = "Low"


class CompositeRating(Enum):
    GOLD = "Gold"
    SILVER = "Silver"
    BRONZE = "Bronze"
    NEUTRAL = "Neutral"
    NEGATIVE = "Negative"


@dataclass
class PillarScore:
    pillar_name: str
    rating: PillarRating
    score: float
    fiduciary_veto: bool = False
    justification: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class FundMedalistScore:
    fund_id: str
    fund_name: str
    people: PillarScore
    process: PillarScore
    parent: PillarScore
    performance: PillarScore
    price: PillarScore
    composite_rating: CompositeRating
    composite_score: float
    veto_activated: bool
    report_section: Dict[str, str] = field(default_factory=dict)
    
    @property
    def pillars(self) -> List[PillarScore]:
        return [self.people, self.process, self.parent, self.performance, self.price]


class FivePillarsEvaluator:
    def __init__(self, policy_config: Optional[Dict] = None):
        self.policy_config = policy_config or {}
    
    def evaluate_people_pillar(self, fund_id: str, manager_tenure_years: Optional[float] = None, team_stability_score: Optional[float] = None, manager_changes_count: int = 0, manager_changes_last_12m: int = 0) -> PillarScore:
        metrics = {"manager_tenure_years": manager_tenure_years or 0.0, "team_stability_score": team_stability_score or 0.0, "manager_changes_count": manager_changes_count, "manager_changes_last_12m": manager_changes_last_12m}
        fiduciary_veto = False
        if manager_tenure_years is not None and manager_tenure_years < 1.0:
            fiduciary_veto = True
            rating = PillarRating.LOW
            score = 20.0
            justification = f"Manager tenure {manager_tenure_years:.1f} years < 1.0 year threshold - FIDUCIARY VETO"
        else:
            tenure_score = min(100, max(0, manager_tenure_years * 10)) if manager_tenure_years else 50
            stability_score = team_stability_score or 50
            change_penalty = manager_changes_last_12m * 20
            final_score = max(0, min(100, (tenure_score * 0.6 + stability_score * 0.4) - change_penalty))
            if final_score >= 80:
                rating = PillarRating.HIGH
            elif final_score >= 60:
                rating = PillarRating.ABOVE_AVERAGE
            elif final_score >= 40:
                rating = PillarRating.AVERAGE
            elif final_score >= 20:
                rating = PillarRating.BELOW_AVERAGE
            else:
                rating = PillarRating.LOW
            score = final_score
            tenure_str = f"{manager_tenure_years:.1f}y" if manager_tenure_years is not None else "N/A"
            stability_str = f"{stability_score:.0f}" if stability_score is not None else "N/A"
            justification = f"Manager tenure {tenure_str}, stability {stability_str}, changes in 12m: {manager_changes_last_12m}"
        return PillarScore(pillar_name="People", rating=rating, score=score, fiduciary_veto=fiduciary_veto, justification=justification, metrics=metrics)
    
    def evaluate_process_pillar(self, fund_id: str, strategy_consistency_score: Optional[float] = None, parent_methodology_alignment: Optional[float] = None, process_deviation_count: int = 0, process_documented: bool = True) -> PillarScore:
        metrics = {"strategy_consistency_score": strategy_consistency_score or 0.0, "parent_methodology_alignment": parent_methodology_alignment or 0.0, "process_deviation_count": process_deviation_count, "process_documented": process_documented}
        consistency = strategy_consistency_score or 50
        alignment = parent_methodology_alignment or 50
        deviation_penalty = process_deviation_count * 15
        documentation_bonus = 10 if process_documented else -20
        score = max(0, min(100, (consistency * 0.5 + alignment * 0.5) - deviation_penalty + documentation_bonus))
        if score >= 80:
            rating = PillarRating.HIGH
        elif score >= 60:
            rating = PillarRating.ABOVE_AVERAGE
        elif score >= 40:
            rating = PillarRating.AVERAGE
        elif score >= 20:
            rating = PillarRating.BELOW_AVERAGE
        else:
            rating = PillarRating.LOW
        consistency_str = f"{consistency:.0f}" if consistency is not None else "N/A"
        alignment_str = f"{alignment:.0f}" if alignment is not None else "N/A"
        justification = f"Strategy consistency {consistency_str}, AMC alignment {alignment_str}, deviations: {process_deviation_count}"
        return PillarScore(pillar_name="Process", rating=rating, score=score, justification=justification, metrics=metrics)
    
    def evaluate_parent_pillar(self, fund_id: str, amc_governance_score: Optional[float] = None, amc_fee_structure_score: Optional[float] = None, amc_stability_score: Optional[float] = None, fund_size_crores: Optional[float] = None) -> PillarScore:
        metrics = {"amc_governance_score": amc_governance_score or 0.0, "amc_fee_structure_score": amc_fee_structure_score or 0.0, "amc_stability_score": amc_stability_score or 0.0, "fund_size_crores": fund_size_crores or 0.0}
        governance = amc_governance_score or 50
        fee_structure = amc_fee_structure_score or 50
        stability = amc_stability_score or 50
        size_bonus = 0
        if fund_size_crores:
            if fund_size_crores >= 10000:
                size_bonus = 10
            elif fund_size_crores >= 1000:
                size_bonus = 5
        score = max(0, min(100, (governance * 0.4 + fee_structure * 0.3 + stability * 0.3) + size_bonus))
        if score >= 80:
            rating = PillarRating.HIGH
        elif score >= 60:
            rating = PillarRating.ABOVE_AVERAGE
        elif score >= 40:
            rating = PillarRating.AVERAGE
        elif score >= 20:
            rating = PillarRating.BELOW_AVERAGE
        else:
            rating = PillarRating.LOW
        gov_str = f"{governance:.0f}" if governance is not None else "N/A"
        fee_str = f"{fee_structure:.0f}" if fee_structure is not None else "N/A"
        stab_str = f"{stability:.0f}" if stability is not None else "N/A"
        fund_size_str = f"{fund_size_crores:.0f}" if fund_size_crores else "N/A"
        justification = f"AMC governance {gov_str}, fee structure {fee_str}, stability {stab_str}, AUM ₹{fund_size_str}Cr"
        return PillarScore(pillar_name="Parent", rating=rating, score=score, justification=justification, metrics=metrics)
    
    def evaluate_performance_pillar(self, fund_id: str, risk_adjusted_return_score: Optional[float] = None, capture_up_ratio: Optional[float] = None, capture_down_ratio: Optional[float] = None, rolling_return_consistency: Optional[float] = None, benchmark_alpha_3y: Optional[float] = None) -> PillarScore:
        metrics = {"risk_adjusted_return_score": risk_adjusted_return_score or 0.0, "capture_up_ratio": capture_up_ratio or 0.0, "capture_down_ratio": capture_down_ratio or 0.0, "rolling_return_consistency": rolling_return_consistency or 0.0, "benchmark_alpha_3y": benchmark_alpha_3y or 0.0}
        risk_adj = risk_adjusted_return_score or 50
        up_capture = capture_up_ratio or 100
        down_capture = capture_down_ratio or 100
        consistency = rolling_return_consistency or 50
        alpha = benchmark_alpha_3y or 0.0
        up_capture_score = min(100, max(0, up_capture))
        down_capture_score = min(100, max(0, 100 - (down_capture - 50)))
        alpha_score = max(0, min(100, 50 + alpha * 10))
        score = max(0, min(100, (risk_adj * 0.3 + up_capture_score * 0.2 + down_capture_score * 0.2 + consistency * 0.2 + alpha_score * 0.1)))
        if score >= 80:
            rating = PillarRating.HIGH
        elif score >= 60:
            rating = PillarRating.ABOVE_AVERAGE
        elif score >= 40:
            rating = PillarRating.AVERAGE
        elif score >= 20:
            rating = PillarRating.BELOW_AVERAGE
        else:
            rating = PillarRating.LOW
        risk_str = f"{risk_adj:.0f}" if risk_adj is not None else "N/A"
        up_str = f"{up_capture:.0f}" if up_capture is not None else "N/A"
        down_str = f"{down_capture:.0f}" if down_capture is not None else "N/A"
        alpha_str = f"{alpha:.1f}" if alpha is not None else "N/A"
        justification = f"Risk-adj return {risk_str}, up capture {up_str}%, down capture {down_str}%, alpha 3Y {alpha_str}%"
        return PillarScore(pillar_name="Performance", rating=rating, score=score, justification=justification, metrics=metrics)
    
    def evaluate_price_pillar(self, fund_id: str, expense_ratio_pct: Optional[float] = None, tax_drag_score: Optional[float] = None, load_structure_score: Optional[float] = None) -> PillarScore:
        metrics = {"expense_ratio_pct": expense_ratio_pct or 0.0, "tax_drag_score": tax_drag_score or 0.0, "load_structure_score": load_structure_score or 0.0}
        expense_score = 100
        if expense_ratio_pct is not None:
            if expense_ratio_pct <= 0.5:
                expense_score = 100
            elif expense_ratio_pct <= 1.0:
                expense_score = 80
            elif expense_ratio_pct <= 1.5:
                expense_score = 60
            elif expense_ratio_pct <= 2.0:
                expense_score = 40
            else:
                expense_score = 20
        tax_score = tax_drag_score or 50
        load_score = load_structure_score or 50
        score = max(0, min(100, (expense_score * 0.5 + tax_score * 0.3 + load_score * 0.2)))
        if score >= 80:
            rating = PillarRating.HIGH
        elif score >= 60:
            rating = PillarRating.ABOVE_AVERAGE
        elif score >= 40:
            rating = PillarRating.AVERAGE
        elif score >= 20:
            rating = PillarRating.BELOW_AVERAGE
        else:
            rating = PillarRating.LOW
        er_str = f"{expense_ratio_pct:.2f}%" if expense_ratio_pct is not None else "N/A"
        tax_str = f"{tax_score:.0f}" if tax_score is not None else "N/A"
        load_str = f"{load_score:.0f}" if load_score is not None else "N/A"
        justification = f"Expense ratio {er_str}, tax drag score {tax_str}, load structure {load_str}"
        return PillarScore(pillar_name="Price", rating=rating, score=score, justification=justification, metrics=metrics)
    
    def compute_composite_rating(self, people_score: PillarScore, process_score: PillarScore, parent_score: PillarScore, performance_score: PillarScore, price_score: PillarScore) -> tuple[CompositeRating, float, bool]:
        scores = [people_score.score, process_score.score, parent_score.score, performance_score.score, price_score.score]
        weights = [0.20, 0.25, 0.20, 0.25, 0.10]
        composite_score = sum(s * w for s, w in zip(scores, weights))
        veto_activated = any(p.fiduciary_veto for p in [people_score, process_score, parent_score, performance_score, price_score])
        if veto_activated:
            composite_rating = CompositeRating.NEGATIVE
        elif composite_score >= 85:
            composite_rating = CompositeRating.GOLD
        elif composite_score >= 70:
            composite_rating = CompositeRating.SILVER
        elif composite_score >= 55:
            composite_rating = CompositeRating.BRONZE
        elif composite_score >= 40:
            composite_rating = CompositeRating.NEUTRAL
        else:
            composite_rating = CompositeRating.NEGATIVE
        return composite_rating, composite_score, veto_activated
    
    def evaluate_fund(self, fund_id: str, fund_name: str, **kwargs) -> FundMedalistScore:
        people = self.evaluate_people_pillar(fund_id, manager_tenure_years=kwargs.get('manager_tenure_years'), team_stability_score=kwargs.get('team_stability_score'), manager_changes_count=kwargs.get('manager_changes_count', 0), manager_changes_last_12m=kwargs.get('manager_changes_last_12m', 0))
        process = self.evaluate_process_pillar(fund_id, strategy_consistency_score=kwargs.get('strategy_consistency_score'), parent_methodology_alignment=kwargs.get('parent_methodology_alignment'), process_deviation_count=kwargs.get('process_deviation_count', 0), process_documented=kwargs.get('process_documented', True))
        parent = self.evaluate_parent_pillar(fund_id, amc_governance_score=kwargs.get('amc_governance_score'), amc_fee_structure_score=kwargs.get('amc_fee_structure_score'), amc_stability_score=kwargs.get('amc_stability_score'), fund_size_crores=kwargs.get('fund_size_crores'))
        performance = self.evaluate_performance_pillar(fund_id, risk_adjusted_return_score=kwargs.get('risk_adjusted_return_score'), capture_up_ratio=kwargs.get('capture_up_ratio'), capture_down_ratio=kwargs.get('capture_down_ratio'), rolling_return_consistency=kwargs.get('rolling_return_consistency'), benchmark_alpha_3y=kwargs.get('benchmark_alpha_3y'))
        price = self.evaluate_price_pillar(fund_id, expense_ratio_pct=kwargs.get('expense_ratio_pct'), tax_drag_score=kwargs.get('tax_drag_score'), load_structure_score=kwargs.get('load_structure_score'))
        composite_rating, composite_score, veto_activated = self.compute_composite_rating(people, process, parent, performance, price)
        report_section = {"people_score": people.score, "people_rating": people.rating.value, "process_score": process.score, "process_rating": process.rating.value, "parent_score": parent.score, "parent_rating": parent.rating.value, "performance_score": performance.score, "performance_rating": performance.rating.value, "price_score": price.score, "price_rating": price.rating.value, "composite_score": composite_score, "composite_rating": composite_rating.value, "veto_activated": veto_activated}
        return FundMedalistScore(fund_id=fund_id, fund_name=fund_name, people=people, process=process, parent=parent, performance=performance, price=price, composite_rating=composite_rating, composite_score=composite_score, veto_activated=veto_activated, report_section=report_section)

    def evaluate_from_metrics(self, fund_id: str, fund_name: str, mrow: dict) -> FundMedalistScore:
        """Helper to evaluate fund from a metrics dictionary row (GAP-120, GAP-193)."""
        tenure = mrow.get("manager_tenure_years")
        if tenure is not None:
            try:
                tenure = float(tenure)
            except Exception:
                tenure = None
        er = mrow.get("ter_direct_pct") or mrow.get("expense_ratio") or mrow.get("er_direct")
        if er is not None:
            try:
                er = float(er)
            except Exception:
                er = None
        aum = mrow.get("aum_cr") or mrow.get("aum")
        if aum is not None:
            try:
                aum = float(aum)
            except Exception:
                aum = None
        alpha = mrow.get("alpha_annual_pct") or mrow.get("alpha_3y") or mrow.get("alpha")
        if alpha is not None:
            try:
                alpha = float(alpha)
            except Exception:
                alpha = None
        up_cap = mrow.get("up_capture_pct") or mrow.get("capture_ratio_up")
        down_cap = mrow.get("down_capture_pct") or mrow.get("capture_ratio_down")
        try:
            up_cap = float(up_cap) if up_cap is not None else None
            down_cap = float(down_cap) if down_cap is not None else None
        except Exception:
            up_cap, down_cap = None, None

        return self.evaluate_fund(
            fund_id=fund_id,
            fund_name=fund_name,
            manager_tenure_years=tenure,
            fund_size_crores=aum,
            expense_ratio_pct=er,
            benchmark_alpha_3y=alpha,
            capture_up_ratio=up_cap,
            capture_down_ratio=down_cap,
        )
    
    def generate_section_6_2_table(self, scores: List[FundMedalistScore]) -> str:
        lines = []
        lines.append("| Fund | People | Process | Parent | Performance | Price | Composite | Veto |")
        lines.append("|------|--------|---------|--------|-------------|-------|-----------|------|")
        for score in scores:
            lines.append(f"| {score.fund_name} | {score.people.rating.value} ({score.people.score:.0f}) | {score.process.rating.value} ({score.process.score:.0f}) | {score.parent.rating.value} ({score.parent.score:.0f}) | {score.performance.rating.value} ({score.performance.score:.0f}) | {score.price.rating.value} ({score.price.score:.0f}) | {score.composite_rating.value} ({score.composite_score:.0f}) | {'YES' if score.veto_activated else 'NO'} |")
        return "\n".join(lines)
