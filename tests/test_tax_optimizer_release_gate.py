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
