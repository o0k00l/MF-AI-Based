# 1. Update core/eligibility.py
with open("core/eligibility.py", "r", encoding="utf-8") as f:
    text_el = f.read()

target_el = '''            "alpha_3y": float(m.get("alpha_3y", m.get("alpha", 0.0)) or 0.0),
            "return_1y": float(m.get("return_1y", m.get("ret_1y", 0.0)) or 0.0),'''

replacement_el = '''            "alpha_3y": float(m.get("alpha_3y", m.get("alpha", 0.0)) or 0.0),
            "international_equity_pct": float(m.get("international_equity_pct", 0.0) or 0.0),
            "cash_debt_buffer_pct": float(m.get("cash_debt_buffer_pct", 0.0) or 0.0),
            "return_1y": float(m.get("return_1y", m.get("ret_1y", 0.0)) or 0.0),'''

if target_el in text_el:
    text_el = text_el.replace(target_el, replacement_el)
    with open("core/eligibility.py", "w", encoding="utf-8") as f:
        f.write(text_el)
    print("core/eligibility.py updated LF")
elif target_el.replace("\n", "\r\n") in text_el:
    text_el = text_el.replace(target_el.replace("\n", "\r\n"), replacement_el.replace("\n", "\r\n"))
    with open("core/eligibility.py", "w", encoding="utf-8") as f:
        f.write(text_el)
    print("core/eligibility.py updated CRLF")
else:
    print("core/eligibility.py target not found")

# 2. Update core/math_engine.py
with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text_math = f.read()

target_math = '''    alpha_3y = float(c.get("alpha_3y", c.get("alpha", 0.0)) or 0.0)
    sharpe_3y = float(c.get("sharpe_3y", c.get("sharpe", 0.5)) or 0.5)
    sharpe_1y = float(c.get("sharpe_1y", 0.5) or 0.5)
    ret_1y = float(c.get("return_1y", c.get("ret_1y", 0.0)) or 0.0)
    ret_6m = float(c.get("return_6m", c.get("ret_6m", 0.0)) or 0.0)
    ter = float(c.get("er", c.get("ter_direct_pct", 0.75)) or 0.75)
    top10 = float(c.get("top10_concentration_pct", c.get("top10", 40.0)) or 40.0)
    conc_penalty = max(0.0, top10 - 40.0) * 0.15

    score = (alpha_3y * 8.0) + (sharpe_3y * 15.0) + (sharpe_1y * 10.0) + (ret_1y * 5.0) + (ret_6m * 3.0) - (ter * 25.0) - conc_penalty
    return round(score, 2)'''

replacement_math = '''    alpha_3y = float(c.get("alpha_3y", c.get("alpha", 0.0)) or 0.0)
    sharpe_3y = float(c.get("sharpe_3y", c.get("sharpe", 0.5)) or 0.5)
    sharpe_1y = float(c.get("sharpe_1y", 0.5) or 0.5)
    ret_1y = float(c.get("return_1y", c.get("ret_1y", 0.0)) or 0.0)
    ret_6m = float(c.get("return_6m", c.get("ret_6m", 0.0)) or 0.0)
    intl_pct = float(c.get("international_equity_pct", 0.0) or 0.0)
    cash_buf = float(c.get("cash_debt_buffer_pct", 0.0) or 0.0)
    ter = float(c.get("er", c.get("ter_direct_pct", 0.75)) or 0.75)
    top10 = float(c.get("top10_concentration_pct", c.get("top10", 40.0)) or 40.0)
    conc_penalty = max(0.0, top10 - 40.0) * 0.15

    score = (alpha_3y * 8.0) + (sharpe_3y * 15.0) + (sharpe_1y * 10.0) + (ret_1y * 5.0) + (ret_6m * 3.0) + (intl_pct * 2.5) + (cash_buf * 1.0) - (ter * 25.0) - conc_penalty
    return round(score, 2)'''

if target_math in text_math:
    text_math = text_math.replace(target_math, replacement_math)
    with open("core/math_engine.py", "w", encoding="utf-8") as f:
        f.write(text_math)
    print("core/math_engine.py updated LF")
elif target_math.replace("\n", "\r\n") in text_math:
    text_math = text_math.replace(target_math.replace("\n", "\r\n"), replacement_math.replace("\n", "\r\n"))
    with open("core/math_engine.py", "w", encoding="utf-8") as f:
        f.write(text_math)
    print("core/math_engine.py updated CRLF")
else:
    print("core/math_engine.py target not found")

