new_content = open('core/math_engine.py', 'r', encoding='utf-8').read()

new_content += '''

def _fifo_redeem(lots: List[TaxLot], units_to_remove: float) -> List[TaxLot]:
    """Remove units from lot pool using FIFO method."""
    remaining = units_to_remove
    new_lots = []
    for lot in lots:
        if remaining <= 0:
            new_lots.append(lot)
            continue
        if lot.units <= remaining:
            remaining -= lot.units
        else:
            remaining_units = lot.units - remaining
            redeemed_units = remaining
            redeemed_lot = TaxLot(
                fund_id=lot.fund_id,
                scheme_name=lot.scheme_name,
                folio=lot.folio,
                purchase_date=lot.purchase_date,
                units=redeemed_units,
                nav=lot.nav,
                cost=lot.cost * (redeemed_units / lot.units),
                source=lot.source
            )
            remaining_lot = TaxLot(
                fund_id=lot.fund_id,
                scheme_name=lot.scheme_name,
                folio=lot.folio,
                purchase_date=lot.purchase_date,
                units=remaining_units,
                nav=lot.nav,
                cost=lot.cost * (remaining_units / lot.units),
                source=lot.source
            )
            new_lots.append(remaining_lot)
            remaining = 0
    return new_lots

def _match_scheme_to_fund(scheme: str) -> Optional[str]:
    """Match a scheme name to a fund_id using fuzzy matching."""
    if not scheme:
        return None
    scheme_lower = scheme.lower()
    for fund_id, metric in fund_metrics.items():
        if metric.get('id', '').lower() in scheme_lower:
            return fund_id
        if metric.get('name', '').lower() in scheme_lower:
            return fund_id
    normalized = re.sub(r'[^a-z0-9]+', '_', scheme_lower).strip('_')
    return normalized if normalized else None

def build_fifo_tax_lots(
    transactions_path: Path,
    holdings: Any,
    as_of_date: Optional[date] = None,
    cas_current: Optional[float] = None
) -> Dict[str, List[TaxLot]]:
    if not transactions_path.exists():
        return {}
    if as_of_date is None:
        as_of_date = date.today()
    try:
        with open(transactions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {}
    transactions = data.get('transactions', [])
    if not transactions:
        return {}
    fund_lots: Dict[str, List[TaxLot]] = {}
    fund_holdings: Dict[str, float] = {}
    for txn in data.get('transactions', []):
        try:
            txn_date = datetime.strptime(txn.get('date', '')[:10], '%Y-%m-%d').date()
            amount = float(txn.get('amount', 0))
            txn_type = txn.get('type', '').upper()
            scheme = txn.get('scheme', '')
            units = float(txn.get('units', 0)) if txn.get('units') else 0
            nav = float(txn.get('nav', 0)) if txn.get('nav') else 0
            if amount == 0 or units == 0:
                continue
            fund_id = _match_scheme_to_fund(scheme)
            if not fund_id:
                continue
            if fund_id not in fund_lots:
                fund_lots[fund_id] = []
            if fund_id not in fund_holdings:
                fund_holdings[fund_id] = 0.0
            if txn_type in ('PURCHASE', 'SIP', 'SWITCH_IN', 'STP_IN', 'DIVIDEND_REINVEST'):
                units_to_add = units if units > 0 else (abs(amount) / nav) if nav > 0 else 0
                if units_to_add > 0:
                    cost = units_to_add * nav if nav > 0 else 0
                    lot = TaxLot(
                        fund_id=fund_id,
                        scheme_name=scheme,
                        folio=txn.get('folio', ''),
                        purchase_date=txn_date,
                        units=units_to_add,
                        nav=nav,
                        cost=cost,
                        source='transactions'
                    )
                    fund_lots[fund_id].append(lot)
                    fund_holdings[fund_id] += units_to_add
            elif txn_type in ('REDEMPTION', 'SWITCH_OUT', 'STP_OUT'):
                units_to_remove = units if units > 0 else (abs(amount) / nav) if nav > 0 else 0
                if units_to_remove > 0:
                    fund_lots[fund_id] = _fifo_redeem(fund_lots[fund_id], units_to_remove)
                    fund_holdings[fund_id] -= units_to_remove
            elif txn_type in ('DIVIDEND',):
                pass
            elif txn_type in ('SWITCH_IN', 'SWITCH_OUT'):
                pass
        except Exception:
            continue
    for fund_id in fund_lots:
        fund_lots[fund_id].sort(key=lambda x: x.purchase_date)
    return fund_lots
'''

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Part 2 done')