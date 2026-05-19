import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Ensure the SBERT model is used for this process
os.environ['CODING_EMBEDDING_MODEL'] = 'sentence-transformers/all-mpnet-base-v2'
print('CODING_EMBEDDING_MODEL=', os.environ['CODING_EMBEDDING_MODEL'])

from services.coding.app import icd10_rag

# Force load model and report
model = icd10_rag._load_model()
try:
    name = getattr(model, 'name_or_path', None) or getattr(model, 'model_name', None)
except Exception:
    name = str(type(model))
print('Loaded embed model:', name)

queries = [
    'normal vaginal delivery with episiotomy',
    'Patient in labour at 39 weeks; normal vaginal delivery performed with episiotomy and repair of perineal laceration',
    'normal vaginal delivery; episiotomy; perineal laceration; repair'
]

for q in queries:
    print('\nQUERY:', q)
    res = icd10_rag.search_icd10_rag(q, max_results=10, mode='dense')
    for r in res:
        print(r)
