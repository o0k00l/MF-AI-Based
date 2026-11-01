with open('docs/OPTION_B_ROADMAP.md', 'r', encoding='utf-8') as f:
    content = f.read()

corrections_header = """## ⚠️ **ARCHITECTURAL REVISION - 2024-11-01**

### **REVISED ROADMAP BASED ON INSTITUTIONAL CRITIQUE**

#### **ROADMAP CORRECTIONS**

1. **Sprint Reordering:** AI reporting moved to LAST (Sprint 5)
   - Financial mathematics and execution safety FIRST
   - AI explanation layer LAST

2. **12-Engine Sprawl → 6-Module Architecture**
   - Data & Reconciliation
   - Portfolio Diagnostics  
   - Investor Suitability
   - Investment Selection
   - Execution & Tax Safeguards
   - Decision & Explainability

3. **Mathematical Corrections:**
   - Weighted look-through overlap (not Jaccard only)
   - SAA Drift Minimizer (not optimizer)
   - Risk distribution reporting (ordinal, not cardinal)
   - NO ACTION decision branch mandatory

4. **Removed Flawed Assumptions:**
   - ❌ Zero-friction switches
   - ❌ Dogmatic multi-cap exits
   - ❌ Cardinal risk scores
   - ❌ Manufactured conviction scoring

---

"""

if '## ✅ **IMPLEMENTATION COMPLETE' not in content:
    content = corrections_header + content

with open('docs/OPTION_B_ROADMAP.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("OPTION_B_ROADMAP.md updated")
