#!/usr/bin/env python
"""
Diagnose the actual data flow from parser to submission service.
Checks if semantic extraction is being called and what data is reaching the renderer.

Usage:
  python scripts/diagnose_data_flow.py <claim_id>
  
Example:
  python scripts/diagnose_data_flow.py 08c8c462-25ee-4b71-ae59-863d5876157c
"""
import sys
import json
from pathlib import Path

def diagnose_claim(claim_id: str):
    """Diagnose a specific claim's data flow."""
    print("\n" + "="*80)
    print(f"DIAGNOSING DATA FLOW FOR CLAIM: {claim_id}")
    print("="*80)
    
    # Check 1: Parser outputs
    debug_dir = Path(f"tmp/parser_debug/{claim_id}")
    if not debug_dir.exists():
        print(f"\n❌ No parser debug directory: {debug_dir}")
        return
    
    print(f"\n✓ Parser debug directory found: {debug_dir}")
    
    # Check normalized fields
    normalized_fields_file = debug_dir / "normalized_fields.json"
    if normalized_fields_file.exists():
        with open(normalized_fields_file) as f:
            normalized_fields = json.load(f)
        print(f"\n✓ Normalized Fields: {len(normalized_fields)} fields")
        for field in normalized_fields[:5]:
            print(f"  - {field.get('canonical_field', 'UNKNOWN')}: {field.get('value', 'N/A')}")
        if len(normalized_fields) > 5:
            print(f"  ... and {len(normalized_fields) - 5} more")
    else:
        print(f"\n❌ No normalized_fields.json")
    
    # Check normalized expenses
    normalized_expenses_file = debug_dir / "normalized_expenses.json"
    if normalized_expenses_file.exists():
        with open(normalized_expenses_file) as f:
            normalized_expenses = json.load(f)
        print(f"\n✓ Normalized Expenses: {len(normalized_expenses)} items")
        for exp in normalized_expenses[:3]:
            amount = exp.get('amount', 'N/A')
            desc = exp.get('description', 'N/A')[:40]
            print(f"  - {desc}: Rs. {amount}")
        if len(normalized_expenses) > 3:
            print(f"  ... and {len(normalized_expenses) - 3} more")
    else:
        print(f"\n❌ No normalized_expenses.json")
    
    # Check 2: Parser canonical claim
    canonical_file = debug_dir / "canonical_claim.json"
    if canonical_file.exists():
        with open(canonical_file) as f:
            canonical = json.load(f)
        print(f"\n✓ Canonical Claim Built")
        
        # Check patient section
        patient = canonical.get("patient", {})
        print(f"\n  Patient Section:")
        print(f"    - name: {patient.get('name', 'MISSING')}")
        print(f"    - age: {patient.get('age', 'MISSING')}")
        print(f"    - sex: {patient.get('sex', 'MISSING')}")
        
        # Check hospitalization
        hosp = canonical.get("hospitalization", {})
        print(f"\n  Hospitalization Section:")
        print(f"    - hospital_name: {hosp.get('hospital_name', 'MISSING')}")
        print(f"    - doctor_name: {hosp.get('doctor_name', 'MISSING')}")
        
        # Check diagnosis
        diag = canonical.get("diagnosis", {})
        print(f"\n  Diagnosis Section:")
        print(f"    - primary: {diag.get('primary', 'MISSING')}")
        
        # Check expenses
        expenses = canonical.get("expenses", {}).get("line_items", [])
        print(f"\n  Expenses: {len(expenses)} items")
        for exp in expenses[:3]:
            print(f"    - {exp.get('description', 'N/A')[:30]}: Rs. {exp.get('amount', 'N/A')}")
    else:
        print(f"\n❌ No canonical_claim.json")
    
    # Check 3: Renderer payload
    runtime_dir = Path("tmp/parser_debug/runtime")
    renderer_file = runtime_dir / "06_renderer_input_submission.json"
    if renderer_file.exists():
        with open(renderer_file) as f:
            renderer_input = json.load(f)
        
        print(f"\n✓ Renderer Input Available")
        parsed_fields = renderer_input.get("parsed_fields", {})
        print(f"\n  Extracted Fields: {len(parsed_fields)}")
        
        critical_fields = [
            "patient_name", "age", "gender", "sex",
            "treating_doctor", "doctor_name",
            "hospital_name", "primary_diagnosis", "diagnosis"
        ]
        
        for field in critical_fields:
            value = parsed_fields.get(field, "MISSING")
            if value != "MISSING":
                print(f"    ✓ {field}: {value}")
            else:
                print(f"    ❌ {field}: MISSING")
        
        # Check expenses
        expenses = renderer_input.get("expenses", [])
        print(f"\n  Expenses: {len(expenses)} items")
        for exp in expenses[:3]:
            print(f"    - {exp.get('description', 'N/A')[:30]}: Rs. {exp.get('amount', 'N/A')}")
    else:
        print(f"\n❌ No renderer_input_submission.json")
    
    # Summary
    print("\n" + "="*80)
    print("DIAGNOSIS SUMMARY")
    print("="*80)
    
    if not normalized_fields_file.exists():
        print("\n⚠️  PROBLEM: Semantic extraction not producing normalized_fields")
        print("   - Check: Is semantic extraction being called?")
        print("   - Check: Is OpenRouter backend available?")
        print("   - Check: Are semantic regions being classified?")
    elif not renderer_file.exists():
        print("\n⚠️  PROBLEM: Renderer payload not being created")
        print("   - Check: Is submission service running?")
        print("   - Check: Is _gather_claim_data_full being called?")
    else:
        parsed_fields = renderer_input.get("parsed_fields", {})
        missing_critical = []
        for field in ["treating_doctor", "doctor_name", "age", "gender"]:
            if field not in parsed_fields or not parsed_fields[field]:
                missing_critical.append(field)
        
        if missing_critical:
            print(f"\n⚠️  PROBLEM: Critical fields missing in renderer:")
            for field in missing_critical:
                print(f"   - {field}")
            print("\n   Likely causes:")
            print("   1. Semantic extraction not extracting these field names")
            print("   2. _canonical_to_parsed_fields not recognizing field names")
            print("   3. Canonical structure not built correctly")
        else:
            print("\n✅ GOOD: All critical fields present in renderer!")
            print("   - Check final PDF report to verify they appear")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_data_flow.py <claim_id>")
        print("\nExample: python scripts/diagnose_data_flow.py 08c8c462-25ee-4b71-ae59-863d5876157c")
        sys.exit(1)
    
    diagnose_claim(sys.argv[1])
