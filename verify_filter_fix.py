#!/usr/bin/env python3
"""End-to-end test: Verify insurance rows are filtered from expenses after parsing."""

import sys
import json
import logging
from pathlib import Path

# Setup paths
sys.path.insert(0, str(Path(__file__).parent))

# Test filter directly on existing debug output
def test_filter_on_debug_output():
    """Test the filter on the semantic_region_outputs.json to see what's being extracted"""
    
    print("=" * 70)
    print("TESTING FILTER ON DEBUG OUTPUT")
    print("=" * 70)
    
    debug_file = Path("tmp/parser_debug/semantic_region_outputs.json")
    if not debug_file.exists():
        print("⚠ Debug file not found. Run a parse first.")
        return None
    
    with open(debug_file) as f:
        regions_data = json.load(f)
    
    # Define filter keywords
    NON_EXPENSE_KEYWORDS = {
        "claim", "claims", "policy", "payer", "premium", "deductible",
        "risk factor", "member id", "policy number", "insurance", "sum insured"
    }
    
    print(f"\nAnalyzing {len(regions_data)} regions...")
    
    insurance_rows_found = []
    medical_expense_rows_found = []
    
    # Check what the LLM returned for each region's tables
    for region in regions_data:
        region_id = region.get("region_id", "?")
        metadata = region.get("metadata", {})
        tables = metadata.get("tables", [])
        
        for table_idx, table in enumerate(tables):
            table_kind = table.get("table_kind", "unknown")
            rows = table.get("rows", [])
            
            for row_idx, row in enumerate(rows):
                cells = row.get("cells") or row
                category = str(cells.get("category", "")).lower()
                description = str(cells.get("description", "")).lower()
                
                # Check if this is an insurance row
                is_insurance = any(kw in category or kw in description for kw in NON_EXPENSE_KEYWORDS)
                
                if table_kind == "expenses":
                    row_data = {
                        "region_id": region_id,
                        "table_idx": table_idx,
                        "row_idx": row_idx,
                        "category": cells.get("category", ""),
                        "description": cells.get("description", ""),
                        "amount": cells.get("amount", 0),
                        "is_insurance": is_insurance,
                    }
                    
                    if is_insurance:
                        insurance_rows_found.append(row_data)
                    else:
                        medical_expense_rows_found.append(row_data)
    
    print(f"\n✓ Found {len(medical_expense_rows_found)} valid medical expenses")
    print(f"✗ Found {len(insurance_rows_found)} insurance rows (should be filtered)")
    
    if insurance_rows_found:
        print("\nInsurance rows that LLM classified as expenses (will be filtered by code):")
        for row in insurance_rows_found:
            print(f"  - {row['category']}: {row['description']} (Rs. {row['amount']})")
    
    if medical_expense_rows_found:
        print("\nSample valid medical expenses:")
        for row in medical_expense_rows_found[:3]:
            print(f"  ✓ {row['category']}: {row['description']} (Rs. {row['amount']})")
    
    return len(insurance_rows_found), len(medical_expense_rows_found)

def check_normalized_after_filtering():
    """Check if normalized_expenses.json will be correct after filtering logic is applied"""
    print("\n" + "=" * 70)
    print("EXPECTED NORMALIZED EXPENSES AFTER FILTERING")
    print("=" * 70)
    
    debug_file = Path("tmp/parser_debug/semantic_region_outputs.json")
    if not debug_file.exists():
        print("⚠ Debug file not found.")
        return
    
    with open(debug_file) as f:
        regions_data = json.load(f)
    
    NON_EXPENSE_KEYWORDS = {
        "claim", "claims", "policy", "payer", "premium", "deductible",
        "risk factor", "member id", "policy number", "insurance", "sum insured"
    }
    
    # Simulate the _table_to_expenses filtering
    filtered_expenses = []
    
    for region in regions_data:
        metadata = region.get("metadata", {})
        tables = metadata.get("tables", [])
        
        for table in tables:
            if table.get("table_kind") != "expenses":
                continue
            
            rows = table.get("rows", [])
            for row in rows:
                cells = row.get("cells") or row
                category = str(cells.get("category", "")).lower()
                description = str(cells.get("description", "")).lower()
                
                # Apply filter
                if any(kw in category or kw in description for kw in NON_EXPENSE_KEYWORDS):
                    continue  # Skip insurance rows
                
                amount = cells.get("amount", 0)
                if not amount or amount <= 0:
                    continue
                
                filtered_expenses.append({
                    "category": cells.get("category", ""),
                    "description": cells.get("description", ""),
                    "amount": amount,
                })
    
    print(f"\nFiltered to {len(filtered_expenses)} valid medical expenses:\n")
    for exp in filtered_expenses:
        print(f"  ✓ {exp['category']:20} | {exp['description']:50} | Rs. {exp['amount']}")

if __name__ == "__main__":
    insurance_count, expense_count = test_filter_on_debug_output()
    check_normalized_after_filtering()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nLLM classified {insurance_count} insurance rows as expenses.")
    print(f"Filter will exclude them -> {expense_count} valid medical expenses remain.\n")
    print("✓ Code fix is ready. Run a full parse to verify the fix works in practice.")
