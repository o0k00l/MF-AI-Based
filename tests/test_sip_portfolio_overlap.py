"""Portfolio-aware SIP candidate overlap regressions."""
import pytest

from core.eligibility import _portfolio_weighted_constituent_overlap_pct, filter_candidates


def _disclosure(weights):
    return {
        "lookthrough_status": "VERIFIED",
        "constituent_weights_coverage_pct": 100.0,
        "constituent_weights": weights,
    }


def test_overlap_is_weighted_by_existing_equity_value_not_equal_fund_count():
    portfolio = [
        {
            **_disclosure({"ALPHA LTD": 50.0, "BETA LTD": 50.0}),
            "current_value_inr": 900.0,
            "equity_pct": 100.0,
            "asset_class": "LARGE_CAP",
        },
        {
            **_disclosure({"ALPHA LTD": 100.0}),
            "current_value_inr": 100.0,
            "equity_pct": 100.0,
            "asset_class": "MID_CAP",
        },
    ]
    candidate = _disclosure({"ALPHA LTD": 60.0, "BETA LTD": 40.0})

    # Existing portfolio exposure is 55% ALPHA / 45% BETA after value weighting.
    assert _portfolio_weighted_constituent_overlap_pct(candidate, portfolio) == pytest.approx(95.0)


def test_missing_existing_holding_lookthrough_is_not_treated_as_zero_overlap():
    portfolio = [
        {
            "current_value_inr": 1000.0,
            "equity_pct": 100.0,
            "asset_class": "FLEXI_CAP",
            "lookthrough_status": "MISSING",
            "constituent_weights_coverage_pct": None,
            "constituent_weights": None,
        }
    ]
    candidate = _disclosure({"ALPHA LTD": 100.0})

    assert _portfolio_weighted_constituent_overlap_pct(candidate, portfolio) is None


def test_candidate_without_verified_lookthrough_is_not_rankable_for_portfolio_fit():
    portfolio = [
        {
            **_disclosure({"ALPHA LTD": 100.0}),
            "current_value_inr": 1000.0,
            "equity_pct": 100.0,
            "asset_class": "LARGE_CAP",
        }
    ]
    candidate = {
        "lookthrough_status": "MISSING",
        "constituent_weights_coverage_pct": None,
        "constituent_weights": None,
    }

    assert _portfolio_weighted_constituent_overlap_pct(candidate, portfolio) is None


@pytest.mark.parametrize("limit", [-0.1, 100.1, float("nan"), True, "not-a-number"])
def test_candidate_filter_rejects_invalid_overlap_limit(limit):
    with pytest.raises(ValueError):
        filter_candidates([], [], max_overlap_limit_pct=limit)


