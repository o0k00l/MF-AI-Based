"""Exact scheme-category routing regressions for SIP candidate selection."""

import pytest

from core.fund_classifier import classify_fund_category


@pytest.mark.parametrize(
    "name,category,expected",
    [
        ("Example Large & Mid Cap Fund", "Large & Mid Cap", "Large & Mid Cap Equity"),
        ("Example Large Cap Fund", "Large Cap", "Large Cap Equity"),
        ("Example Focused Fund", "Focused", "Focused Equity"),
        ("Example Flexi Cap Fund", "Flexi Cap", "Flexi Cap Equity"),
        # Marketing names must not override authoritative category metadata.
        ("Large Cap Bluechip Fund", "Focused", "Focused Equity"),
        ("Focused Opportunities Fund", "Flexi Cap", "Flexi Cap Equity"),
        ("Large & Mid Cap Growth Fund", "Large Cap", "Large Cap Equity"),
        ("Large Cap Opportunities Fund", "Large & Mid Cap", "Large & Mid Cap Equity"),
    ],
)
def test_category_comes_only_from_exact_canonical_category(name, category, expected):
    assert classify_fund_category(name, category) == expected


@pytest.mark.parametrize(
    "name,category",
    [
        ("Focused Opportunities Fund", ""),
        ("Large & Mid Cap Fund", ""),
        ("Flexi Cap Fund", "Equity Opportunities"),
        ("Large Cap Fund", "Large Cap / Mid Cap"),
    ],
)
def test_missing_or_conflicting_category_is_not_guessed(name, category):
    assert classify_fund_category(name, category) == "Unknown"


def test_large_and_mid_cap_and_focused_are_not_eligible_for_neighboring_sleeves():
    assert classify_fund_category("Large & Mid Cap Fund", "Large & Mid Cap") != "Large Cap Equity"
    assert classify_fund_category("Focused Fund", "Focused") != "Flexi Cap Equity"
