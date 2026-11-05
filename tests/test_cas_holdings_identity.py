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
        "er": 0.65, "eq": 100.0, "debt": 0.0,
        "lc": 50.0, "mc": 30.0, "sc": 20.0, "h": [],
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
            "er": 0.65, "eq": 100.0, "debt": 0.0,
            "lc": 50.0, "mc": 30.0, "sc": 20.0, "h": [],
        }
    }
    from core.math_engine import _validate_metrics_provenance
    with pytest.raises(ValueError, match="missing required identity fields.*category"):
        _validate_metrics_provenance(
            metrics_map, master, require_exact_identity=True
        )


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
