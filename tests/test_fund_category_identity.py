import pytest

from core.fund_classifier import classify_fund_category


@pytest.mark.parametrize(
    "category,expected",
    [
        ("Large & Mid Cap", "Large & Mid Cap Equity"),
        ("Large and Mid Cap", "Large & Mid Cap Equity"),
        ("Focused Fund", "Focused Equity"),
        ("Flexi Cap", "Flexi Cap Equity"),
        ("Large Cap", "Large Cap Equity"),
    ],
)
def test_verified_category_keeps_distinct_sebi_categories(category, expected):
    assert classify_fund_category("Generic Scheme Name", category) == expected


@pytest.mark.parametrize(
    "scheme_name,category,expected",
    [
        ("ABC Large & Mid Cap Fund", "Large Cap", "Large Cap Equity"),
        ("ABC Focused Fund", "Flexi Cap", "Flexi Cap Equity"),
        ("ABC Flexi Cap Fund", "Focused Fund", "Focused Equity"),
        ("ABC Large Cap Bluechip Fund", "Large & Mid Cap", "Large & Mid Cap Equity"),
    ],
)
def test_scheme_name_cannot_override_canonical_category(scheme_name, category, expected):
    assert classify_fund_category(scheme_name, category) == expected


def test_unknown_or_missing_category_is_not_inferred_from_scheme_name():
    assert classify_fund_category("ABC Large Cap Fund", "") == "Unknown"
    assert classify_fund_category("ABC Flexi Cap Fund", "Special Opportunities") == "Unknown"
