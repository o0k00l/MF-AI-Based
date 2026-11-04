import math
import pytest

from core.candidate_scoring import (
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
    assert not ScoringWeights(w_alpha=float("nan")).validate()
    assert not ScoringWeights(w_alpha=float("inf")).validate()


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
    }
    _, pillars = calculate_candidate_6_pillar_score(candidate, "Flexi Cap")
    assert pillars["alpha_return"] == 30.0



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
