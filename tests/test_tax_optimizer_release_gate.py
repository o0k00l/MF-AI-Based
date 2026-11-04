import pytest

from tax.tax_optimizer import (
    TaxAdviceDisabledError,
    _determine_asset_class,
    optimize_capital_gains_set_off,
    specific_lot_designation,
    tax_drag_per_fund,
)


@pytest.mark.parametrize("entrypoint,args", [
    (tax_drag_per_fund, ([], {})),
    (optimize_capital_gains_set_off, ([], {})),
    (specific_lot_designation, ([],)),
    (_determine_asset_class, ("unknown",)),
])
def test_all_tax_optimizer_advice_entrypoints_fail_closed(entrypoint, args):
    with pytest.raises(TaxAdviceDisabledError, match="disabled pending independently approved"):
        entrypoint(*args)


def test_tax_optimizer_rejects_unknown_and_non_equity_categories_without_classification():
    for category in ("unknown", "gold", "international FoF", "debt"):
        with pytest.raises(TaxAdviceDisabledError):
            _determine_asset_class(category)


def test_all_direct_taxlot_maturity_classifiers_are_disabled():
    from datetime import date
    from core.math_engine import TaxLot as EngineTaxLot, TaxClassificationDisabledError
    from core.math.tax_lots import TaxLot as LegacyTaxLot

    engine_lot = EngineTaxLot(
        fund_id="fund-1", scheme_name="Scheme", folio="REDACTED",
        purchase_date=date(2024, 1, 1), units=1.0, nav=100.0, cost=100.0,
        source="synthetic",
    )
    legacy_lot = LegacyTaxLot(
        fund_id="fund-1", scheme_name="Scheme", folio="REDACTED",
        purchase_date=date(2024, 1, 1), units=1.0, nav=100.0, cost=100.0,
        source="synthetic",
    )
    for lot in (engine_lot, legacy_lot):
        with pytest.raises(TaxClassificationDisabledError, match="Direct tax-lot maturity classification is disabled"):
            lot.is_long_term(date(2026, 11, 4))
        with pytest.raises(TaxClassificationDisabledError, match="Direct tax-lot maturity classification is disabled"):
            lot.is_short_term(date(2026, 11, 4))
