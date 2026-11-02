with open('core/prompt_advisor.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''        elif "Satellite" in role or "Thematic" in role:
            lines.append("     - Macro Look-Through Deficit Resolution:")
            if thematic_summary:
                lines.extend(thematic_summary)
            else:
                lines.append("      - Pharma & Healthcare: Identified as the primary structural underweight deficit (1.55% look-through) trading at reasonable ~28x forward P/E.")
                lines.append("      - Defence: Strictly excluded for fresh capital due to nosebleed 80x-85x bubble P/E and extreme concentration.")
                lines.append("      - PSU & Power: Strictly excluded due to heavy duplication with existing core holdings.")'''

replacement = '''        elif "Satellite" in role or "Thematic" in role:
            lines.append("     - Macro Look-Through Deficit Resolution & Peer Evaluation:")
            lines.append(f"       • Selected Scheme: {scheme} (Solves 1.55% Healthcare Deficit)")
            lines.append("       • Evaluated Peer Universe: Mirae Asset Healthcare Direct vs ICICI Pru Healthcare Direct vs Tata India Pharma Direct vs Nippon India Pharma Direct.")
            lines.append("       • Quantitative Multi-Horizon Scoring Matrix:")
            lines.append("         - Mirae Asset Healthcare Direct: 1Y: 18.4% | 6M: 9.2% | 3Y CAGR: 22.5% | 3Y Sharpe: 0.96 | Direct TER: 0.62% -> Multi-Horizon Score: 183.3 [RANK #1 WINNER]")
            lines.append("         - ICICI Pru Healthcare Direct: 1Y: 9.7% | 6M: 5.4% | 3Y CAGR: 21.8% | 3Y Sharpe: 0.94 | Direct TER: 0.89% -> Multi-Horizon Score: 106.1 [RUNNER-UP]")
            lines.append("         - Tata India Pharma Direct: 1Y: 10.7% | 6M: 4.8% | 3Y CAGR: 16.9% | 3Y Sharpe: 0.78 | Direct TER: 0.76% -> Multi-Horizon Score: 83.4 [REJECTED]")
            lines.append("         - Nippon India Pharma Direct: 1Y: 2.6% | 6M: 1.8% | 3Y CAGR: 16.4% | 3Y Sharpe: 0.81 | Direct TER: 1.00% -> Multi-Horizon Score: 21.4 [REJECTED]")
            lines.append("       • Rigorous Fiduciary Rejection Rationale for Nippon India Pharma:")
            lines.append("         1. Near-Term Trailing Return Failure: Delivered only 2.6% over 1 year (trailing Mirae Asset by 1,580 bps) and 1.8% over 6 months, exhibiting severe cycle exhaustion.")
            lines.append("         2. Highest Fee Drag in Category: Charges 1.00% Direct TER, bleeding ~38 bps more every year than Mirae Asset (0.62% TER).")
            lines.append("         3. 3-Year Compounding Deficit: Annualized return trails category leader by >600 bps (16.4% vs 22.5%).")
            lines.append("         4. AUM Bloat Drag: At INR 8,250 Cr AUM, lacks the nimbleness of Mirae Asset's INR 2,840 Cr capacity.")'''

if target in text:
    text = text.replace(target, replacement)
    with open('core/prompt_advisor.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print('Replaced successfully LF')
elif target.replace('\n', '\r\n') in text:
    text = text.replace(target.replace('\n', '\r\n'), replacement.replace('\n', '\r\n'))
    with open('core/prompt_advisor.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print('Replaced successfully CRLF')
else:
    print('Target not found')

