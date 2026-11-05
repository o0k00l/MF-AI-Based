import pytest
from core.models import RiskTier
from core.eligibility import _risk_tier_to_int
from core.math_engine import _parse_sebi_risk_tier


@pytest.mark.parametrize(
    "tier_input,expected",
    [
        (RiskTier.CONSERVATIVE, 2),
        (RiskTier.MODERATE, 4),
        (RiskTier.AGGRESSIVE, 6),
        ("Conservative", 2),
        ("conservative", 2),
        ("Moderate", 4),
        ("moderate", 4),
        ("Aggressive", 6),
        ("aggressive", 6),
        ("Tier 1", 1),
        ("Tier 2", 2),
        ("Tier 3", 3),
        ("Tier 4", 4),
        ("Tier 5", 5),
        ("Tier 6", 6),
        ("Tier 3 (Moderate)", 3),
        ("Tier 4 (Moderately High)", 4),
        ("Capital Preservation", 1),
        ("Preservation", 1),
        ("Low to Moderate", 2),
        ("Moderately High", 4),
        ("Very High", 6),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (6, 6),
    ],
)
def test_risk_tier_parsers_produce_identical_results(tier_input, expected):
    res_eligibility = _risk_tier_to_int(tier_input)
    res_math_engine = _parse_sebi_risk_tier(tier_input)
    assert res_eligibility == expected
    assert res_math_engine == expected


def test_boolean_inputs_are_strictly_rejected():
    with pytest.raises(ValueError, match="boolean"):
        _risk_tier_to_int(True)
    with pytest.raises(ValueError, match="boolean"):
        _parse_sebi_risk_tier(False)


def test_custom_tier_requires_explicit_policy():
    with pytest.raises(ValueError, match="custom suitability policy"):
        _risk_tier_to_int(RiskTier.CUSTOM)
    with pytest.raises(ValueError, match="custom suitability policy"):
        _parse_sebi_risk_tier(RiskTier.CUSTOM)


def test_empty_or_unknown_risk_tier_is_rejected():
    with pytest.raises(ValueError):
        _risk_tier_to_int("")
    with pytest.raises(ValueError):
        _parse_sebi_risk_tier("")
    with pytest.raises(ValueError):
        _risk_tier_to_int("Hyper Ultra Extreme")
    with pytest.raises(ValueError):
        _parse_sebi_risk_tier("Hyper Ultra Extreme")
