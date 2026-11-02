with open('core/prompt_advisor.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Remove hardcoded XIRR / Alpha fallbacks
old_fallbacks = '''    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "15.82%"
    benchmark_val = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "12.00%"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "+3.82%"'''

new_fallbacks = '''    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "N/A"
    benchmark_val = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "12.00%"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "N/A"'''

assert old_fallbacks in text, "old_fallbacks not found in prompt_advisor.py"
text = text.replace(old_fallbacks, new_fallbacks)

# 2. Fix generate_cash_and_sip_plan prompt text
old_sip_prompt_text = '''Explain the role of each engine:
- Parag Parikh Flexi Cap: Low 0.69% TER, international tech exposure, and built-in ~12% organic cash/arbitrage buffer.
- Mid-Cap Alpha Engine: Proven 10-year multi-bagger wealth creation driver.
- Nippon India Large Cap: Consolidates active Direct Folio #401321771817; steady alpha leader (+1.99% 3Y alpha).
- Nippon India Pharma / Healthcare: Forward-looking tactical satellite solving the 1.1% healthcare void at reasonable (~28x P/E) valuations.'''

new_sip_prompt_text = '''Explain the fiduciary role of each engine in the verified table:
{engine_bullets}'''

assert old_sip_prompt_text in text, "old_sip_prompt_text not found in prompt_advisor.py"
text = text.replace(old_sip_prompt_text, new_sip_prompt_text)

# Also insert engine_bullets generation before prompt
old_bullets_marker = '    sip_rows = []\n    if getattr(facts, "deterministic_sip_plan", None):'
new_bullets_code = '''    sip_rows = []
    engine_bullets = ""
    if getattr(facts, "deterministic_sip_plan", None):
        engine_bullets = "\\n".join([f"- **{it.scheme_name}:** {it.fiduciary_rationale}" for it in facts.deterministic_sip_plan.items])'''

assert old_bullets_marker in text, "old_bullets_marker not found in prompt_advisor.py"
text = text.replace(old_bullets_marker, new_bullets_code)

with open('core/prompt_advisor.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("core/prompt_advisor.py hardcoding removed successfully")

