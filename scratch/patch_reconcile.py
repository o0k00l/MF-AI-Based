with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# Define the reconcile function right before calculate_portfolio_xirr
target_pos = "def calculate_portfolio_xirr("

recon_func = '''def reconcile_cas_holdings_with_transactions(
    holdings: List[HoldingItem],
    transactions_path: Path
) -> Dict[str, Any]:
    """
    Cross-reconciles CAS statement holdings against cumulative transaction history units.
    Flags any unrecorded corporate actions, external transfers, or unit discrepancies.
    """
    if not transactions_path.exists():
        return {
            "status": "NO_TRANSACTION_FILE",
            "reconciled_schemes": 0,
            "total_schemes": len(holdings),
            "discrepancies": []
        }

    try:
        with open(transactions_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        txs = data.get("transactions", [])
    except Exception as e:
        return {
            "status": f"READ_ERROR: {e}",
            "reconciled_schemes": 0,
            "total_schemes": len(holdings),
            "discrepancies": []
        }

    net_units_by_scheme: Dict[str, float] = {}
    for tx in txs:
        s_norm = tx.get("scheme", "").strip().lower()
        u = float(tx.get("units", 0.0) or 0.0)
        t_type = tx.get("type", "PURCHASE").upper()
        if t_type in ("PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST"):
            net_units_by_scheme[s_norm] = net_units_by_scheme.get(s_norm, 0.0) + u
        elif t_type in ("REDEMPTION", "SWITCH_OUT", "STP_OUT"):
            net_units_by_scheme[s_norm] = net_units_by_scheme.get(s_norm, 0.0) - u

    discrepancies = []
    reconciled_count = 0
    for h in holdings:
        h_norm = h.scheme.strip().lower()
        cas_u = round(float(h.units), 3)
        matched_tx_u = None
        for s_key, t_u in net_units_by_scheme.items():
            if s_key == h_norm or (len(s_key) > 10 and (s_key in h_norm or h_norm in s_key)):
                matched_tx_u = round(t_u, 3)
                break

        if matched_tx_u is not None:
            diff = abs(cas_u - matched_tx_u)
            if diff <= 0.05:
                reconciled_count += 1
            else:
                discrepancies.append({
                    "scheme": h.scheme,
                    "cas_units": cas_u,
                    "transaction_units": matched_tx_u,
                    "difference": round(cas_u - matched_tx_u, 3)
                })
        else:
            discrepancies.append({
                "scheme": h.scheme,
                "cas_units": cas_u,
                "transaction_units": 0.0,
                "difference": cas_u
            })

    status = "VERIFIED_RECONCILED" if not discrepancies else "PARTIALLY_RECONCILED"
    return {
        "status": status,
        "reconciled_schemes": reconciled_count,
        "total_schemes": len(holdings),
        "discrepancies": discrepancies
    }


def calculate_portfolio_xirr('''

assert target_pos in text, "target_pos not found"
text = text.replace(target_pos, recon_func, 1)

# Now call it in aggregate_fiduciary_facts
target_call = """    portfolio_xirr = calculate_portfolio_xirr(transactions_path, holdings)
    tax_lots_raw = compute_fifo_tax_lots(transactions_path)"""

replacement_call = """    portfolio_xirr = calculate_portfolio_xirr(transactions_path, holdings)
    tax_lots_raw = compute_fifo_tax_lots(transactions_path)
    cas_recon = reconcile_cas_holdings_with_transactions(holdings, transactions_path)"""

assert target_call in text, "target_call not found"
text = text.replace(target_call, replacement_call, 1)

# And add to FiduciaryFactsPayload instantiation
target_payload = """        deterministic_sip_plan=det_sip_plan,
        deterministic_lumpsum_plan=det_lumpsum_plan,
    )"""

replacement_payload = """        deterministic_sip_plan=det_sip_plan,
        deterministic_lumpsum_plan=det_lumpsum_plan,
        cas_reconciliation=cas_recon,
    )"""

assert target_payload in text, "target_payload not found"
text = text.replace(target_payload, replacement_payload, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully added CAS vs Transactions Reconciliation to core/math_engine.py")

