import os
import sys
from pathlib import Path
# Ensure project root is on sys.path so `services` package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ['CLINICAL_EMBED_MODEL'] = 'emilyalsentzer/Bio_ClinicalBERT'
from services.coding.app.icd10_rag import search_icd10_rag

q = 'normal vaginal delivery with episiotomy'
res = search_icd10_rag(q, max_results=10, mode='dense')
print('QUERY:', q)
for r in res:
    print(r)
