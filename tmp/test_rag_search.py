import sys
sys.path.insert(0, '.')
import os
os.chdir(r'C:\Project\ClaimGPT')

from services.coding.app.icd10_rag import search_icd10_rag, is_rag_available

print("RAG available:", is_rag_available())
print()

# LLM output terms from the log
terms = [
    "39 weeks 2 days pregnancy in labour",
    "full term normal delivery",
    "G3P1L1A1 39WKS 2DAYS PREGNANCY IN LABOUR",
    "G3PILIAI 39WKS ZDAYS PREGNANCY IN LABOUR",
    "pregnancy in labour",
    "ftnd episiotomy",
]

for term in terms:
    print(f"Query: '{term}'")
    results = search_icd10_rag(term, max_results=5)
    for code, desc, cat, score in results:
        print(f"  [{score:.4f}] {code} | {desc}")
    print()