def test_actual_sip_overlap_uses_equity_value_not_total_portfolio_value():
    from types import SimpleNamespace
    from core.math_engine import compute_candidate_portfolio_overlap

    equity_holding = SimpleNamespace(
        fund_id="EQ-1",
        current_value_inr=1000.0,
        equity_pct=100.0,
        constituent_weights={"ALPHA LTD": 50.0, "BETA LTD": 50.0},
        constituent_weights_coverage_pct=100.0,
    )
    debt_holding_without_equity_lookthrough = SimpleNamespace(
        fund_id="DEBT-1",
        current_value_inr=1000.0,
        equity_pct=0.0,
        constituent_weights=None,
        constituent_weights_coverage_pct=None,
    )
    candidate = {
        "constituent_weights": {"ALPHA LTD": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }

    # Debt doubles total portfolio value but must not dilute equity-stock overlap.
    assert compute_candidate_portfolio_overlap(
        candidate, [equity_holding, debt_holding_without_equity_lookthrough]
    ) == pytest.approx(50.0)


def test_actual_sip_overlap_is_zero_for_verified_debt_only_portfolio():
    from types import SimpleNamespace
    from core.math_engine import compute_candidate_portfolio_overlap

    debt_holding = SimpleNamespace(
        fund_id="DEBT-1",
        current_value_inr=5000.0,
        equity_pct=0.0,
        constituent_weights=None,
        constituent_weights_coverage_pct=None,
    )
    candidate = {
        "constituent_weights": {"ALPHA LTD": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }

    assert compute_candidate_portfolio_overlap(candidate, [debt_holding]) == 0.0


def test_explicit_multi_cap_category_is_not_misclassified_as_flexi_cap():
    from core.math_engine import _infer_asset_class
    from core.models import AssetClass

    assert _infer_asset_class("Multi Cap", 95.0, 5.0, 35.0, 35.0, 25.0) == AssetClass.MULTI_CAP


def test_explicit_large_cap_category_is_not_misclassified_as_flexi_cap():
    from core.math_engine import _infer_asset_class
    from core.models import AssetClass

    assert _infer_asset_class("Large Cap", 95.0, 5.0, 85.0, 10.0, 5.0) == AssetClass.LARGE_CAP


def test_explicit_international_equity_category_is_preserved():
    from core.math_engine import _infer_asset_class
    from core.models import AssetClass

    assert _infer_asset_class("International Equity", 98.0, 2.0, 0.0, 0.0, 0.0) == AssetClass.INTERNATIONAL


def test_debt_liquid_and_international_holdings_are_included_in_total_saa_buckets():
    from types import SimpleNamespace
    from core.math_engine import calculate_saa_drift_minimizer
    from core.models import AssetClass

    holdings = [
        SimpleNamespace(current_value_inr=1000.0, asset_class=AssetClass.DEBT_LIQUID, equity_pct=0.0, debt_pct=100.0),
        SimpleNamespace(current_value_inr=1000.0, asset_class=AssetClass.INTERNATIONAL, equity_pct=100.0, debt_pct=0.0),
    ]
    result = calculate_saa_drift_minimizer(
        holdings, {"equity_pct": 50.0, "debt_liquid_pct": 50.0, "cash_pct": 0.0}, 0.0
    )

    assert result.current_allocation["Equity"] == pytest.approx(50.0)
    assert result.current_allocation["Debt"] == pytest.approx(50.0)
    assert "Other" not in result.current_allocation


def test_portfolio_gate_summary_preserves_amc_identity_for_candidate_concentration_gate():
    from types import SimpleNamespace
    from core.math_engine import _build_portfolio_gate_summary

    result = _build_portfolio_gate_summary([
        SimpleNamespace(scheme="ABC Direct Growth", current_value_inr=25000.0, amc_name="ABC Asset Management")
    ])
    assert result == [{
        "scheme": "ABC Direct Growth",
        "value": 25000.0,
        "amc_name": "ABC Asset Management",
    }]


@pytest.mark.parametrize("ips", [
    {"monthly_sip_budget": True},
    {"monthly_sip_budget": 10000, "lumpsum_budget": False},
    {"monthly_sip_budget": 10000, "emergency_months": True},
])
def test_ips_numeric_contract_rejects_boolean_values(ips):
    from core.math_engine import _validated_ips_numeric_inputs

    with pytest.raises(ValueError, match="must not be booleans"):
        _validated_ips_numeric_inputs(ips)


def test_ips_numeric_contract_rejects_missing_budget_and_nonfinite_values():
    from core.math_engine import _validated_ips_numeric_inputs

    with pytest.raises(ValueError, match="monthly_sip_budget"):
        _validated_ips_numeric_inputs({})
    with pytest.raises(ValueError, match="finite"):
        _validated_ips_numeric_inputs({"monthly_sip_budget": float("nan")})


def test_saa_drift_refuses_to_invent_default_aggressive_target():
    from types import SimpleNamespace
    from core.math_engine import calculate_saa_drift_minimizer
    from core.models import AssetClass

    holdings = [SimpleNamespace(current_value_inr=1000.0, asset_class=AssetClass.EQUITY, equity_pct=100.0, debt_pct=0.0)]
    with pytest.raises(ValueError, match="explicit equity allocation"):
        calculate_saa_drift_minimizer(holdings, {}, 1000.0)


def test_saa_drift_accepts_explicit_zero_equity_target_without_fallback():
    from types import SimpleNamespace
    from core.math_engine import calculate_saa_drift_minimizer
    from core.models import AssetClass

    holdings = [SimpleNamespace(current_value_inr=1000.0, asset_class=AssetClass.DEBT, equity_pct=0.0, debt_pct=100.0)]
    result = calculate_saa_drift_minimizer(
        holdings, {"equity_pct": 0.0, "debt_liquid_pct": 100.0, "cash_pct": 0.0}, 1000.0
    )
    assert result.target_allocation == {"Equity": 0.0, "Debt": 100.0, "Cash": 0.0}



def test_metrics_matching_rejects_token_similarity_without_exact_identity():
    from core.math_engine import _find_matching_metric

    metrics = {
        "abc_flexi": {"id": "abc_flexi", "name": "ABC Flexi Cap Fund", "scheme": "ABC Flexi Cap Fund"},
    }
    assert _find_matching_metric("ABC Large Cap Fund Direct Growth", metrics, {}) is None


def test_metrics_matching_accepts_exact_normalized_scheme_identity():
    from core.math_engine import _find_matching_metric

    metrics = {
        "abc_flexi": {"id": "abc_flexi", "name": "ABC Flexi Cap Fund", "scheme": "ABC Flexi Cap Fund"},
    }
    result = _find_matching_metric("ABC Flexi-Cap Fund (Direct) - Growth", metrics, {})
    assert result is None  # plan/option-bearing CAS name is not the same identity


def test_metrics_matching_requires_reviewed_alias_for_plan_option_variants():
    from core.math_engine import _find_matching_metric

    metrics = {
        "abc_flexi_direct_growth": {
            "id": "abc_flexi_direct_growth",
            "name": "ABC Flexi Cap Fund Direct Growth",
        },
    }
    result = _find_matching_metric(
        "ABC Flexi Cap Fund (Direct) - Growth",
        metrics,
        {"ABC Flexi Cap Fund (Direct) - Growth": "abc_flexi_direct_growth"},
    )
    assert result is metrics["abc_flexi_direct_growth"]


def test_metrics_matching_rejects_ambiguous_exact_name():
    from core.math_engine import _find_matching_metric

    metrics = {
        "scheme_a": {"id": "scheme_a", "name": "ABC Flexi Cap Fund"},
        "scheme_b": {"id": "scheme_b", "scheme": "ABC Flexi Cap Fund"},
    }
    assert _find_matching_metric("ABC Flexi Cap Fund", metrics, {}) is None
