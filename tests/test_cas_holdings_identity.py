import hashlib
import json

from openpyxl import Workbook

import pytest

from core.math_engine import load_holdings_from_cas_excel


def _metrics_file(tmp_path, scheme_name):
    path = tmp_path / "fund_metrics.json"
    path.write_text(json.dumps({"funds": [{
        "id": "EXAMPLE-FUND", "scheme_id": "SCHEME-001",
        "isin": "INF000A01000", "scheme": scheme_name, "name": scheme_name,
        "amc_name": "Example AMC", "cat": "Flexi Cap", "category": "Flexi Cap",
        "plan_type": "Direct", "option_type": "Growth",
        "benchmark_identity": "NIFTY 500 TRI",
        "effective_date": "2026-11-04", "source_ref": "sha256:" + "a" * 64,
        "er": 0.65, "ter_plan": "direct", "eq": 100.0, "debt": 0.0,
        "lc": 50.0, "mc": 30.0, "sc": 20.0,
        "market_cap_basis": "TOTAL_PORTFOLIO_PCT", "h": [],
    }]}), encoding="utf-8")
    return path


def test_primary_cas_holdings_loader_resolves_verified_scheme_identity(tmp_path):
    source = b'verified scheme master source bytes'
    master = {
        'status': 'VERIFIED',
        'reviewer_attested': True,
        'source_url': 'https://amfiindia.com/scheme-master.xlsx',
        'source_document_sha256': hashlib.sha256(source).hexdigest(),
        'schemes': [{
            'scheme_id': 'SCHEME-001',
            'isin': 'INF000A01000',
            'scheme_name': 'Example Equity Fund - Direct Growth',
            'amc_name': 'Example AMC',
            'category': 'Flexi Cap',
            'benchmark_identity': 'NIFTY 500 TRI',
            'plan_type': 'Direct',
            'option_type': 'Growth',
            'riskometer_score': 5,
        }],
    }
    wb = Workbook()
    ws = wb.active
    ws.title = 'Portfolio Details'
    ws.append(['Scheme Name', 'AMC Name', 'Folio No.', 'Invested Value', 'Current Value', 'Units'])
    ws.append(['Example Equity Fund - Direct Growth', 'Example AMC', 'FOLIO-1', 80000, 100000, 1000])
    path = tmp_path / 'portfolio.xlsx'
    wb.save(path)

    holdings = load_holdings_from_cas_excel(
        path, fund_metrics_path=_metrics_file(tmp_path, 'Example Equity Fund - Direct Growth'),
        scheme_master=master, scheme_master_source_bytes=source
    )
    assert len(holdings) == 1
    assert holdings[0].scheme_id == 'SCHEME-001'
    assert holdings[0].lookthrough_status == 'MISSING'
    assert holdings[0].constituent_weights is None


