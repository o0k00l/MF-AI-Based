with open('core/eligibility.py', 'r', encoding='utf-8') as f:
    text = f.read()

new_code = '''

def validate_thematic_satellite_cap(
    sip_plan: Any,
    client_aum: float,
    max_satellite_pct: float = 15.0
) -> bool:
    """
    Enforces Gate 9: Thematic Satellite Cap.
    - If client AUM < INR 5,00,000 (Starter), satellite thematic must be 0%.
    - If client AUM >= INR 5,00,000, satellite thematic must not exceed 15%.
    """
    if not hasattr(sip_plan, "items"):
        return True

    thematic_alloc = sum(
        item.allocation_pct for item in sip_plan.items
        if getattr(item, "rational_code", "") == "SATELLITE_THEME"
    )

    if client_aum < 500000.0 and thematic_alloc > 0.0:
        raise ValueError(f"Fiduciary Gate 9 Violation: Starter portfolios (< INR 5L AUM) cannot hold thematic funds (found {thematic_alloc}%).")

    if thematic_alloc > max_satellite_pct:
        raise ValueError(f"Fiduciary Gate 9 Violation: Thematic satellite allocation {thematic_alloc}% exceeds max allowed {max_satellite_pct}%.")

    return True


def validate_direct_sip_mandate(sip_plan: Any) -> bool:
    """
    Enforces Gate 10: 100% Direct Plan Mandate on Fresh SIPs.
    Any recommended SIP item containing Regular or distributor commission throws an immediate violation.
    """
    if not hasattr(sip_plan, "items"):
        return True

    for item in sip_plan.items:
        scheme = getattr(item, "scheme_name", "").lower()
        if "regular" in scheme:
            raise ValueError(f"Fiduciary Gate 10 Violation: Fresh SIP recommendation '{item.scheme_name}' contains Regular plan.")

    return True
'''

if "validate_thematic_satellite_cap" not in text:
    with open('core/eligibility.py', 'a', encoding='utf-8') as f:
        f.write(new_code)
    print("Updated core/eligibility.py successfully")
else:
    print("Already in core/eligibility.py")

