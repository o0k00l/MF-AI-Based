from datetime import date
import hashlib

import pytest

from core.candidate_scoring import ScoringWeights, calculate_candidate_6_pillar_score



def _weights():
    return ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10)


def _candidate(category="Healthcare"):
    return {
        "fund_id": "fund-1",
        "scheme_id": "scheme-1",
        "alpha_3y": 2.0,
        "return_1y": 8.0,
        "sharpe_3y": 0.8,
        "ter_direct_pct": 0.7,
        "cash_debt_buffer_pct": 10.0,
        "international_equity_pct": 0.0,
        "category": category,
    }


def _overlap_evidence(*, as_of=None, coverage=99.8, overlap=20.0, source_bytes=b"reviewed overlap source"):
    digest = hashlib.sha256(source_bytes).hexdigest()
    return {
        "status": "VERIFIED",
        "reviewer_attested": True,
        "candidate_id": "fund-1",
        "overlap_pct": overlap,
        "coverage_pct": coverage,
        "as_of_date": as_of or date.today().isoformat(),
        "source_ref": "sha256:" + digest,
        "source_document_sha256": digest,
        "source_bytes": source_bytes,
    }


def _anchor_evidence(*, category="Healthcare", as_of=None, anchor_set=None, source_bytes=b"approved benchmark anchors"):
    digest = hashlib.sha256(source_bytes).hexdigest()
    return {
        "status": "APPROVED",
        "reviewer_attested": True,
        "category": category,
        "benchmark_identity": "Example Category TRI",
        "effective_date": as_of or date.today().isoformat(),
        "reviewer_id": "independent-reviewer",
        "policy_version": "category-anchors-v1",
        "source_ref": "sha256:" + digest,
        "source_document_sha256": digest,
        "source_bytes": source_bytes,
        "anchor_set": anchor_set or {
            "alpha": [0, 10],
            "ret1y": [0, 30],
            "sharpe": [0.2, 1.2],
            "ter": [0.2, 1.2],
            "buffer": [0, 25],
            "intl": [0, 50],
            "overlap": [0, 100],
        },
    }


def _portfolio_score(**overrides):
    values = {
        "portfolio_aware": True,
        "portfolio_overlap_evidence": _overlap_evidence(),
        "approved_category_anchor_evidence": _anchor_evidence(),
        "as_of_date": date.today().isoformat(),
        "max_evidence_age_days": 30,
        "weights": _weights(),
    }
    values.update(overrides)
    return values


def test_portfolio_aware_score_rejects_missing_overlap_even_if_legacy_field_is_present():
    candidate = _candidate()
    candidate["overlap_pct"] = 0.0
    with pytest.raises(ValueError, match="Verified portfolio overlap evidence is required"):
        calculate_candidate_6_pillar_score(
            candidate,
            "Healthcare",
            portfolio_overlap_pct=0.0,
            **_portfolio_score(portfolio_overlap_evidence=None),
        )


def test_portfolio_aware_score_uses_verified_overlap_not_neutral_fallback():
    score, pillars = calculate_candidate_6_pillar_score(
        _candidate(), "Healthcare", **_portfolio_score()
    )
    assert 0.0 <= score <= 100.0
    assert pillars["portfolio_overlap"] == 80.0


@pytest.mark.parametrize(
    "evidence,reason",
    [
        (_overlap_evidence(coverage=99.4), "at least 99.5"),
        (_overlap_evidence(as_of="2026-01-01"), "stale or future-dated"),
    ],
)
def test_portfolio_aware_score_rejects_insufficient_stale_or_tampered_overlap(evidence, reason):
    with pytest.raises(ValueError, match=reason):
        calculate_candidate_6_pillar_score(
            _candidate(), "Healthcare",
            **_portfolio_score(portfolio_overlap_evidence=evidence),
        )


def test_portfolio_aware_score_rejects_overlap_for_another_candidate():
    evidence = _overlap_evidence()
    evidence["candidate_id"] = "other-fund"
    with pytest.raises(ValueError, match="candidate identity mismatch"):
        calculate_candidate_6_pillar_score(
            _candidate(), "Healthcare",
            **_portfolio_score(portfolio_overlap_evidence=evidence),
        )


def test_portfolio_aware_score_requires_approved_complete_category_anchor_source():
    incomplete = _anchor_evidence(anchor_set={"alpha": [0, 10], "sharpe": [0.2, 1.2]})
    with pytest.raises(ValueError, match="every required metric bound"):
        calculate_candidate_6_pillar_score(
            _candidate(), "Healthcare",
            **_portfolio_score(approved_category_anchor_evidence=incomplete),
        )


def test_portfolio_aware_score_rejects_unapproved_stale_or_wrong_category_anchors():
    unapproved = _anchor_evidence()
    unapproved["status"] = "PROVISIONAL"
    with pytest.raises(ValueError, match="approved category benchmark anchors"):
        calculate_candidate_6_pillar_score(
            _candidate(), "Healthcare",
            **_portfolio_score(approved_category_anchor_evidence=unapproved),
        )

    stale = _anchor_evidence(as_of="2026-01-01")
    with pytest.raises(ValueError, match="Category anchor evidence is stale"):
        calculate_candidate_6_pillar_score(
            _candidate(), "Healthcare",
            **_portfolio_score(approved_category_anchor_evidence=stale),
        )

    wrong_category = _anchor_evidence(category="Large Cap")
    with pytest.raises(ValueError, match="does not match candidate category"):
        calculate_candidate_6_pillar_score(
            _candidate(), "Healthcare",
            **_portfolio_score(approved_category_anchor_evidence=wrong_category),
        )


@pytest.mark.parametrize("category", ["Flexi Cap", "Mid Cap", "Large Cap"])
def test_legacy_category_score_does_not_borrow_missing_healthcare_return_bounds(category):
    with pytest.raises(ValueError, match="no complete approved anchor set"):
        calculate_candidate_6_pillar_score(_candidate(category), category, weights=_weights())


@pytest.mark.parametrize("category", ["Small Cap", "Multi Cap", "Debt", "Hybrid", "International"])
def test_unsupported_category_is_unavailable_until_explicit_approved_anchors(category):
    with pytest.raises(ValueError, match="Unsupported scoring category"):
        calculate_candidate_6_pillar_score(_candidate(category), category, weights=_weights())


def test_portfolio_aware_score_can_use_complete_external_approved_anchors_for_new_category():
    category = "Small Cap"
    score, pillars = calculate_candidate_6_pillar_score(
        _candidate(category),
        category,
        **_portfolio_score(approved_category_anchor_evidence=_anchor_evidence(category=category)),
    )
    assert 0.0 <= score <= 100.0
    assert pillars["portfolio_overlap"] == 80.0


def test_portfolio_aware_score_rejects_overlap_source_digest_mismatch():
    evidence = _overlap_evidence()
    evidence["source_document_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source digest"):
        calculate_candidate_6_pillar_score(
            _candidate(), "Healthcare",
            **_portfolio_score(portfolio_overlap_evidence=evidence),
        )


def test_verified_zero_overlap_is_not_treated_as_missing():
    evidence = _overlap_evidence(overlap=0.0)
    _, pillars = calculate_candidate_6_pillar_score(
        _candidate(), "Healthcare",
        **_portfolio_score(portfolio_overlap_evidence=evidence),
    )
    assert pillars["portfolio_overlap"] == 100.0
