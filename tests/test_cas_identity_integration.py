import hashlib

from openpyxl import Workbook

from core.math_engine import parse_cas


def test_active_core_cas_parser_resolves_only_verified_exact_identity(tmp_path):
    source = b'verified scheme master bytes'
    master = {
        'status': 'VERIFIED',
        'reviewer_attested': True,
        'source_url': 'https://amfiindia.com/master.xlsx',
        'source_document_sha256': hashlib.sha256(source).hexdigest(),
        'schemes': [{
            'scheme_id': 'SCHEME-CORE-1',
            'isin': 'INF000A01001',
            'scheme_name': 'Example Equity Fund - Direct Growth',
            'amc_name': 'Example AMC',
            'riskometer_score': 5,
        }],
    }
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Portfolio Details'
    sheet.append(['To Date', '31-Oct-2026'])
    sheet.append(['Scheme Name', 'AMC Name', 'Folio No.', 'Invested Value', 'Current Value'])
    sheet.append(['Example Equity Fund - Direct Growth', 'Example AMC', 'FOLIO-1', 80000, 100000])
    path = tmp_path / 'core-cas.xlsx'
    workbook.save(path)

    as_of, holdings = parse_cas(path, scheme_master=master, scheme_master_source_bytes=source)
    assert as_of == '31-Oct-2026'
    assert len(holdings) == 1
    assert holdings[0]['scheme_identity_status'] == 'VERIFIED'
    assert holdings[0]['scheme_id'] == 'SCHEME-CORE-1'
    assert holdings[0]['constituent_weights'] is None


def test_active_core_cas_parser_does_not_resolve_without_verified_master(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Portfolio Details'
    sheet.append(['To Date', '31-Oct-2026'])
    sheet.append(['Scheme Name', 'AMC Name', 'Folio No.', 'Invested Value', 'Current Value'])
    sheet.append(['Example Equity Fund - Direct Growth', 'Example AMC', 'FOLIO-1', 80000, 100000])
    path = tmp_path / 'core-cas-unverified.xlsx'
    workbook.save(path)

    _, holdings = parse_cas(path)
    assert holdings[0]['scheme_identity_status'] == 'MISSING'
    assert holdings[0]['scheme_id'] is None
