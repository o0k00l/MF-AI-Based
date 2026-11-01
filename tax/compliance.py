"""
Tax compliance module - loads policy from data/policy/
"""
import json
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parent.parent / "data" / "policy"

def load_policy(policy_dir: str = None) -> dict:
    """Load tax policy from JSON file."""
    if policy_dir is None:
        policy_dir = POLICY_DIR
    else:
        policy_dir = Path(policy_dir)
    tax_file = policy_dir / "tax_rules.json"
    if tax_file.exists():
        return json.loads(tax_file.read_text(encoding="utf-8"))
    return {}

def load_all_policies(policy_dir: str = None) -> dict:
    """Load all policy files."""
    if policy_dir is None:
        policy_dir = POLICY_DIR
    else:
        policy_dir = Path(policy_dir)
    policies = {}
    for f in policy_dir.glob("*.json"):
        policies[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return policies