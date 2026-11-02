with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """        for th in facts.thematic_exposures:
            thematic_summary.append(f"      - {th.theme_name}: Current look-through weight {th.look_through_weight_pct:.2f}% | Verdict: {th.fiduciary_verdict} ({th.recommendation_action})")"""

replacement = """        for th in facts.thematic_exposures:
            tot_th_pct = th.dedicated_funds_pct + th.look_through_stocks_pct
            thematic_summary.append(f"      - {th.theme_name}: Total exposure {tot_th_pct:.2f}% (Look-Through Stocks: {th.look_through_stocks_pct:.2f}%, Dedicated: {th.dedicated_funds_pct:.2f}%) | Status: {th.coverage_status}")"""

assert target in text, "Target not found"
text = text.replace(target, replacement, 1)

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully patched thematic_summary in prompt_advisor.py")

