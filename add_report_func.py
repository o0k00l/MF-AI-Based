with open('core/prompt_advisor.py', 'r') as f:
    c = f.read()

# Find the last 'return _call_llm_with_retry(prompt)'
idx = c.rfind('return _call_llm_with_retry(prompt)')
if idx != -1:
    new_c = c[:idx+40] + '\n\ndef generate_fiduciary_report(payload: FiduciaryFactsPayload) -> str:\n    """Generates the comprehensive Fiduciary Fact Sheet report."""\n    return generate_health_audit_report(payload)\n'
    with open('core/prompt_advisor.py', 'w') as f:
        f.write(new_c)
    print('Added generate_fiduciary_report')
else:
    print('Not found')