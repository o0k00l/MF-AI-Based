import math
import pytest

from core.candidate_scoring import (
    LegacyFundSelectorDisabledError,
    ScoringWeights,
    calculate_candidate_6_pillar_score,
    normalize_metric,
)


def test_scoring_weights_reject_negative_and_out_of_range_values():
    assert not ScoringWeights(
        w_alpha=-0.1, w_sharpe=0.3, w_ter=0.2,
        w_downside_buffer=0.2, w_international=0.2, w_mpb_overlap=0.2,
    ).validate()
    assert not ScoringWeights(
        w_alpha=1.1, w_sharpe=0.0, w_ter=0.0,
        w_downside_buffer=0.0, w_international=0.0, w_mpb_overlap=-0.1,
    ).validate()


def test_scoring_weights_reject_non_finite_values():
    base = (0.25, 0.20, 0.15, 0.15, 0.15, 0.10)
    assert not ScoringWeights(float("nan"), *base[1:]).validate()
    assert not ScoringWeights(float("inf"), *base[1:]).validate()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_normalizer_rejects_non_finite_or_boolean_metrics(value):
    with pytest.raises(ValueError):
        normalize_metric(value, 0.0, 10.0)


def test_normalizer_rejects_reversed_bounds():
    with pytest.raises(ValueError, match="upper bound"):
        normalize_metric(5.0, 10.0, 0.0)


def test_negative_one_year_return_is_scored_as_a_bad_return_not_replaced_by_alpha():
    candidate = {
        "alpha_3y": 4.0,
        "return_1y": -5.0,
        "sharpe_3y": 0.8,
        "ter_direct_pct": 0.7,
        "cash_debt_buffer_pct": 0.0,
        "international_equity_pct": 0.0,
        "overlap_pct": 0.0,
    }
    # Use the only complete legacy category anchor set; Flexi Cap remains
    # unavailable until its independent 1Y-return anchor is approved.
    _, pillars = calculate_candidate_6_pillar_score(
        candidate, "Healthcare",
        weights=ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10),
    )
    assert pillars["alpha_return"] == 24.0



def test_metrics_loader_rejects_missing_evidence_file(tmp_path):
    from core.candidate_scoring import FiduciaryFundSelector

    with pytest.raises(FileNotFoundError, match="missing"):
        FiduciaryFundSelector(fund_metrics_path=tmp_path / "missing.json")


def test_metrics_loader_rejects_malformed_and_empty_evidence(tmp_path):
    import json
    from core.candidate_scoring import FiduciaryFundSelector

    path = tmp_path / "metrics.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        FiduciaryFundSelector(fund_metrics_path=path)

    path.write_text(json.dumps({"funds": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no fund records"):
        FiduciaryFundSelector(fund_metrics_path=path)


def test_metrics_loader_rejects_duplicate_fund_identity(tmp_path):
    import json
    from core.candidate_scoring import FiduciaryFundSelector

    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"funds": [
        {"id": "same", "name": "Fund A"},
        {"id": "same", "name": "Fund B"},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        FiduciaryFundSelector(fund_metrics_path=path)



def test_normalizer_uses_validated_numeric_bounds():
    assert normalize_metric("5", "0", "10") == 50.0


def test_legacy_named_fund_selector_is_quarantined(tmp_path):
    import json
    from core.candidate_scoring import FiduciaryFundSelector

    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"funds": [{"id": "unrelated", "name": "Unrelated"}]}), encoding="utf-8")
    selector = FiduciaryFundSelector(
        fund_metrics_path=metrics,
        weights=ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10),
    )
    with pytest.raises(LegacyFundSelectorDisabledError, match="legacy named-fund selector is disabled"):
        selector.score_flexi_cap_candidates()
    with pytest.raises(LegacyFundSelectorDisabledError, match="legacy named-fund comparison is disabled"):
        selector.get_comparison_summary()


def test_scoring_requires_explicit_composite_weights_and_category_ter_reference():
    candidate = {
        "alpha_3y": 3.0, "return_1y": 10.0,
        "sharpe_3y": 0.8, "ter_direct_pct": 0.7,
    }
    with pytest.raises(ValueError, match="Explicit approved scoring weights"):
        calculate_candidate_6_pillar_score(candidate, "Healthcare")


