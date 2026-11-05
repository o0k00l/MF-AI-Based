import pytest
from core.fund_classifier import FUND_CATEGORY_TAXONOMY, classify_fund_category


def test_large_and_mid_cap_is_distinct_taxonomy_category():
    assert "Large & Mid Cap Equity" in FUND_CATEGORY_TAXONOMY
    tokens = FUND_CATEGORY_TAXONOMY["Large & Mid Cap Equity"]
    assert "large & mid cap" in tokens
    assert "large and mid cap" in tokens

    # Must NOT be in Large Cap Equity
    lc_tokens = FUND_CATEGORY_TAXONOMY["Large Cap Equity"]
    assert "large & mid cap" not in lc_tokens
    assert "large and mid cap" not in lc_tokens


def test_focused_equity_is_distinct_taxonomy_category():
    assert "Focused Equity" in FUND_CATEGORY_TAXONOMY
    tokens = FUND_CATEGORY_TAXONOMY["Focused Equity"]
    assert "focused" in tokens

    # Must NOT be in Flexi Cap Equity
    flexi_tokens = FUND_CATEGORY_TAXONOMY["Flexi Cap Equity"]
    assert "focused" not in flexi_tokens


def test_classify_fund_category_distinguishes_large_mid_from_large_cap():
    assert classify_fund_category("Fund Name", "Large and Mid Cap") == "Large & Mid Cap Equity"
    assert classify_fund_category("Fund Name", "Large & Mid Cap") == "Large & Mid Cap Equity"
    assert classify_fund_category("Fund Name", "Large Cap") == "Large Cap Equity"


def test_classify_fund_category_distinguishes_focused_from_flexi_cap():
    assert classify_fund_category("Fund Name", "Focused") == "Focused Equity"
    assert classify_fund_category("Fund Name", "Focused Fund") == "Focused Equity"
    assert classify_fund_category("Fund Name", "Flexi Cap") == "Flexi Cap Equity"


def test_name_tokens_do_not_override_verified_fund_category():
    assert classify_fund_category("Marketing Focused Super Fund", "Large Cap") == "Large Cap Equity"
    assert classify_fund_category("Marketing Midcap Winner", "Large and Mid Cap") == "Large & Mid Cap Equity"
