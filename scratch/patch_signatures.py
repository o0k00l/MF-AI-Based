with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

old_lump = """    mid_choice: str = "motilal_midcap",
    large_choice: str = "nippon_large",
    flexi_choice: str = "ppfas_flexi",
) -> DeterministicLumpsumPlan:"""

new_lump = """) -> DeterministicLumpsumPlan:"""

old_sip = """    client_aum: float = 0.0,
    mid_choice: str = "motilal_midcap",
    large_choice: str = "nippon_large",
    flexi_choice: str = "ppfas_flexi",
) -> DeterministicSIPPlan:"""

new_sip = """    client_aum: float = 0.0,
) -> DeterministicSIPPlan:"""

assert old_lump in text, "old_lump not found"
assert old_sip in text, "old_sip not found"

text = text.replace(old_lump, new_lump, 1)
text = text.replace(old_sip, new_sip, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully cleaned up function signatures in core/math_engine.py")

