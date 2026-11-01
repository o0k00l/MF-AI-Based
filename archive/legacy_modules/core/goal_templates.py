"""
Goal templates and SIP allocation helpers.
Minimal implementation for Streamlit UI.
"""
from __future__ import annotations
from typing import Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class Goal:
    name: str
    target_amount: float
    target_year: int
    priority: int  # 1 = highest
    current_value: float = 0.0

GOAL_TEMPLATES = {
    "retirement": {"name": "Retirement", "horizon_years": 20, "priority": 1, "inflation_rate": 0.06},
    "child_education": {"name": "Child Education", "horizon_years": 15, "priority": 1, "inflation_rate": 0.10},
    "house": {"name": "House Purchase", "horizon_years": 10, "priority": 2, "inflation_rate": 0.07},
    "emergency": {"name": "Emergency Fund", "horizon_years": 1, "priority": 1, "inflation_rate": 0.06},
    "custom": {"name": "Custom Goal", "horizon_years": 10, "priority": 2, "inflation_rate": 0.06},
}

def create_goal(name: str, target_amount: float, target_year: int, priority: int = 2, template: str = "custom") -> Goal:
    """Create a goal from template or custom parameters."""
    t = GOAL_TEMPLATES.get(template, GOAL_TEMPLATES["custom"])
    return Goal(
        name=name or t["name"],
        target_amount=target_amount,
        target_year=target_year,
        priority=priority,
        current_value=0.0
    )

def inflation_adjusted_target(present_value: float, years: int, inflation_rate: float = 0.06) -> float:
    """Calculate future value adjusted for inflation."""
    return present_value * ((1 + inflation_rate) ** years)

def allocate_sip_to_goals(goals: List[Goal], monthly_sip: float, expected_return: float = 0.12) -> Dict[str, float]:
    """
    Allocate monthly SIP across goals by priority.
    Returns dict of goal_name -> monthly_allocation.
    """
    # Sort by priority (1 = highest)
    sorted_goals = sorted(goals, key=lambda g: g.priority)
    allocations = {}
    remaining = monthly_sip
    
    for goal in sorted_goals:
        years_left = max(1, goal.target_year - 2026)
        months_left = years_left * 12
        
        # Future value needed
        fv_needed = goal.target_amount - goal.current_value * (1 + expected_return) ** years_left
        
        # Monthly SIP needed for this goal (simplified)
        if months_left > 0:
            monthly_needed = fv_needed * (expected_return / 12) / ((1 + expected_return / 12) ** months_left - 1)
        else:
            monthly_needed = 0
        
        allocation = min(max(monthly_needed, 0), remaining)
        allocations[goal.name] = round(allocation, 2)
        remaining -= allocation
    
    # Any remainder goes to lowest priority goal
    if remaining > 0 and sorted_goals:
        allocations[sorted_goals[-1].name] = round(allocations.get(sorted_goals[-1].name, 0) + remaining, 2)
    
    return allocations