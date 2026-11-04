import pytest

from tax import tax_optimizer


@pytest.mark.parametrize(
    "entrypoint,args",
    [
        (tax_optimizer.tax_drag_per_fund, ([], {})),
        (tax_optimizer.optimize_capital_gains_set_off, ([], {})),
        (tax_optimizer.specific_lot_designation, ([],)),
        (tax_optimizer._determine_asset_class, ("unknown",)),
    ],
)
def test_every_tax_optimizer_entrypoint_uses_the_disabled_tax_advice_boundary(entrypoint, args):
    with pytest.raises(tax_optimizer.TaxAdviceDisabledError):
        entrypoint(*args)
