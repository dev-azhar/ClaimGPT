import logging, sys
logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, "/Users/azhar/claimgpt")
from services.coding.app.icd10_rag import search_icd10_rag, search_cpt_rag, is_rag_available

print(f"RAG available: {is_rag_available()}")
print()

queries = [
    "heart attack",
    "diabetes with kidney complications",
    "dengue fever",
    "knee replacement surgery",
    "breast cancer",
    "asthma exacerbation",
    "appendicitis",
    "stroke cerebrovascular accident",
    "chronic obstructive pulmonary disease",
    "rheumatoid arthritis",
    "major depressive disorder",
    "urinary tract infection",
    "congestive heart failure",
    "deep vein thrombosis",
    "peptic ulcer disease",
    "diabetic retinopathy",
    "tension pneumothorax",
    "anaphylactic shock",
    "polycystic ovarian syndrome",
    "guillain barre syndrome",
]

for q in queries:
    results = search_icd10_rag(q, max_results=3)
    print(f'Query: "{q}"')
    for code, desc, cat, score in results:
        print(f"  {code:12s} | {desc[:70]:70s} | {cat:15s} | {score:.3f}")
    print()

print("--- CPT Search ---")
cpt_queries = ["coronary bypass", "appendectomy", "knee arthroscopy", "total hip replacement", "ct scan abdomen"]
for q in cpt_queries:
    results = search_cpt_rag(q, max_results=3)
    print(f'Query: "{q}"')
    for code, desc, cat, score in results:
        print(f"  {code:12s} | {desc[:70]:70s} | {cat:15s} | {score:.3f}")
    print()
