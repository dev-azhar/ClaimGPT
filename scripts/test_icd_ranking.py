"""Test that score-ranked ICD mapping returns O80 as primary for FTND cases."""
import sys
sys.path.insert(0, ".")

from services.coding.app.icd10_rag import search_icd10_rag, _load_indices
from services.coding.app.diagnosis_extractor import extract_diagnosis_keywords, clear_cache

_load_indices()
clear_cache()

# These are the two terms the LLM outputs for "G3PILIAI 39WKS ... FTND C EPISIOTOMY"
narrative_terms = ["pregnancy in labour", "normal vaginal delivery with episiotomy"]

scored = []
seen = set()
for term in narrative_terms:
    hits = search_icd10_rag(term, max_results=2)
    for code, desc, cat, score in hits:
        if code in seen:
            continue
        seen.add(code)
        scored.append((score, code, desc))
        print(f"  term={term!r} -> {code}: {desc[:50]} (score={score:.4f})")

scored.sort(key=lambda x: -x[0])
matches = [(code, desc) for _, code, desc in scored[:4]]

print()
print("=== FINAL RANKED CODES ===")
for i, (code, desc) in enumerate(matches):
    label = "PRIMARY" if i == 0 else "secondary"
    print(f"  [{label}] {code}: {desc}")

print()
expected_primary = "O80"
actual_primary = matches[0][0] if matches else None
if actual_primary == expected_primary:
    print(f"PASS: Primary code is {actual_primary} (O80 - Encounter for full-term uncomplicated delivery)")
else:
    print(f"FAIL: Expected primary=O80, got primary={actual_primary}")
