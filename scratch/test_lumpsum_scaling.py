import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.math_engine import compute_deterministic_sip_blueprint, calculate_cash_deployment

lumpsum_test_cases = [
    50000.0,
    200000.0,
    500000.0,
    1000000.0,
    2500000.0,
    5000000.0,
]

print("=== TESTING LUMPSUM DEPLOYMENT SCALING ===")
for L in lumpsum_test_cases:
    immediate_20 = round(L * 0.20, 2)
    stp_80 = round(L * 0.80, 2)
    stp_6mo = round(stp_80 / 6, 2)
    stp_9mo = round(stp_80 / 9, 2)
    stp_12mo = round(stp_80 / 12, 2)
    print(f"Lumpsum INR {L:,.0f}:")
    print(f"  - Immediate (20%): INR {immediate_20:,.0f}")
    print(f"  - STP 80%: INR {stp_80:,.0f}")
    print(f"    * 6-Mo STP: INR {stp_6mo:,.0f}/mo")
    print(f"    * 9-Mo STP: INR {stp_9mo:,.0f}/mo")
    print(f"    * 12-Mo STP: INR {stp_12mo:,.0f}/mo")
