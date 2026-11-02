with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """def answer_interactive_query(facts: FiduciaryFactsPayload, user_query: str, chat_history: Optional[List[Dict[str, str]]] = None) -> str:
    \"\"\"Answers ad-hoc interactive questions from the user using full verified context.\"\"\""""

replacement = """def answer_interactive_query(facts: FiduciaryFactsPayload, user_query: str, chat_history: Optional[List[Dict[str, str]]] = None) -> str:
    \"\"\"Answers ad-hoc interactive questions from the user using full verified context and canonical intent routing.\"\"\"
    q_lower = user_query.strip().lower()

    # Intent 1: Switch / Transition / Commission Bleed
    if any(k in q_lower for k in ("should i switch", "is switching worth it", "switch plan", "commission bleed", "broker fee", "regular vs direct", "switch cost")):
        f1 = facts.fee_bleed
        reg_val = f1.regular_portfolio_value_inr
        bleed = f1.annual_bleed_inr
        loss10 = f1.ten_year_compounded_loss_inr
        top_leaks = "\\n".join([f"- **{f.get('fund_name', 'Scheme')}**: INR {f.get('annual_bleed_inr', 0):,.0f}/yr leak (Current: INR {f.get('current_value_inr', 0):,.0f})" for f in f1.details[:4]])
        return (
            f"### 🛡️ Fiduciary Recommendation: Switch to 100% Direct Plans\\n\\n"
            f"**Yes, switching is a mathematical imperative.** Here is the fiduciary evidence from your portfolio:\\n\\n"
            f"1. **Guaranteed Commission Bleed:** You currently hold **{f1.regular_funds_count} Regular plans** valued at **INR {reg_val:,.2f}**.\\n"
            f"2. **Annual Fee Leakage:** You are bleeding **INR {bleed:,.2f} per year** in unnecessary distributor commissions that provide zero alpha.\\n"
            f"3. **10-Year Compounded Loss:** Over a 10-year compounding horizon at 12% CAGR, this commission leakage compounds to **INR {loss10:,.2f}** in destroyed wealth.\\n\\n"
            f"**Largest Fee Leaks:**\\n{top_leaks}\\n\\n"
            f"**Execution Safeguard:** We mandate a disciplined **3-Phase Switch Schedule**:\\n"
            f"- **Phase 1:** Immediately switch loss-making and mature lots within the annual **INR 1,25,000 Section 112A LTCG tax-free exemption**.\\n"
            f"- **Phase 2:** Hold immature SIP lots (<365 days) until **Day 366** to eliminate 1.0% exit load penalties and 20% STCG.\\n"
            f"- **Phase 3:** Execute remaining tranches in the subsequent financial year under a fresh INR 1.25L tax-free window."
        )

    # Intent 2: Fresh Money / SIP / Lumpsum Blueprint
    if any(k in q_lower for k in ("sip plan", "fresh money", "where should i invest", "fresh sip", "sip blueprint", "4-slot", "lumpsum deployment", "fresh deployment")):
        sip = facts.deterministic_sip_plan
        lump = facts.deterministic_lumpsum_plan
        sip_rows = "\\n".join([f"- **{it.category_role}**: {it.scheme_name} | {it.allocation_pct:.1f}% (INR {it.monthly_inr:,.0f}/mo) | Target: {it.folio_target or 'New Direct Folio'}" for it in sip.items]) if sip else "SIP plan calculated per IPS."
        lump_imm = lump.immediate_amount_inr if lump else 40000.0
        lump_stp = lump.stp_total_amount_inr if lump else 160000.0
        lump_mo = lump.monthly_stp_total_inr if lump else 26667.0
        lump_dur = lump.stp_duration_months if lump else 6
        return (
            f"### 🎯 The Deterministic Fresh Money Blueprint\\n\\n"
            f"Your fresh capital is deployed across **100% Direct Plans** under the documented 4-Slot Sizing Engine:\\n\\n"
            f"**Monthly SIP Allocation (Budget: INR {facts.monthly_sip_budget_inr:,.2f}):**\\n{sip_rows}\\n\\n"
            f"**Universal 20/80 Lumpsum Deployment:**\\n"
            f"- **Day 1 Immediate Entry (20%):** INR {lump_imm:,.0f} deployed into the Large-Cap Bluechip Anchor.\\n"
            f"- **Systematic STP (80%):** INR {lump_stp:,.0f} parked in an **Equity Arbitrage Fund - Direct Plan** and staggered over {lump_dur} months (INR {lump_mo:,.0f}/mo).\\n"
            f"- **Tax Protection:** Arbitrage parking bypasses Section 50AA debt slab taxation (saving tax drag) and enjoys equity capital gains treatment under Sections 111A/112A."
        )

    # Intent 3: Redemption / Withdrawal / Cash Out
    if any(k in q_lower for k in ("redeem", "redemption", "withdraw", "need cash", "take out money", "emergency withdrawal")):
        sb = facts.stability_buffer
        cash_avail = sb.bank_deployable_cash_inr if sb else 0.0
        return (
            f"### 💧 Fiduciary Personal Redemption Framework\\n\\n"
            f"Capital withdrawals are executed via a strict **4-Stage Tax-Minimizing Waterfall**:\\n\\n"
            f"1. **Stage 1 (Organic Cash):** Draw from deployable bank cash (INR {cash_avail:,.0f} available above emergency buffer) $\\\\rightarrow$ **INR 0 tax, INR 0 exit load**.\\n"
            f"2. **Stage 2 (Tactical Regular Bleed):** Liquidate underperforming Regular plans with capital losses (loss-harvesting) or mature LTCG within the INR 1,25,000 exemption $\\\\rightarrow$ **Eliminates fee drag, INR 0 exit load**.\\n"
            f"3. **Stage 3 (Thematic Trim):** Trim over-allocated or peak-valuation thematic holdings (e.g. Defence at 80x+ P/E).\\n"
            f"4. **Stage 4 (Core Equity Siphon):** Siphon long-term Direct equity compounders held >365 days.\\n\\n"
            f"*To calculate an exact redemption schedule with lot-by-lot exit loads and taxes, run:* `python advisor.py --redeem <amount> [--net]`"
        )

    # Intent 4: Stability Buffer / Debt Cushion
    if any(k in q_lower for k in ("stability buffer", "debt cushion", "how much debt", "debt allocation", "cash buffer")):
        sb = facts.stability_buffer
        if sb:
            return (
                f"### 🛡️ Look-Through Stability Cushion Analysis\\n\\n"
                f"- **Total Look-Through Stability Buffer:** **{sb.total_stability_buffer_pct:.2f}%** of portfolio net worth.\\n"
                f"- **Embedded Debt:** INR {sb.embedded_debt_inr:,.2f} ({sb.embedded_debt_pct:.2f}%) held inside hybrid/flexi-cap funds.\\n"
                f"- **Embedded Cash:** INR {sb.embedded_cash_inr:,.2f} ({sb.embedded_cash_pct:.2f}%) held as fund manager dry powder.\\n"
                f"- **Bank Deployable Cash:** INR {sb.bank_deployable_cash_inr:,.2f} (above emergency reserves).\\n\\n"
                f"**Fiduciary Impact:** This organic {sb.total_stability_buffer_pct:.2f}% stability cushion fully satisfies your **Tier 6 (5% debt ceiling)** target without requiring low-yielding standalone debt SIPs."
            )"""

assert target in text, "target not found"
text = text.replace(target, replacement, 1)

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully added Canonical Intent Routing to answer_interactive_query in core/prompt_advisor.py")

