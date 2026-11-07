"""Unit tests for services/goal_planner.py."""
from __future__ import annotations

import pytest
from services.goal_planner import (
    plan_goal,
    compute_expected_cagr,
    calculate_future_value,
    calculate_flat_monthly_sip,
    calculate_step_up_initial_sip,
)


def test_existing_portfolio_compounding_reduces_sip():
    """Verify that existing portfolio compounds and reduces the required SIP."""
    # Without existing portfolio:
    res_zero = plan_goal(
        goal_name="Retirement",
        cost_today_inr=50000000.0,
        horizon_years=15,
        existing_allocated_corpus_inr=0.0,
        inflation_rate_pct=6.0,
    )
    # With ₹50 Lakhs existing portfolio:
    res_with_portfolio = plan_goal(
        goal_name="Retirement",
        cost_today_inr=50000000.0,
        horizon_years=15,
        existing_allocated_corpus_inr=5000000.0,
        inflation_rate_pct=6.0,
    )

    # ₹50 Lakhs at 12% over 15 years compounds to ~₹2.73 Crore!
    assert res_with_portfolio.existing_corpus_future_val_inr > 27000000.0
    assert res_with_portfolio.net_corpus_needed_inr < res_zero.net_corpus_needed_inr
    assert res_with_portfolio.flat_monthly_sip_inr < res_zero.flat_monthly_sip_inr
    assert res_with_portfolio.existing_corpus_coverage_pct > 20.0


def test_step_up_sip_is_lower_than_flat_sip():
    """Verify that a 10% annual step-up requires significantly lower initial monthly SIP."""
    res = plan_goal(
        goal_name="Child Higher Education",
        cost_today_inr=2500000.0,
        horizon_years=10,
        annual_step_up_pct=10.0,
    )
    assert res.step_up_initial_sip_inr > 0
    assert res.step_up_initial_sip_inr < res.flat_monthly_sip_inr
    # Starting step-up SIP is typically 30% - 45% less than fixed flat SIP
    savings_pct = (res.flat_monthly_sip_inr - res.step_up_initial_sip_inr) / res.flat_monthly_sip_inr
    assert savings_pct > 0.25


def test_horizon_aware_expected_cagr():
    """Returns conservative CAGR for short horizons and higher CAGR for long horizons."""
    assert compute_expected_cagr(2) == 7.5
    assert compute_expected_cagr(4) == 8.5
    assert compute_expected_cagr(7) == 10.5
    assert compute_expected_cagr(15) == 12.0


def test_fully_funded_goal_requires_zero_sip():
    """If existing portfolio compounds to exceed future target, required SIP is zero."""
    res = plan_goal(
        goal_name="Home Down Payment",
        cost_today_inr=2000000.0,
        horizon_years=5,
        existing_allocated_corpus_inr=3000000.0,  # ₹30L existing covers ₹20L in 5y
        inflation_rate_pct=5.0,
    )
    assert res.net_corpus_needed_inr == 0.0
    assert res.flat_monthly_sip_inr == 0.0
    assert res.step_up_initial_sip_inr == 0.0
    assert "Fully Funded" in res.feasibility_status

