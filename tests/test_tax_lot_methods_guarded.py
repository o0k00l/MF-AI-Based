from datetime import date
import pytest
from core.math_engine import TaxLot as EngineTaxLot, TaxClassificationDisabledError
from core.math.tax_lots import TaxLot as MathTaxLot


def test_engine_tax_lot_is_long_term_fails_closed():
    lot = EngineTaxLot()
    lot.purchase_date = date(2020, 1, 1)
    with pytest.raises(TaxClassificationDisabledError):
        lot.is_long_term(date(2026, 11, 4))


def test_engine_tax_lot_is_short_term_fails_closed():
    lot = EngineTaxLot()
    lot.purchase_date = date(2020, 1, 1)
    with pytest.raises(TaxClassificationDisabledError):
        lot.is_short_term(date(2026, 11, 4))


def test_math_tax_lot_is_long_term_fails_closed():
    lot = MathTaxLot()
    lot.purchase_date = date(2020, 1, 1)
    with pytest.raises(TaxClassificationDisabledError):
        lot.is_long_term(date(2026, 11, 4))


def test_math_tax_lot_is_short_term_fails_closed():
    lot = MathTaxLot()
    lot.purchase_date = date(2020, 1, 1)
    with pytest.raises(TaxClassificationDisabledError):
        lot.is_short_term(date(2026, 11, 4))
