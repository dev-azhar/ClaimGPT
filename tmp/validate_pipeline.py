"""Quick validation of SNOMED stripping + cross-encoder pipeline."""
import sys, os, re
sys.path.insert(0, r"C:\Project\ClaimGPT")
os.chdir(r"C:\Project\ClaimGPT")

# ─── 1. SNOMED stripping logic test ───────────────────────────────
_SNOMED_RE = re.compile(
    r"\s*\((?:disorder|finding|procedure|observable entity|situation|"
    r"morphologic abnormality|body structure|substance|product|event|"
    r"regime/therapy|qualifier value)\)",
    flags=re.IGNORECASE,
)
cases = [
    ("Shock (disorder)",                 "Shock"),
    ("Myocardial infarction (disorder)", "Myocardial infarction"),
    ("Urinary tract infection (disorder)", "Urinary tract infection"),
    ("Type 2 diabetes mellitus (disorder)", "Type 2 diabetes mellitus"),
    ("Normal delivery (finding)",         "Normal delivery"),
    ("Pneumonia (disorder)",              "Pneumonia"),
    ("Fracture of femur (disorder)",      "Fracture of femur"),
    ("Normal delivery",                   "Normal delivery"),   # no tag → unchanged
]
print("=== SNOMED tag stripping ===")
all_ok = True
for inp, expected in cases:
    result = _SNOMED_RE.sub("", inp).strip()
    ok = result == expected
    if not ok:
        all_ok = False
    print(f"  [{'OK' if ok else 'FAIL'}] '{inp}' → '{result}'")
print()

# ─── 2. RAG search after SNOMED stripping ─────────────────────────
from services.coding.app.icd10_rag import search_icd10_rag, is_rag_available
print("RAG available:", is_rag_available())
print()
print("=== RAG + cross-encoder with SNOMED-stripped queries ===")
tests = [
    ("shock",                     "R57"),
    ("myocardial infarction",     "I21"),
    ("urinary tract infection",   "N39"),
    ("type 2 diabetes mellitus",  "E11"),
    ("pneumonia",                 "J18"),
    ("fracture of femur",         "S72"),
    ("spontaneous vertex delivery", "O80"),
    ("acute appendicitis",        "K35"),
]
passed = 0
for query, expected in tests:
    results = search_icd10_rag(query, max_results=5)
    top = results[0] if results else None
    top_code = top[0] if top else "none"
    ok = top_code.startswith(expected)
    if ok:
        passed += 1
    status = "PASS" if ok else "FAIL"
    confidence = top[3] if top else 0
    print(f"  [{status}] '{query}' → {top_code} (expected {expected}*, conf={confidence:.3f})")

print(f"\n{passed}/{len(tests)} passed")
