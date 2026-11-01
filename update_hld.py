with open('docs/OPTION_B_HLD_LLD.md', 'r', encoding='utf-8') as f:
    content = f.read()

corrections_header = """## ⚠️ **ARCHITECTURAL CORRECTIONS - 2024-11-01**

### **6-MODULE ARCHITECTURE IMPLEMENTED**

Replacing 12-engine sprawl with clean 6-module architecture.

**The 6-Module Architecture:**

1. **DATA & RECONCILIATION** - Ingestion, mapping, reconciliation
2. **PORTFOLIO DIAGNOSTICS** - Fee bleed, XIRR, alpha, overlap
3. **INVESTOR SUITABILITY** - Goals, horizon, risk capacity
4. **INVESTMENT SELECTION** - Eligibility gates, scoring
5. **EXECUTION & TAX SAFEGUARDS** - FIFO, exit loads, tax harvesting
6. **DECISION & EXPLAINABILITY** - AI reporting layer

### **MATHEMATICAL CORRECTIONS**

**Overlap Calculation:**
- ❌ OLD: Jaccard similarity only
- ✅ NEW: Weighted look-through concentration

**Risk Scoring:**
- ❌ OLD: Cardinal 5.84/6.00
- ✅ NEW: Ordinal distribution + metrics

**SAA Drift:**
- ❌ OLD: Called "optimizer"
- ✅ NEW: "Drift Minimizer" (accurate description)

**Switch Costs:**
- ❌ OLD: Zero-friction claim
- ✅ NEW: Actual tax + exit load calculation

**Multi-Cap Funds:**
- ❌ OLD: Dogmatic exit
- ✅ NEW: Evaluate on actual merits

**Eligibility:**
- ✅ NEW: Mandatory binary gates before scoring

**NO ACTION:**
- ✅ NEW: Mandatory decision branch

---

"""

if '## ✅ **ARCHITECTURAL OVERHAUL' not in content:
    content = corrections_header + content

with open('docs/OPTION_B_HLD_LLD.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("OPTION_B_HLD_LLD.md updated")
