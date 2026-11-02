# 1. Update core/models.py to add client_age, horizon_years, risk_tier_name to FiduciaryFactsPayload
with open('core/models.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_ffp = '''class FiduciaryFactsPayload(BaseModel):
    client_name: str'''

new_ffp = '''class FiduciaryFactsPayload(BaseModel):
    client_name: str
    client_age: Optional[int] = 35
    horizon_years: Optional[int] = 10
    risk_tier_name: str = "Tier 6 (Very High)"'''

assert old_ffp in text, "old_ffp not found in models.py"
text = text.replace(old_ffp, new_ffp)

with open('core/models.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated core/models.py")

# 2. Update core/math_engine.py to populate these fields from config.json
with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_load_cfg = '''            client_name = cfg.get("client_name") or cfg.get("ips", {}).get("client_name") or "Valued Client"
            monthly_sip = float(cfg.get("ips", {}).get("monthly_sip_budget", 100000.0))'''

new_load_cfg = '''            client_name = cfg.get("client_name") or cfg.get("ips", {}).get("client_name") or "Valued Client"
            client_age_val = int(cfg.get("ips", {}).get("client_age", 35))
            horizon_yrs_val = int(cfg.get("ips", {}).get("horizon_years", 10))
            client_risk_tier = cfg.get("risk_tier") or cfg.get("ips", {}).get("risk_tolerance", "Tier 6 (Very High)")
            monthly_sip = float(cfg.get("ips", {}).get("monthly_sip_budget", 100000.0))'''

assert old_load_cfg in text, "old_load_cfg not found in math_engine.py"
text = text.replace(old_load_cfg, new_load_cfg)

old_ret_call = '''    return FiduciaryFactsPayload(
        client_name=client_name,'''

new_ret_call = '''    return FiduciaryFactsPayload(
        client_name=client_name,
        client_age=client_age_val,
        horizon_years=horizon_yrs_val,
        risk_tier_name=client_risk_tier,'''

assert old_ret_call in text, "old_ret_call not found in math_engine.py"
text = text.replace(old_ret_call, new_ret_call)

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated core/math_engine.py")

# 3. Update core/prompt_advisor.py to use dynamic client age and horizon
with open('core/prompt_advisor.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_p_text = '''1. Executive Deployment Strategy:
   - Provide a disciplined fiduciary roadmap explaining why 100% of fresh SIP money is deployed into high-alpha Direct equity engines for a 35-year-old Tier 6 investor with a 10-year horizon.
   - Explain why standalone debt SIPs are omitted: the portfolio already holds {facts.stability_buffer.total_stability_buffer_pct if facts.stability_buffer else 7.54}% in embedded look-through debt & cash + bank cash.'''

new_p_text = '''1. Executive Deployment Strategy:
   - Provide a disciplined fiduciary roadmap explaining why 100% of fresh SIP money is deployed into high-alpha Direct equity engines for a {facts.client_age or 35}-year-old {facts.risk_tier_name} investor with a {facts.horizon_years or 10}-year horizon.
   - Explain why standalone debt SIPs are omitted: the portfolio already holds {facts.stability_buffer.total_stability_buffer_pct if facts.stability_buffer else 0.0:.2f}% in embedded look-through debt & cash + bank cash.'''

assert old_p_text in text, "old_p_text not found in prompt_advisor.py"
text = text.replace(old_p_text, new_p_text)

with open('core/prompt_advisor.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated core/prompt_advisor.py")

