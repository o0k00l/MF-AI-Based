with open('README.md', 'r', encoding='utf-8') as f:
    content = f.read()

old_gates = """[Step 1: 10 Binary Fiduciary Gates]
  • Gate 1: Single-AMC Exposure < 30% of Net Worth
  • Gate 2: AUM Bounds (Mid-Cap <= ₹40k Cr, Flexi <= ₹90k Cr)
  • Gate 3: Top-10 Concentration <= 55%
  • Gate 4: Risk-Adjusted Sharpe Ratio >= 0.40
  • Gate 5: Downside Capture Ratio <= 100%
  • Gate 6: Upside Capture Ratio >= 90%
  • Gate 7: Riskometer Score Alignment with Client Risk Tier
  • Gate 8: Data Completeness & Manager Tenure >= 3 Years
  • Gate 9: Thematic Satellite Cap <= 15% (0% for Starters < ₹5L)
  • Gate 10: 100% Direct Plan Mandate (Zero Regular Plans)
       │
       ├─ Active Funds Pass ──► [Step 2: Multi-Horizon Quantitative Composite Scoring]
       │                        Score = (3Y Alpha x 8) + (3Y Sharpe x 15) + (1Y Sharpe x 10)
       │                              + (1Y Return x 5) + (6M Return x 3) - (Direct TER x 25) - Conc Penalty
       │                        • Rigorously incorporates 1-year near-term momentum & 6-month cycle trend
       │                          alongside 3-year compounding consistency and direct TER fee discipline."""

new_gates = """[Step 1: 10 Binary Fiduciary Gates]
  • Gate 1: Single-AMC Exposure < 30% of Net Worth
  • Gate 2: AUM Bounds (Mid-Cap <= ₹40k Cr; Flexi <= ₹175k Cr with >=65% Large-Cap/Cash bluechip liquidity, else ₹90k Cr)
  • Gate 3: Top-10 Concentration <= 55% (Debt & Dedicated Thematic funds exempted from equity sector cap)
  • Gate 4: Risk-Adjusted Sharpe Ratio >= 0.40 (Index & Debt funds adjusted)
  • Gate 5: Downside Capture Ratio <= 100%
  • Gate 6: Upside Capture Ratio >= 90%
  • Gate 7: Riskometer Score Alignment with Client Risk Tier
  • Gate 8: Data Completeness & Manager Tenure >= 3 Years
  • Gate 9: Thematic Satellite Cap <= 15% (0% for Starters < ₹5L)
  • Gate 10: 100% Direct Plan Mandate (Zero Regular Plans)
       │
       ├─ Active Funds Pass ──► [Step 2: Multi-Horizon Quantitative Composite Scoring]
       │                        Score = (3Y Alpha x 8) + (3Y Sharpe x 15) + (1Y Sharpe x 10)
       │                              + (1Y Return x 5) + (6M Return x 3) + (Intl% x 2.5) + (CashBuf% x 1.0)
       │                              - (Direct TER x 25) - Conc Penalty
       │                        • Rigorously incorporates 1-year near-term momentum & 6-month cycle trend
       │                          alongside 3-year compounding consistency, international tech ballast, and direct TER fee discipline."""

assert old_gates in content, "old_gates not found"
content = content.replace(old_gates, new_gates, 1)

old_tests = """### 4. Run Test & Validation Suites
```bash
# 1. P0 Fiduciary Invariants Suite (5/5 PASS)
python test_p0_fiduciary_invariants.py

# 2. Universal Fiduciary Logic Validation Suite (83/83 PASS - 100% SUCCESS)
python validate_final_logics.py
```"""

new_tests = """### 4. Run Test & Validation Suites
```bash
# 1. P0 Fiduciary Invariants Suite (6/6 PASS)
python -m pytest

# 2. Universal Fiduciary Logic Validation Suite (83/83 PASS - 100% SUCCESS)
python validate_final_logics.py
```"""

assert old_tests in content, "old_tests not found"
content = content.replace(old_tests, new_tests, 1)

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Updated README.md")

