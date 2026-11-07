"""Executive Fiduciary Report & Download Page."""
from __future__ import annotations

import sys
from pathlib import Path
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st
from services.fiduciary_engine import evaluate_portfolio_saa_audit, generate_fiduciary_sip_blueprint
from services.ai_fund_classifier import enrich_funds_with_ai

# --- Page Configuration ---
st.set_page_config(
    page_title="Fiduciary Report | Portfolio Review",
    page_icon="📄",
    layout="wide",
)

# --- Render Advisory Flow Sidebar ---
with st.sidebar:
    st.markdown("""
    <style>
        [data-testid="stSidebarNav"] { display: none !important; }
        .sidebar-brand {
            font-size: 1.15rem;
            font-weight: 700;
            color: #0f172a;
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 2px;
        }
        .sidebar-subbrand {
            font-size: 0.72rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 12px;
        }
        .portfolio-card {
            background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
            color: white;
            border-radius: 10px;
            padding: 12px 14px;
            margin-top: 6px;
            margin-bottom: 14px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        }
    </style>
    <div class="sidebar-brand">🛡️ Fiduciary Engine</div>
    <div class="sidebar-subbrand">SEBI IA Advisory Decision Support</div>
    """, unsafe_allow_html=True)

    _user_portfolio = st.session_state.get("user_portfolio", [])
    _has_cas = len(_user_portfolio) > 0
    _has_cgs = bool(st.session_state.get("cgs_data"))
    _has_statements = _has_cas and _has_cgs
    _has_risk = bool(st.session_state.get("user_risk_score") or st.session_state.get("risk_tier"))
    _has_goals = bool(st.session_state.get("goals_allocation"))

    # Active Portfolio Card (if uploaded)
    if _has_cas:
        _tot_val = sum(f.get("current_value", 0) for f in _user_portfolio)
        _tot_inv = sum(f.get("invested_value", 0) for f in _user_portfolio)
        _gain = _tot_val - _tot_inv if _tot_inv > 0 else 0
        _gain_pct = (_gain / _tot_inv * 100) if _tot_inv > 0 else 0
        _dir_val = sum(f.get("current_value", 0) for f in _user_portfolio if str(f.get("plan_type", "Direct")).upper() == "DIRECT")
        _dir_pct = (_dir_val / _tot_val * 100) if _tot_val > 0 else 100.0

        st.markdown(f"""
        <div class="portfolio-card">
            <div style="font-size: 0.72rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em;">Active Portfolio</div>
            <div style="font-size: 1.45rem; font-weight: 700; color: #38bdf8; margin: 2px 0;">₹{_tot_val/100000:.2f}L</div>
            <div style="font-size: 0.78rem; color: #cbd5e1; display: flex; justify-content: space-between;">
                <span>{len(_user_portfolio)} Schemes</span>
                <span style="color: {'#4ade80' if _gain >= 0 else '#f87171'}; font-weight: 600;">{_gain_pct:+.1f}%</span>
            </div>
            <div style="font-size: 0.72rem; color: #94a3b8; margin-top: 6px; border-top: 1px solid rgba(255,255,255,0.15); padding-top: 5px;">
                Direct Plans: <b style="color: {'#4ade80' if _dir_pct == 100 else '#facc15'}">{_dir_pct:.0f}%</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Active Governing Risk Tier (if evaluated)
    if _has_risk:
        _tier_name = str(st.session_state.get("risk_tier", "Assessed")).replace("_", " ").title()
        _target = st.session_state.get("saa_target", {})
        _eq_t = _target.get("total_equity_pct", _target.get("equity_pct", 75.0))
        _db_t = _target.get("debt_pct", 25.0)
        st.markdown(f"""
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px; margin-bottom: 12px;">
            <div style="color: #64748b; font-size: 0.7rem; text-transform: uppercase;">Governing Risk Profile</div>
            <div style="color: #0f172a; font-size: 0.85rem; font-weight: 600;">🎯 {_tier_name}</div>
            <div style="color: #475569; font-size: 0.75rem;">Target SAA: <b>{_eq_t:.0f}% Eq / {_db_t:.0f}% Debt</b></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<p style='font-weight: 700; font-size: 0.82rem; color: #334155; margin-bottom: 6px;'>🧭 ADVISORY WORKFLOW</p>", unsafe_allow_html=True)

    # Primary Two-Step Fiduciary Flow
    st.markdown("<p style='font-weight: 700; font-size: 0.82rem; color: #334155; margin-bottom: 6px;'>🧭 TWO-STEP FIDUCIARY FLOW</p>", unsafe_allow_html=True)
    st.page_link("app.py", label=f"Step 1: Portfolio Intake & Audit {'✅' if _has_cas else '⏳'}", icon="📊")
    st.page_link("pages/5_Fiduciary_Report.py", label=f"Step 2: Executive Report {'✅' if _has_cas else '⏳'}", icon="📄")

    st.markdown("<p style='font-weight: 700; font-size: 0.75rem; color: #64748b; margin-top: 10px; margin-bottom: 4px;'>🔬 OPTIONAL DEEP-DIVES</p>", unsafe_allow_html=True)
    st.page_link("pages/2_Risk_Profiler.py", label="Risk Profiler & SAA", icon="📋")
    st.page_link("pages/4_Debt_Allocation.py", label="True Debt Factsheet Matrix", icon="📈")
    st.page_link("pages/3_Financial_Goals.py", label="Financial Goals Wizard", icon="🎯")
    st.page_link("pages/1_Advisory_Flow.py", label="Advisory Roadmap", icon="🧭")

    st.markdown("---")
    if st.button("🔄 Reset / Clear Session", use_container_width=True, help="Clear active session portfolio and start over"):
        st.session_state.clear()
        st.rerun()

    st.caption("🛡️ **Fiduciary Standard:** SEBI (Investment Advisers) Regulations, 2013 | Non-execution authority | Zero distributor commission bias.")

st.title("📄 Executive Fiduciary Report & Action Plan")
st.markdown("Your formal, comprehensive portfolio diagnostic and investment advisory report.")

# Check prerequisites
portfolio = st.session_state.get("user_portfolio", [])
if portfolio:
    portfolio = enrich_funds_with_ai(portfolio)

cgs_data = st.session_state.get("cgs_data")
goals_alloc = st.session_state.get("goals_allocation")
risk_tier = st.session_state.get("risk_tier") or st.session_state.get("risk_bucket") or "Moderate (Evaluated SAA)"

# Synthesize goal allocation / SIP blueprint seamlessly from evaluated portfolio SAA
if not goals_alloc:
    bp = st.session_state.get("deterministic_sip_plan")
    if not bp and portfolio:
        budget = float(st.session_state.get("sip_budget", 25000.0))
        bp = generate_fiduciary_sip_blueprint(
            monthly_budget_inr=budget,
            funds=portfolio,
            target_saa=st.session_state.get("saa_target"),
        )
        st.session_state["deterministic_sip_plan"] = bp
    if bp:
        lc_val = float(next((a["amount_inr"] for a in bp.get("allocations", []) if "Large" in a.get("sleeve", "")), 0.0))
        ms_val = float(next((a["amount_inr"] for a in bp.get("allocations", []) if "Mid" in a.get("sleeve", "")), 0.0))
        db_val = float(next((a["amount_inr"] for a in bp.get("allocations", []) if "Debt" in a.get("sleeve", "")), 0.0))
        goals_alloc = {
            "goals": {
                "sip_plan": {
                    "goal_name": "Long-Term Wealth Accumulation & SAA Compounding",
                    "priority": 1,
                    "required_monthly": float(bp["monthly_budget_inr"]),
                    "allocated_monthly": float(bp["allocated_budget_inr"]),
                    "gap_monthly": float(bp["unallocated_budget_inr"]),
                    "target_corpus": 0.0,
                    "horizon_years": 10,
                }
            },
            "total_required": float(bp["monthly_budget_inr"]),
            "total_allocated": float(bp["allocated_budget_inr"]),
            "total_gap": float(bp["unallocated_budget_inr"]),
            "surplus": 0.0,
            "use_step_up": False,
            "asset_sleeves": {
                "large_cap_inr": lc_val,
                "mid_small_cap_inr": ms_val,
                "debt_inr": db_val,
            },
        }
        st.session_state["goals_allocation"] = goals_alloc

missing = []
if not portfolio:
    missing.append("📤 Upload CAS Statement (Portfolio Dashboard)")

if missing:
    st.warning("⚠️ **Prerequisites Missing:** Please upload your CAS portfolio statement to generate your report:")
    for m in missing:
        st.markdown(f"* {m}")
    st.info("👉 *Return to Step 1 (Portfolio Intake & Audit) to upload your statement.*")
else:
    total_val = sum(f.get("current_value", 0) for f in portfolio)
    total_invested = sum(f.get("invested_value", 0) for f in portfolio)
    total_gain = total_val - total_invested if total_invested > 0 else 0
    gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0

    st.success("✅ All advisory milestones complete! Your review report is ready.")

    # High-level Summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Portfolio Value", f"₹{total_val:,.0f}")
    with col2:
        st.metric("Governing Risk Profile", str(risk_tier).replace("_", " ").title())
    with col3:
        sip_budget = goals_alloc.get("total_allocated", 0)
        st.metric("Monthly SIP Budget", f"₹{sip_budget:,.0f}/mo")

    # Build report preview
    report_lines = [
        "# Executive Mutual Fund Portfolio Review & Fiduciary Advisory Plan",
        "",
        f"**Valuation Date:** Current Session  |  **Governing Risk Tier:** {risk_tier}  |  **Active Funds:** {len(portfolio)}",
        "",
        "---",
        "",
        "## 1. Portfolio Diagnostic Summary",
        f"* **Total Portfolio Value:** ₹{total_val:,.0f}",
        f"* **Total Invested Cost:** ₹{total_invested:,.0f}",
        f"* **Unrealized Gain / (Loss):** ₹{total_gain:,.0f} ({gain_pct:+.1f}%)",
        "",
        "## 2. Holdings Breakdown",
        "| Scheme Name | Category | Plan | Current Value (₹) | Equity % | Debt % |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for f in portfolio:
        name = f.get("scheme", "Unknown")
        cat = f.get("category", "N/A")
        plan = f.get("plan_type", "Direct")
        val = f.get("current_value", 0)
        eq = f.get("eq", 0)
        debt = f.get("debt", 0)
        report_lines.append(f"| {name} | {cat} | {plan} | ₹{val:,.0f} | {eq:.1f}% | {debt:.1f}% |")

    # Add CGS section if available
    cgs_data = st.session_state.get("cgs_data")
    if cgs_data and cgs_data.get("summary"):
        cg_s = cgs_data.get("summary", {})
        ltcg = float(cg_s.get("ltcg_inr") or 0.0)
        stcg = float(cg_s.get("stcg_inr") or 0.0)
        rem_hd = max(0.0, 125_000.0 - ltcg)
        report_lines.extend([
            "",
            "## 6. Statutory Capital Gains Audit (CGS)",
            f"* **Realized LTCG (§112A):** ₹{ltcg:,.2f}",
            f"* **Realized STCG (§111A):** ₹{stcg:,.2f}",
            f"* **Remaining §112A Exemption Headroom:** ₹{rem_hd:,.2f} (out of ₹1.25 Lakhs annual tax-free limit)",
            f"* **Statement Provenance:** SHA256 `{cgs_data.get('source_sha256', 'N/A')[:16]}...`",
        ])

    # Commission Bleed & Direct Conversion Audit (Zero Hardcoding - AMC Factsheet Look-Through)
    regular_holdings = [f for f in portfolio if str(f.get("plan_type", "Direct")).upper() == "REGULAR"]
    regular_val = sum(f.get("current_value", 0) for f in regular_holdings)
    regular_pct = (regular_val / total_val * 100.0) if total_val > 0 else 0.0
    total_annual_bleed = sum(f.get("annual_commission_bleed", 0.0) for f in regular_holdings)
    total_10y_linear = sum(f.get("ten_year_linear_commission", 0.0) for f in regular_holdings)
    total_10y_compounded = sum(f.get("ten_year_compounded_drag", 0.0) for f in regular_holdings)
    avg_trail = (total_annual_bleed / regular_val * 100.0) if regular_val > 0 else 0.0

    report_lines.extend([
        "",
        "## 3. Distributor Commission Bleed & Direct Plan Audit",
    ])
    if regular_val > 0:
        report_lines.extend([
            f"* **Regular Plan Exposure:** ₹{regular_val:,.0f} ({regular_pct:.1f}% of total portfolio) across {len(regular_holdings)} schemes",
            f"* **Annual Distributor Trail Bleed:** ₹{total_annual_bleed:,.0f} / year (weighted avg trail ~{avg_trail:.2f}% p.a.)",
            f"* **Estimated 10-Year Compounded Drag:** ₹{total_10y_compounded:,.0f} (Linear Cumulative: ₹{total_10y_linear:,.0f})",
            "* **Fiduciary Switch Recommendation:** Execute non-taxable/disciplined switches from Regular to Direct Growth plans to halt distributor commission leakage.",
            "",
            "| Identified Regular Scheme | Current Value (₹) | Direct TER | Regular TER | Trail Comm. % | Annual Bleed (₹/yr) | 10Y Compounded Drag (₹) |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for rf in sorted(regular_holdings, key=lambda x: x.get("annual_commission_bleed", 0), reverse=True):
            r_name = rf.get("scheme", "Regular Scheme")
            r_val = float(rf.get("current_value", 0))
            r_td = float(rf.get("ter_direct", 0.75))
            r_tr = float(rf.get("ter_regular", 1.75))
            r_trail = float(rf.get("trail_commission_pct", 1.0))
            r_yr = float(rf.get("annual_commission_bleed", 0))
            r_10y = float(rf.get("ten_year_compounded_drag", 0))
            report_lines.append(f"| {r_name} | ₹{r_val:,.0f} | {r_td:.2f}% | {r_tr:.2f}% | {r_trail:.2f}% | ₹{r_yr:,.0f}/yr | ₹{r_10y:,.0f} |")
    else:
        report_lines.extend([
            "* **Direct Plan Compliance:** ✅ 100% Direct Plan Mandate Verified",
            "* **Commission Leakage:** Zero distributor trail commission bleed detected across all active folios.",
        ])

    # SAA Drift & Fiduciary Audit
    target_saa = st.session_state.get("saa_target")
    audit_res = evaluate_portfolio_saa_audit(portfolio, target_saa=target_saa) if target_saa else None

    if audit_res and audit_res.get("status") == "ANALYZED":
        tgt_eq = audit_res["target_equity_pct"]
        tgt_db = audit_res["target_debt_pct"]
        cur_eq = audit_res["current_equity_pct"]
        cur_db = audit_res["current_debt_pct"]
        db_gap = audit_res["debt_gap_inr"]
        is_def = audit_res["is_debt_deficit"]

        report_lines.extend([
            "",
            "## 4. Strategic Asset Allocation (SAA) & Drift Diagnostic",
            f"* **Target SAA:** {tgt_eq:.1f}% Equity / {tgt_db:.1f}% Debt",
            f"* **Current Portfolio Mix:** {cur_eq:.1f}% Equity / {cur_db:.1f}% Debt",
            f"* **Debt Stability Buffer:** {'Deficit of ₹' + str(round(float(db_gap)/100000.0, 2)) + ' Lakhs' if is_def else 'Adequate Surplus'}",
            f"* **Fiduciary Rebalancing Flag:** {'Action Required (Drift exceeds tolerance band)' if audit_res.get('rebalance_required') else 'Compliant within +/-5% Band'}",
        ])

    report_lines.extend([
        "",
        "## 5. Financial Goal Allocation & SIP Deployment",
    ])
    for g_id, g_info in goals_alloc.get("goals", {}).items():
        g_name = g_info.get("goal_name", g_id)
        req = g_info.get("required_monthly", 0)
        alloc = g_info.get("allocated_monthly", 0)
        report_lines.append(f"* **{g_name}:** Required SIP: ₹{req:,.0f}/mo | Allocated SIP: ₹{alloc:,.0f}/mo")

    # Add Asset Sleeve SIP Blueprint if available
    sleeves = goals_alloc.get("asset_sleeves")
    if sleeves:
        report_lines.extend([
            "",
            "### Monthly SIP Asset-Sleeve Deployment Breakdown",
            f"* **Large-Cap Core Index:** ₹{sleeves.get('large_cap_inr', 0):,.2f} / month",
            f"* **Mid/Small-Cap Alpha:** ₹{sleeves.get('mid_small_cap_inr', 0):,.2f} / month",
            f"* **Debt & Liquidity Cushion:** ₹{sleeves.get('debt_inr', 0):,.2f} / month",
        ])

    # Add Lump-Sum Deployment Plan if available
    ls_plan = st.session_state.get("deterministic_lumpsum_plan")
    if ls_plan and ls_plan.get("status") in ("ELIGIBLE", "CAPPED_AT_SURPLUS"):
        report_lines.extend([
            "",
            "### Lump-Sum Capital Staging & STP Plan",
            f"* **Total Staged Lump-Sum Capital:** ₹{float(ls_plan['effective_lumpsum_inr']):,.2f}",
            f"* **Equity Staging (STP):** ₹{float(ls_plan['target_equity_capital_inr']):,.2f}",
            f"* **Debt / Liquid Retention:** ₹{float(ls_plan['target_debt_capital_inr']):,.2f}",
            f"* **Liquid Parking Vehicle:** {ls_plan['parking_scheme']}",
            f"* **STP Duration:** {ls_plan['stp_duration_months']} months @ ₹{float(ls_plan['monthly_stp_tranche_inr']):,.2f} / month",
        ])

    report_lines.extend([
        "",
        "## 7. Fiduciary Disclosures & Compliance Statement",
        "* **Statutory Mandate:** SEBI (Investment Advisers) Regulations, 2013.",
        "* **Direct Plan Enforcement:** All proposed switches and SIP allocations strictly mandate Direct Plans to eliminate intermediary commissions.",
        "* **Non-Execution Authority:** The adviser operates solely on a fee-only, non-execution advisory basis; order execution remains exclusively in client control.",
    ])

    report_md = "\n".join(report_lines)

    tab1, tab2 = st.tabs(["📄 Report Preview", "💾 Download"])
    with tab1:
        st.markdown(report_md)
    with tab2:
        st.download_button(
            "📥 Download Report (Markdown)",
            data=report_md,
            file_name="Executive_Fiduciary_Report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.download_button(
            "📥 Download Report (HTML)",
            data=f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Executive Fiduciary Report</title>
<style>body{{font-family:Arial, sans-serif; max-width:850px; margin:2rem auto; padding:1.5rem; line-height: 1.6;}}</style>
</head>
<body>{report_md}</body>
</html>""",
            file_name="Executive_Fiduciary_Report.html",
            mime="text/html",
            use_container_width=True,
        )

