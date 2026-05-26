"""Rebuild index and verify across diverse clinical query types."""
import sys, os
sys.path.insert(0, r"C:\Project\ClaimGPT")
os.chdir(r"C:\Project\ClaimGPT")

from services.coding.app.icd10_rag import build_index
print("Rebuilding index ...")
ok = build_index(force=True, load_after=True)
print("Build result:", ok)

if ok:
    from services.coding.app.icd10_rag import search_icd10_rag
    print()
    print("=== Broad verification ===")
    tests = [
        # Obstetric
        ("full term normal delivery", "O80"),
        ("39 weeks 2 days pregnancy in labour", "O80"),
        # Cardiac
        ("acute myocardial infarction", "I21"),
        ("heart failure", "I50"),
        # Diabetes
        ("type 2 diabetes mellitus", "E11"),
        # Respiratory
        ("pneumonia", "J18"),
        ("COPD exacerbation", "J44"),
        # Surgical
        ("acute appendicitis", "K35"),
        # Fracture
        ("fracture of femur", "S72"),
        # Infection
        ("urinary tract infection", "N39"),
    ]
    passed = 0
    for query, expected_prefix in tests:
        results = search_icd10_rag(query, max_results=5)
        top = results[0] if results else None
        top_code = top[0] if top else "none"
        ok_flag = top_code.startswith(expected_prefix)
        status = "PASS" if ok_flag else "FAIL"
        if ok_flag:
            passed += 1
        print(f"[{status}] '{query}' -> {top_code} (expected {expected_prefix}*)")
    print(f"\n{passed}/{len(tests)} passed")
