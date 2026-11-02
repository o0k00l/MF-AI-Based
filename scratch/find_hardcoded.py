with open('core/math_engine.py', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        for term in ['hdfc', 'motilal', 'nippon', 'parag parikh', 'ppfas']:
            if f'"{term}"' in line.lower() or f"'{term}'" in line.lower():
                print(f"L{i}: {line.strip()[:100]}")

