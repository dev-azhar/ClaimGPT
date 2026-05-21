import sys, os
sys.path.insert(0, r"C:\Project\ClaimGPT")
os.chdir(r"C:\Project\ClaimGPT")
os.environ["PYTHONIOENCODING"] = "utf-8"

from services.coding.app.icd10_rag import search_icd10_rag, is_rag_available

print("RAG available:", is_rag_available())
print()
print("=== Post-rebuild verification ===")

tests = [
    "39 weeks 2 days pregnancy in labour",
    "full term normal delivery",
    "pregnancy in labour",
    "G3P1L1A1 39WKS 2DAYS PREGNANCY IN LABOUR",
    "ftnd episiotomy",
]

for q in tests:
    results = search_icd10_rag(q, max_results=5)
    top = results[0] if results else None
    status = "PASS O80" if top and top[0].startswith("O80") else ("FAIL got " + (top[0] if top else "nothing"))
    print(f"[{status}] '{q}'")
    for code, desc, _cat, score in results:
        marker = " <-- TOP" if code == (top[0] if top else "") else ""
        print(f"       [{score:.4f}] {code} | {desc}{marker}")
    print()
