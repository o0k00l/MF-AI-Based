with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_tier6 = """    if tier_num == 6:
        base_eq, base_debt, threshold = 95.0, 5.0, 5.0"""

new_tier6 = """    if tier_num == 6:
        if stability_buffer_pct is not None and stability_buffer_pct < 5.0:
            return 95.0, 5.0
        return 100.0, 0.0"""

assert old_tier6 in content, "old_tier6 not found"
content = content.replace(old_tier6, new_tier6, 1)

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Updated Tier 6 default in calculate_universal_tier_split")