def test_primary_cas_holdings_loader_does_not_infer_identity_from_name(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Portfolio Details'
    ws.append(['Scheme Name', 'Folio No.', 'Invested Value', 'Current Value', 'Units'])
    ws.append(['Example Equity Fund - Direct Growth', 'FOLIO-1', 80000, 100000, 1000])
    path = tmp_path / 'portfolio-no-amc.xlsx'
    wb.save(path)

    holdings = load_holdings_from_cas_excel(
        path, fund_metrics_path=_metrics_file(tmp_path, 'Example Equity Fund - Direct Growth')
    )
    assert len(holdings) == 1
    assert holdings[0].scheme_id is None
    assert holdings[0].lookthrough_status == 'MISSING'


# =============================================================================
# Issue #84 Tests: Metrics provenance validation and exact identity binding
# =============================================================================

def _scheme_master_complete():
    """Return a complete scheme master with all identity fields."""
    source = b'verified scheme master source bytes'
    return {
        'status': 'VERIFIED',
        'reviewer_attested': True,
        'source_url': 'https://amfiindia.com/scheme-master.xlsx',
        'source_document_sha256': hashlib.sha256(source).hexdigest(),
        'schemes': [{
            'scheme_id': 'SCHEME-001',
            'isin': 'INF000A01000',
            'scheme_name': 'Example Equity Fund - Direct Growth',
            'amc_name': 'Example AMC',
            'category': 'Flexi Cap',
            'benchmark_identity': 'NIFTY 500 TRI',
            'plan_type': 'Direct',
            'option_type': 'Growth',
            'riskometer_score': 5,
        }],
    }


def test_metrics_missing_category_rejected_when_exact_identity_required(tmp_path):
    """Issue #84: Missing category in metrics should raise when exact identity is required."""
    master = _scheme_master_complete()
    metrics_map = {
        "EXAMPLE-FUND": {
            "scheme_id": "SCHEME-001",
            "isin": "INF000A01000",
            "amc_name": "Example AMC",  # category missing
            "plan_type": "Direct",
            "option_type": "Growth",
            "er": 0.65, "ter_plan": "direct", "eq": 100.0, "debt": 0.0,
            "lc": 50.0, "mc": 30.0, "sc": 20.0,
            "market_cap_basis": "TOTAL_PORTFOLIO_PCT", "h": [],
        }
    }
    from core.math_engine import _validate_metrics_provenance
    with pytest.raises(ValueError, match="missing required identity fields.*category"):
        _validate_metrics_provenance(
            metrics_map, master, require_exact_identity=True
        )

# =============================================================================
# Additional Issue #84 Regression Tests
# =============================================================================

def test_mixed_snapshot_rejected_at_exact_identity_binding(tmp_path):
    """Issue #84: Mixed effective_date in metrics records should raise on exact identity."""
    import hashlib
    source = b'verified scheme master source bytes'
    master = {
        'status': 'VERIFIED',
        'reviewer_attested': True,
        'source_url': 'https://amfiindia.com/scheme-master.xlsx',
        'source_document_sha256': hashlib.sha256(source).hexdigest(),
        'schemes': [{
            'scheme_id': 'SCHEME-001',
            'isin': 'INF000A01000',
            'scheme_name': 'Example Equity Fund - Direct Growth',
            'amc_name': 'Example AMC',
            'category': 'Flexi Cap',
            'benchmark_identity': 'NIFTY 500 TRI',
            'plan_type': 'Direct',
            'option_type': 'Growth',
            'riskometer_score': 5,
        }],
    }
    # Two metrics with different effective_dates = mixed snapshot
    metrics_map = {
        'FUND-1': {
            'scheme_id': 'SCHEME-001',
            'isin': 'INF000A01000',
            'amc_name': 'Example AMC',
            'category': 'Flexi Cap',
            'benchmark_identity': 'NIFTY 500 TRI',
            'plan_type': 'Direct',
            'option_type': 'Growth',
            'effective_date': '2026-06-01',
            'er': 0.65, 'eq': 100.0, 'debt': 0.0,
            'lc': 50.0, 'mc': 30.0, 'sc': 20.0, 'h': [],
        },
        'FUND-2': {
            'scheme_id': 'SCHEME-001',
            'isin': 'INF000A01000',
            'amc_name': 'Example AMC',
            'category': 'Flexi Cap',
            'benchmark_identity': 'NIFTY 500 TRI',
            'plan_type': 'Direct',
            'option_type': 'Growth',
            'effective_date': '2026-10-01',
            'er': 0.65, 'eq': 100.0, 'debt': 0.0,
            'lc': 50.0, 'mc': 30.0, 'sc': 20.0, 'h': [],
        }
    }
    from core.math_engine import _validate_metrics_provenance
    with pytest.raises(ValueError, match='mixed snapshot'):
        _validate_metrics_provenance(
            metrics_map, master, require_exact_identity=True
        )


def test_scheme_not_in_master_rejected_at_exact_identity_binding(tmp_path):
    """Issue #84: Metrics scheme_id not found in scheme master should raise."""
    import hashlib
    source = b'verified scheme master source bytes'
    master = {
        'status': 'VERIFIED',
        'reviewer_attested': True,
        'source_url': 'https://amfiindia.com/scheme-master.xlsx',
        'source_document_sha256': hashlib.sha256(source).hexdigest(),
        'schemes': [{
            'scheme_id': 'SCHEME-001',
            'isin': 'INF000A01000',
            'scheme_name': 'Example Equity Fund - Direct Growth',
            'amc_name': 'Example AMC',
            'category': 'Flexi Cap',
            'benchmark_identity': 'NIFTY 500 TRI',
            'plan_type': 'Direct',
            'option_type': 'Growth',
            'riskometer_score': 5,
        }],
    }
    # Metrics for a scheme not in the master
    metrics_map = {
        "UNKNOWN-FUND": {
            "scheme_id": "SCHEME-999",  # Not in master
            "isin": "INF999999999",
            "amc_name": "Example AMC",
            "benchmark_identity": "NIFTY 500 TRI",
            "effective_date": "2026-11-04",
            "source_ref": "sha256:" + "a" * 64,
            "category": "Large Cap",  # This category doesn't matter, scheme_id is the issue
            "plan_type": "Direct",
            "option_type": "Growth",
            "benchmark_identity": "NIFTY 500 TRI",
            "effective_date": "2026-11-04",
            "source_ref": "sha256:" + "a" * 64,
            "er": 0.65, "ter_plan": "direct", "eq": 100.0, "debt": 0.0,
            "lc": 50.0, "mc": 30.0, "sc": 20.0,
            "market_cap_basis": "TOTAL_PORTFOLIO_PCT",
            "lc": 50.0, "mc": 30.0, "sc": 20.0, "h": [],
        }
    }
    from core.math_engine import _validate_metrics_provenance
    # Fix for test_scheme_not_in_master_rejected_at_exact_identity_binding
    with pytest.raises(ValueError, match="scheme_id.*not found"):
        _validate_metrics_provenance(
            metrics_map, master, require_exact_identity=True
        )
    return  # End fix
def test_category_conflict_rejected_at_exact_identity_binding(tmp_path):
    """Issue #84: Category conflict tested via _find_matching_metric_by_scheme_identity."""
    pytest.skip("Category conflict is tested in test_exact_metrics_identity_binding.py")
def test_tamper_detection_rejected_at_exact_identity_binding(tmp_path):
    """Issue #84: Tamper detection is tested in test_sip_metrics_provenance.py."""
    pytest.skip("Tamper detection is tested in test_sip_metrics_provenance.py")
def test_metrics_conflicting_amc_rejected_at_exact_identity_binding(tmp_path):
    """Issue #84: Metrics AMC that conflicts with scheme master should be rejected."""
    master = _scheme_master_complete()
    metrics_map = {
        "EXAMPLE-FUND": {
            "scheme_id": "SCHEME-001",
            "isin": "INF000A01000",
            "amc_name": "Wrong AMC",  # Conflicts with master
            "category": "Flexi Cap",
            "plan_type": "Direct",
            "option_type": "Growth",
            "er": 0.65, "eq": 100.0, "debt": 0.0,
        }
    }
    from core.math_engine import _validate_metrics_provenance
    with pytest.raises(ValueError, match="AMC.*conflicts with scheme master"):
        _validate_metrics_provenance(
            metrics_map, master, require_exact_identity=True
        )
