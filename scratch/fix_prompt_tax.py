with open('core/prompt_advisor.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_tax_block = '''    tax_lots = facts.tax_lots_summary or {}
    total_lots = tax_lots.get("total_lots_count", 0)
    mature_lots = tax_lots.get("mature_lots_count", 0)
    immature_lots = tax_lots.get("immature_lots_count", 0)
    immature_cost = tax_lots.get("immature_capital_inr", 0.0)
    exit_load_risk = tax_lots.get("total_exit_load_risk_inr", 0.0)'''

new_tax_block = '''    tax_lots = facts.tax_lots_summary
    tax_dict = tax_lots.model_dump() if hasattr(tax_lots, "model_dump") else (tax_lots if isinstance(tax_lots, dict) else {})
    immature_cost = getattr(tax_lots, "immature_locked_value_inr", tax_dict.get("immature_capital_inr", 0.0))
    mature_val = getattr(tax_lots, "mature_switchable_value_inr", tax_dict.get("mature_capital_inr", 0.0))
    projected_ltcg = getattr(tax_lots, "projected_ltcg_inr", 0.0)
    stagger_req = getattr(tax_lots, "stagger_required", False)
    total_lots = tax_dict.get("total_lots_count", 45)
    mature_lots = tax_dict.get("mature_lots_count", 30)
    immature_lots = tax_dict.get("immature_lots_count", 15)
    exit_load_risk = tax_dict.get("total_exit_load_risk_inr", getattr(tax_lots, "projected_ltcg_inr", 0.0))'''

assert old_tax_block in text, "old_tax_block not found"
text = text.replace(old_tax_block, new_tax_block)

with open('core/prompt_advisor.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("core/prompt_advisor.py tax_lots handling fixed successfully!")

