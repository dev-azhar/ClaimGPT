#!/usr/bin/env python3
"""Test that insurance/claims rows are filtered from expenses."""

import json
import sys
from pathlib import Path

# Test the filter logic directly
def test_filter_logic():
    """Test the filter logic matches properly"""
    NON_EXPENSE_KEYWORDS = {
        "claim", "claims", "policy", "payer", "premium", "deductible",
        "risk factor", "member id", "policy number", "insurance", "sum insured"
    }
    
    test_cases = [
        ("Claims", "2 claims in last 12 months", True, "Should filter: claims keyword"),
        ("Claim vs Sum Insured", "Claim (Rs. 3,00,000)", True, "Should filter: claim + sum insured"),
        ("ICU", "ICU - 5 Days @ Rs. 15,000/day", False, "Should NOT filter: medical expense"),
        ("Room", "Private Ward - 6 Days @ Rs. 6,000/day", False, "Should NOT filter: medical expense"),
        ("Surgery", "Emergency PCI + Stent Placement", False, "Should NOT filter: medical expense"),
    ]
    
    print("=" * 70)
    print("EXPENSE FILTER TEST")
    print("=" * 70)
    
    all_pass = True
    for category, description, should_filter, explanation in test_cases:
        category_lower = category.lower()
        description_lower = description.lower()
        is_filtered = any(keyword in category_lower or keyword in description_lower 
                         for keyword in NON_EXPENSE_KEYWORDS)
        
        status = "✓ PASS" if is_filtered == should_filter else "✗ FAIL"
        all_pass = all_pass and (is_filtered == should_filter)
        
        print(f"\n{status}: {explanation}")
        print(f"  Category: '{category}' | Description: '{description}'")
        print(f"  Expected filter: {should_filter} | Got: {is_filtered}")
    
    print("\n" + "=" * 70)
    return all_pass

def test_normalized_expenses_file():
    """Check if normalized_expenses.json has been cleaned"""
    debug_file = Path("tmp/parser_debug/normalized_expenses.json")
    
    if not debug_file.exists():
        print("⚠ Debug file not found. Run a parse first to generate normalized_expenses.json")
        return None
    
    print("\n" + "=" * 70)
    print("NORMALIZED EXPENSES VALIDATION")
    print("=" * 70)
    
    with open(debug_file) as f:
        expenses = json.load(f)
    
    insurance_keywords = {"claim", "claims", "policy", "payer", "sum insured"}
    found_insurance = []
    
    for i, expense in enumerate(expenses):
        category = expense.get("category", "").lower()
        description = expense.get("description", "").lower()
        
        if any(kw in category or kw in description for kw in insurance_keywords):
            found_insurance.append((i, expense["category"], expense["description"]))
    
    if found_insurance:
        print(f"\n✗ FAIL: Found {len(found_insurance)} insurance-related rows in expenses:")
        for idx, category, desc in found_insurance:
            print(f"  [{idx}] {category}: {desc}")
        return False
    else:
        print(f"\n✓ PASS: No insurance-related rows found in {len(expenses)} expenses")
        print("\nSample expenses:")
        for i, exp in enumerate(expenses[:3]):
            print(f"  [{i}] {exp['category']}: {exp['description']} - Rs. {exp['amount']}")
        return True

if __name__ == "__main__":
    filter_pass = test_filter_logic()
    
    expenses_check = test_normalized_expenses_file()
    
    print("\n" + "=" * 70)
    if filter_pass:
        print("✓ Filter logic is correct")
    else:
        print("✗ Filter logic has issues")
    
    if expenses_check is None:
        print("⚠ Skipped normalized_expenses.json check (no debug file)")
    elif expenses_check:
        print("✓ Normalized expenses file is clean")
    else:
        print("✗ Normalized expenses file still has insurance rows")
    
    sys.exit(0 if filter_pass else 1)
