import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Use a proven SBERT model for dense embeddings
os.environ['CODING_EMBEDDING_MODEL'] = 'sentence-transformers/all-mpnet-base-v2'
print('Set CODING_EMBEDDING_MODEL=', os.environ['CODING_EMBEDDING_MODEL'])

from services.coding.app.icd10_rag import build_index

build_index(force=True, load_after=True)
print('Rebuild with SBERT complete')
