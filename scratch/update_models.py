with open("core/models.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """class DeterministicSIPPlan(BaseModel):
    total_monthly_budget_inr: float
    equity_sip_pct: float = 100.0
    debt_sip_pct: float = 0.0
    items: List[DeterministicSIPRecommendation] = Field(default_factory=list)"""

replacement = """class DeterministicSIPPlan(BaseModel):
    total_monthly_budget_inr: float
    equity_sip_pct: float = 100.0
    debt_sip_pct: float = 0.0
    items: List[DeterministicSIPRecommendation] = Field(default_factory=list)


class LumpsumTrancheItem(BaseModel):
    role: str
    scheme_name: str
    folio_target: Optional[str] = None
    amount_inr: float
    monthly_inr: Optional[float] = None
    allocation_pct: float
    timing: str
    source_vehicle: str
    fiduciary_rationale: str


class DeterministicLumpsumPlan(BaseModel):
    total_lumpsum_inr: float
    is_big_ticket: bool
    stp_duration_months: int
    immediate_amount_inr: float
    stp_total_amount_inr: float
    monthly_stp_total_inr: float
    parking_vehicle: str
    tax_savings_vs_debt_fund_inr: float = 0.0
    cash_validation_passed: bool = True
    cash_validation_message: str = ""
    tranches: List[LumpsumTrancheItem] = Field(default_factory=list)"""

if target in content:
    content = content.replace(target, replacement, 1)
    
    # Also add deterministic_lumpsum_plan to FiduciaryFactsPayload
    target_payload = "    deterministic_sip_plan: Optional[DeterministicSIPPlan] = None"
    replacement_payload = """    deterministic_sip_plan: Optional[DeterministicSIPPlan] = None
    deterministic_lumpsum_plan: Optional[DeterministicLumpsumPlan] = None"""
    content = content.replace(target_payload, replacement_payload, 1)

    with open("core/models.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: Updated core/models.py")
else:
    print("ERROR: Target not found in core/models.py")

