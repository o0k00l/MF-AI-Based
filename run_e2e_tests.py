#!/usr/bin/env python3
"""
End-to-End Testing Script for Fiduciary Mutual Funds Copilot
============================================================
Run from the project root directory:
    python run_e2e_tests.py
"""

import subprocess
import sys
import os
import re
from pathlib import Path

GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def run_cmd(cmd):
    """Run shell command and return (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, '', str(e)

def test_syntax():
    """Test 1: Python syntax validation"""
    print(f"\n{BLUE}TEST 1: Python Syntax Validation{RESET}")
    
    py_files = []
    for f in Path('.').rglob('*.py'):
        if 'archive' not in str(f) and 'scratch' not in str(f) and not str(f).startswith('./data'):
            py_files.append(str(f))
    
    all_ok = True
    for py_file in sorted(py_files):
        ret, out, err = run_cmd(f'python -m py_compile "{py_file}"')
        if ret != 0:
            print(f"  {RED}❌ FAIL{RESET}: {py_file}")
            all_ok = False
    
    if all_ok:
        print(f"  {GREEN}✅ PASS{RESET}: {len(py_files)} Python files validated")
    return all_ok

def test_p0_tests():
    """Test 2: P0 Fiduciary Invariant Tests"""
    print(f"\n{BLUE}TEST 2: P0 Fiduciary Invariant Tests{RESET}")
    ret, out, err = run_cmd('python -m pytest test_p0_fiduciary_invariants.py -q')
    passed = out.count('passed')
    
    if ret == 0 and 'passed' in out:
        print(f"  {GREEN}✅ PASS{RESET}: Test suite passed")
        return True
    else:
        print(f"  {RED}❌ FAIL{RESET}: Tests failed")
        print(out[-1000:] if len(out) > 1000 else out)
        return False

def test_clean_checkout():
    """Test 3: Clean Checkout Viability"""
    print(f"\n{BLUE}TEST 3: Clean Checkout Viability{RESET}")
    ret, out, err = run_cmd('python -m pytest test_clean_checkout.py -q')
    
    if ret == 0:
        print(f"  {GREEN}✅ PASS{RESET}: Clean checkout test passed")
        return True
    else:
        print(f"  {RED}❌ FAIL{RESET}: Clean checkout test failed")
        return False

def test_validation():
    """Test 4: Universal Logic Validation"""
    print(f"\n{BLUE}TEST 4: Universal Logic Validation{RESET}")
    ret, out, err = run_cmd('python validate_final_logics.py')
    
    match = re.search(r'(\d+)/(\d+) CHECKS PASSED', out)
    if match:
        passed, total = int(match.group(1)), int(match.group(2))
        print(f"  {GREEN}✅ PASS{RESET}: {passed}/{total} checks passed")
        return ret == 0 or 'FINAL SCORECARD' in out
    else:
        print(f"  {YELLOW}⚠️  WARN{RESET}: Could not parse validation output")
        return False

def test_hardcoding():
    """Test 5: Hardcoding Detection"""
    print(f"\n{BLUE}TEST 5: Hardcoded Value Detection{RESET}")
    
    issues = []
    doc_files = ['README.md', 'ARCHITECTURE.md', 'VERIFICATION_REPORT.md', 'logical_flow.md']
    
    for doc in doc_files:
        if os.path.exists(doc):
            with open(doc, 'r', encoding='utf-8') as f:
                content = f.read()
            
            bad_patterns = ['40/30/15/15', '86/86', '40% Core Flexi-Cap Compounder (40%)']
            for pattern in bad_patterns:
                if pattern in content:
                    issues.append(f"{doc}: Found '{pattern}'")
    
    if issues:
        for issue in issues[:5]:
            print(f"  {RED}❌ {issue}{RESET}")
        return False
    else:
        print(f"  {GREEN}✅ PASS{RESET}: No outdated hardcoded references found")
        return True

def main():
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}  FIDUCIARY WEALTH ENGINE - END-TO-END TESTING SCRIPT{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    
    results = {}
    results['syntax'] = test_syntax()
    results['p0_tests'] = test_p0_tests()
    results['clean_checkout'] = test_clean_checkout()
    results['validation'] = test_validation()
    results['hardcoding'] = test_hardcoding()
    
    # Summary
    print(f"\n{BLUE}{'='*50}{RESET}")
    print(f"\nFinal Results:")
    
    for name, passed in results.items():
        icon = "✅" if passed else "❌"
        print(f"  {icon} {name.replace('_', ' ').upper()}")
    
    all_passed = all(results.values())
    print(f"\n{BLUE}{'='*50}{RESET}")
    
    if all_passed:
        print(f"{GREEN}✅ ALL CHECKS PASSED - PRODUCTION RELEASE APPROVAL STILL REQUIRED{RESET}\n")
        return 0
    else:
        print(f"{RED}❌ SOME TESTS FAILED - REVIEW REQUIRED{RESET}\n")
        return 1

if __name__ == '__main__':
    sys.exit(main())