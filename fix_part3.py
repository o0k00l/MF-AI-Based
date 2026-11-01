new_content = open('core/math_engine.py', 'r', encoding='utf-8').read()

new_content += '''

def compute_fifo_tax_lots(
    transactions_path: Path,
    holdings: Any,
    as_of_date: Optional[date] = None
) -> Dict[str, TaxLotSummary]:
    if as_of_date is None:
        as_of_date = date.today()
    fund_lots = build_fifo_tax_lots(transactions_path, [], as_of_date)
    summaries: Dict[str, TaxLotSummary] = {}
    for fund_id, lots in fund_lots.items():
        if not lots:
            continue
        scheme_name = lots[0].scheme_name if lots else ""
        current_value_est = sum(l.nav * l.units for l in lots) if lots else 0
        total_cost = sum(l.cost for l in lots)
        ltcg_units = 0.0
        ltcg_gain = 0.0
        stcg_units = 0.0
        stcg_gain = 0.0
        total_units = 0.0
        for lot in lots:
            is_ltcg = lot.is_long_term(as_of_date)
            gain = (lot.nav - lot.cost / lot.units) * lot.units if lot.units > 0 else 0
            if is_ltcg:
                ltcg_units += lot.units
                ltcg_gain += gain
            else:
                stcg_units += lot.units
                stcg_gain += gain
            total_units += lot.units
        unrealized_gain = current_value_est - total_cost
        ltcg_taxable = max(0, ltcg_gain - 125000.0)
        ltcg_tax = ltcg_taxable * 0.13
        stcg_tax = stcg_gain * 0.208
        summaries[fund_id] = TaxLotSummary(
            fund_id=fund_id,
            scheme_name=scheme_name,
            total_units=total_units,
            total_cost=total_cost,
            current_value=current_value_est,
            unrealized_gain=unrealized_gain,
            ltcg_units=ltcg_units,
            ltcg_gain=ltcg_gain,
            stcg_units=stcg_units,
            stcg_gain=stcg_gain,
            ltcg_tax=ltcg_tax,
            stcg_tax=stcg_tax,
            ltcg_exemption_used=min(ltcg_gain, 125000.0),
            stcg_exemption_used=0.0
        )
    return summaries

def stage_redemptions_for_tax_optimization(
    tax_summaries: Dict[str, TaxLotSummary],
    annual_ltcg_exemption: float = 125000.0,
    max_years: int = 5
) -> List[Dict[str, Any]]:
    ltcg_lots = []
    for fund_id, summary in tax_summaries.items():
        if summary.ltcg_gain > 0:
            ltcg_lots.append({
                'fund_id': fund_id,
                'scheme_name': summary.scheme_name,
                'ltcg_gain': summary.ltcg_gain,
                'ltcg_units': summary.ltcg_units,
                'ltcg_tax_if_sold_now': summary.ltcg_tax,
                'tax_savings_if_staged': summary.ltcg_tax
            })
    ltcg_lots.sort(key=lambda x: x['ltcg_tax_if_sold_now'], reverse=True)
    staged_plan = []
    remaining_exemption = annual_ltcg_exemption
    fy_start = date.today().year
    for lot in ltcg_lots:
        if remaining_exemption <= 0:
            break
        sheltered = min(lot['ltcg_gain'], remaining_exemption)
        tax_saved = sheltered * 0.13
        staged_plan.append({
            'fy': f'FY{fy_start}-{fy_start+1}',
            'fund_id': lot['fund_id'],
            'scheme_name': lot['scheme_name'],
            'ltcg_gain': lot['ltcg_gain'],
            'gain_sheltered': sheltered,
            'tax_saved': tax_saved,
            'remaining_exemption': remaining_exemption - sheltered
        })
        remaining_exemption -= sheltered
        if remaining_exemption <= 0:
            fy_start += 1
            remaining_exemption = annual_ltcg_exemption
    return staged_plan
'''

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Part 3 done')