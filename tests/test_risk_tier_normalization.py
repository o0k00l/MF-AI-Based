import pytest

from core.eligibility import _risk_tier_to_int


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Moderate", 4),
        ("moderate risk", 4),
        ("risk_tier.moderate", 4),
        ("Moderately High", 4),
        ("Tier 3 (Moderate)", 3),
        ("Tier 4 (Moderately High)", 4),
        ("Tier 5 (High)", 5),
        ("Tier 6 (Very High)", 6),
    ],
)
def test_risk_tier_labels_have_one_unambiguous_normalization(label, expected):
    assert _risk_tier_to_int(label) == expected


def test_ambiguous_moderate_substrings_are_rejected_instead_of_misclassified():
    with pytest.raises(ValueError, match="Unrecognized risk tier"):
        _risk_tier_to_int("moderate-plus")
