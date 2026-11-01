import json
with open('data/lalit_portfolio/config.json') as f:
    c = json.load(f)
print(json.dumps(c, indent=2)[:3000])