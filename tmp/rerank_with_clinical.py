import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.coding.app.icd10_rag import search_icd10_rag
from sentence_transformers import SentenceTransformer
import numpy as np

os.environ['CLINICAL_EMBED_MODEL'] = os.environ.get('CLINICAL_EMBED_MODEL','emilyalsentzer/Bio_ClinicalBERT')
clinical_name = os.environ['CLINICAL_EMBED_MODEL']

query = 'normal vaginal delivery with episiotomy'

# Get a wide candidate pool from dense index
candidates = search_icd10_rag(query, max_results=200, mode='dense')
print(f'Got {len(candidates)} dense candidates')

# Load clinical wrapper
print('Loading clinical model:', clinical_name)
clinical = SentenceTransformer(clinical_name)

texts = [query] + [f"{desc} | {cat}" for (code, desc, cat, _score) in candidates]
embs = clinical.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
q = embs[0]

sims = []
for i, (code, desc, cat, _score) in enumerate(candidates):
    sim = float(np.dot(q, embs[i+1]))
    sims.append((sim, code, desc, cat))

sims.sort(reverse=True)
print('\nTop 20 by clinical similarity:')
for sim, code, desc, cat in sims[:20]:
    print(f"{code}: {desc} | sim={sim:.4f}")

# Check if O80 is in top 20
in_top = any(code.startswith('O80') for _, code, _, _ in sims[:20])
print('\nO80 in top20?', in_top)
