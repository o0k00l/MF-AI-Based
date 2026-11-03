import pathlib

p = pathlib.Path('core/fund_classifier.py')
t = p.read_text()

# Add warnings to heuristic checks
t = t.replace(
    'if fund_data.get("is_passive") is True:\n        return True',
    'if fund_data.get("is_passive") is True:\n        import warnings\n        warnings.warn("Passive verification via metadata flag - scheme master not used. Gate 4 release gate requires scheme_master.")\n        return True'
)

t = t.replace(
    'if any(cat_lower == sc or cat_lower.startswith("index: ") or cat_lower.startswith("etf: ") for sc in sebi_passive_categories):\n        return True',
    'if any(cat_lower == sc or cat_lower.startswith("index: ") or cat_lower.startswith("etf: ") for sc in sebi_passive_categories):\n        import warnings\n        warnings.warn("Passive verification via SEBI category heuristic - scheme master not used. Gate 4 release gate requires scheme_master.")\n        return True'
)

t = t.replace(
    'if any(token in name_lower for token in passive_name_tokens):\n        return True',
    'if any(token in name_lower for token in passive_name_tokens):\n        import warnings\n        warnings.warn("Passive verification via name heuristic - scheme master not used. Gate 4 release gate requires scheme_master.")\n        return True'
)

p.write_text(t)
print("Done - passive verification warnings added")