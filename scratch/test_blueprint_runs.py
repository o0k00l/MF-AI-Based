import sys
sys.path.insert(0, ".")
from pathlib import Path
from core.math_engine import load_holdings_from_cas_excel, select_autonomous_blueprint_funds

cas_path = Path("data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx")
holdings = load_holdings_from_cas_excel(cas_path)

slots = select_autonomous_blueprint_funds(holdings=holdings, client_risk_tier=6, thematic_deficit_theme="Pharma & Healthcare")
print("=== DYNAMIC BLUEPRINT FUNDS ===")
for role, item in slots.items():
    print(f"\n{role}:")
    print(f"  Scheme: {item['scheme']}")
    print(f"  Folio: {item['folio']}")
    print(f"  Score: {item['score']}")
    print(f"  Gate Passed: {item['gate_passed']}")
    print(f"  Rationale: {item['rationale'][:100]}...")

