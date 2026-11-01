"""
Risk profiling questionnaire and scoring.
Minimal implementation for Streamlit UI.
"""
from __future__ import annotations
from typing import List, Dict, Tuple

def get_questionnaire() -> List[Dict]:
    """Return the 10-question SEBI-style risk profiling questionnaire."""
    return [
        {
            "id": "q1",
            "text": "What is your age?",
            "type": "choice",
            "options": ["Under 30", "30-45", "45-55", "Over 55"],
            "scores": [4, 3, 2, 1]
        },
        {
            "id": "q2",
            "text": "What is your investment horizon?",
            "type": "choice",
            "options": ["Less than 3 years", "3-5 years", "5-10 years", "More than 10 years"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q3",
            "text": "How would you react if your portfolio dropped 20% in a month?",
            "type": "choice",
            "options": ["Sell everything", "Sell some", "Hold", "Buy more"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q4",
            "text": "What is your primary investment goal?",
            "type": "choice",
            "options": ["Capital preservation", "Steady income", "Balanced growth", "Aggressive growth"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q5",
            "text": "What percentage of your portfolio are you comfortable allocating to equities?",
            "type": "choice",
            "options": ["0-20%", "20-40%", "40-60%", "60-80%"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q6",
            "text": "How stable is your current income?",
            "type": "choice",
            "options": ["Unstable", "Somewhat stable", "Stable", "Very stable"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q7",
            "text": "Do you have adequate insurance (life, health) and emergency fund?",
            "type": "choice",
            "options": ["No", "Partial", "Yes, basic", "Yes, comprehensive"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q8",
            "text": "How much investment experience do you have?",
            "type": "choice",
            "options": ["None", "Beginner", "Intermediate", "Advanced"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q9",
            "text": "What is your liquidity requirement?",
            "type": "choice",
            "options": ["High (need access within 1 year)", "Medium (1-3 years)", "Low (3-5 years)", "Very low (5+ years)"],
            "scores": [1, 2, 3, 4]
        },
        {
            "id": "q10",
            "text": "How do you prefer to invest?",
            "type": "choice",
            "options": ["Lump sum only", "Mostly lump sum", "Mix of SIP and lump sum", "SIP only"],
            "scores": [1, 2, 3, 4]
        },
    ]

def compute_score(answers: Dict[str, int]) -> int:
    """Compute total risk score from answers (1-4 per question)."""
    return sum(answers.values())

def map_score_to_risk_bucket(score: int) -> Tuple[str, Dict]:
    """Map score to risk bucket with allocation targets."""
    if score <= 15:
        return "low", {
            "label": "Conservative",
            "equity": 20, "debt": 80,
            "desc": "Capital preservation focus"
        }
    elif score <= 22:
        return "low_to_moderate", {
            "label": "Conservative Moderate",
            "equity": 40, "debt": 60,
            "desc": "Income with inflation protection"
        }
    elif score <= 28:
        return "moderate", {
            "label": "Balanced",
            "equity": 60, "debt": 40,
            "desc": "Balanced growth (DEFAULT)"
        }
    elif score <= 34:
        return "moderately_high", {
            "label": "Growth",
            "equity": 75, "debt": 25,
            "desc": "Long-term wealth accumulation"
        }
    else:
        return "high", {
            "label": "Aggressive",
            "equity": 90, "debt": 10,
            "desc": "Maximum growth orientation"
        }