def _portfolio_score_evidence(candidate_id="candidate-1"):
    import hashlib
    overlap_bytes = b"reviewed overlap source"
    anchor_bytes = b"reviewed category anchor source"
    overlap_sha = hashlib.sha256(overlap_bytes).hexdigest()
    anchor_sha = hashlib.sha256(anchor_bytes).hexdigest()
    return {
        "overlap": {
            "status": "VERIFIED", "reviewer_attested": True,
            "candidate_id": candidate_id, "overlap_pct": 0.0,
            "coverage_pct": 100.0, "source_bytes": overlap_bytes,
            "source_document_sha256": overlap_sha, "source_ref": "sha256:" + overlap_sha,
            "as_of_date": "2026-11-04",
        },
        "anchors": {
            "status": "APPROVED", "reviewer_attested": True,
            "category": "Healthcare", "benchmark_identity": "NIFTY HEALTHCARE TRI",
            "reviewer_id": "independent-reviewer", "policy_version": "test-v1",
            "source_ref": "sha256:" + anchor_sha, "source_bytes": anchor_bytes,
            "source_document_sha256": anchor_sha, "effective_date": "2026-11-04",
            "anchor_set": {
                "alpha": [0, 10], "ret1y": [-20, 40], "sharpe": [0, 2],
                "ter": [0, 2], "buffer": [0, 100], "intl": [0, 100],
                "overlap": [0, 100],
            },
        },
    }


@pytest.mark.parametrize(
    ("missing_field", "message"),
    [
        ("cash_debt_buffer_pct", "cash/debt buffer"),
        ("international_equity_pct", "international exposure"),
    ],
)
def test_portfolio_aware_score_blocks_missing_defensive_and_international_evidence(missing_field, message):
    candidate = {
        "fund_id": "candidate-1", "alpha_3y": 2.0, "return_1y": 5.0,
        "sharpe_3y": 0.8, "ter_direct_pct": 0.8,
        "cash_debt_buffer_pct": 10.0, "international_equity_pct": 0.0,
    }
    candidate.pop(missing_field)
    evidence = _portfolio_score_evidence()
    with pytest.raises(ValueError, match=message):
        calculate_candidate_6_pillar_score(
            candidate, "Healthcare",
            weights=ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10),
            portfolio_aware=True,
            portfolio_overlap_evidence=evidence["overlap"],
            approved_category_anchor_evidence=evidence["anchors"],
            as_of_date="2026-11-04",
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("cash_debt_buffer_pct", "cash/debt buffer"),
        ("international_equity_pct", "international exposure"),
        ("overlap_pct", "portfolio overlap"),
    ],
)
def test_standalone_candidate_score_blocks_missing_explanatory_evidence(field, message):
    candidate = {
        "alpha_3y": 2.0, "return_1y": 5.0,
        "sharpe_3y": 0.8, "ter_direct_pct": 0.8,
        "cash_debt_buffer_pct": 10.0,
        "international_equity_pct": 0.0,
        "overlap_pct": 5.0,
    }
    candidate.pop(field)

    with pytest.raises(ValueError, match=message):
        calculate_candidate_6_pillar_score(
            candidate, "Healthcare",
            weights=ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10),
        )


def test_portfolio_aware_score_preserves_verified_zero_exposure_values():
    candidate = {
        "fund_id": "candidate-1", "alpha_3y": 2.0, "return_1y": 5.0,
        "sharpe_3y": 0.8, "ter_direct_pct": 0.8,
        "cash_debt_buffer_pct": 0.0, "international_equity_pct": 0.0,
    }
    evidence = _portfolio_score_evidence()
    _, pillars = calculate_candidate_6_pillar_score(
        candidate, "Healthcare",
        weights=ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10),
        portfolio_aware=True,
        portfolio_overlap_evidence=evidence["overlap"],
        approved_category_anchor_evidence=evidence["anchors"],
        as_of_date="2026-11-04",
    )
    assert pillars["downside_buffer"] == 0.0
    assert pillars["geographic_moat"] == 0.0
