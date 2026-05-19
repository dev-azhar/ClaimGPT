import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.coding.app.icd10_rag import search_icd10_rag

queries = {
    'short_phrase': 'normal vaginal delivery with episiotomy',
    'full_diagnosis': 'Patient in labour at 39 weeks; normal vaginal delivery performed with episiotomy and repair of perineal laceration',
    'aggregated_phrases': 'normal vaginal delivery; episiotomy; perineal laceration; repair'
}

for name, q in queries.items():
    print('\n===', name, '===')
    res = search_icd10_rag(q, max_results=10, mode='dense')
    for r in res:
        print(r)
