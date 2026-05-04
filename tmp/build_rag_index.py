import logging
logging.basicConfig(level=logging.INFO)

from services.coding.app.icd10_rag import build_index

print("Building FAISS index with ALL ICD-10-CM codes...")
ok = build_index(force=True)
print(f"Build result: {ok}")
