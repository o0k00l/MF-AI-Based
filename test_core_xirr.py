from core.math_engine import calculate_portfolio_xirr, load_holdings_from_cas_excel
from pathlib import Path

holdings = load_holdings_from_cas_excel(Path("data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx"))
result = calculate_portfolio_xirr(Path("data/lalit_portfolio/transactions.json"), holdings)
print(f"Core XIRR: {result}")