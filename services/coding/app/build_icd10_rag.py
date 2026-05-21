"""Build and query a RAG index for the ICD-10 PDF.

Usage:
  - Run this file as a script to (re)build the index and run a small local test.
  - Import `retrieve_icd_codes_for_query` to map free-text diagnoses to ICD codes
    by retrieving the nearest passages from the ICD-10 PDF and extracting codes.
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Tuple

import faiss
import numpy as np
import pdfplumber
from sentence_transformers import SentenceTransformer


BASE = os.path.dirname(__file__)
RAG_DATA_DIR = os.path.join(BASE, "rag_data")
INPUT_PDF = os.path.join(RAG_DATA_DIR, "input", "icd-10-medical-diagnosis-codes.pdf")
INDEX_PATH = os.path.join(RAG_DATA_DIR, "icd10_index.faiss")
META_PATH = os.path.join(RAG_DATA_DIR, "icd10_meta.json")


def extract_chunks_from_pdf(pdf_path: str, chunk_chars: int = 400) -> List[dict]:
    chunks = []
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        for p, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            # split into lines and join nearby lines to form chunk_chars-sized chunks
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            cur = []
            cur_len = 0
            for ln in lines:
                if cur_len + len(ln) > chunk_chars and cur:
                    chunk_text = " ".join(cur)
                    chunks.append({"text": chunk_text, "page": p})
                    cur = [ln]
                    cur_len = len(ln)
                else:
                    cur.append(ln)
                    cur_len += len(ln)
            if cur:
                chunks.append({"text": " ".join(cur), "page": p})
    return chunks


_ICD_REGEX = re.compile(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-Za-z]+)?\b")


def extract_icd_codes(text: str) -> List[str]:
    # Return unique codes found in text (uppercased)
    found = [m.group(0).upper() for m in _ICD_REGEX.finditer(text)]
    # Normalize by stripping trailing punctuation
    found = [f.rstrip('.,;:') for f in found]
    return list(dict.fromkeys(found))


def build_index(model_name: str = "all-MiniLM-L6-v2") -> Tuple[faiss.IndexFlatIP, List[dict]]:
    print("Extracting chunks from PDF...", INPUT_PDF)
    chunks = extract_chunks_from_pdf(INPUT_PDF)
    print(f"Got {len(chunks)} chunks")

    model = SentenceTransformer(model_name)
    emb = model.encode([c["text"] for c in chunks], show_progress_bar=True, convert_to_numpy=True)

    # Normalize embeddings for cosine similarity with inner product
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb = emb / norms

    dim = emb.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(emb.astype("float32"))

    # Prepare metadata (include extracted ICD codes per chunk)
    meta = []
    for c in chunks:
        meta.append({"text": c["text"], "page": c["page"], "codes": extract_icd_codes(c["text"])})

    # persist index and meta
    faiss.write_index(index, INDEX_PATH)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("Index built and saved.")
    return index, meta


def load_index_and_meta() -> Tuple[faiss.IndexFlatIP, List[dict], SentenceTransformer]:
    if not os.path.exists(INDEX_PATH) or not os.path.exists(META_PATH):
        raise FileNotFoundError("Index or metadata missing — run build_index() first")
    index = faiss.read_index(INDEX_PATH)
    with open(META_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)
    model = SentenceTransformer("all-MiniLM-L6-v2")
    return index, meta, model


def retrieve_icd_codes_for_query(query: str, top_k: int = 5) -> List[Tuple[str, float, str]]:
    index, meta, model = load_index_and_meta()
    q_emb = model.encode([query], convert_to_numpy=True)
    q_emb = q_emb / np.linalg.norm(q_emb, axis=1, keepdims=True)
    D, I = index.search(q_emb.astype("float32"), top_k)
    results = []
    for score, idx in zip(D[0], I[0]):
        if idx < 0 or idx >= len(meta):
            continue
        entry = meta[idx]
        # prefer explicit codes extracted from passage; if none, return passage snippet
        codes = entry.get("codes", [])
        if codes:
            for c in codes:
                results.append((c, float(score), entry["text"]))
        else:
            results.append((None, float(score), entry["text"]))
    return results


if __name__ == "__main__":
    # Build index (overwrites existing)
    idx, meta = build_index()

    # Quick test mapping — you can change these inputs
    test_queries = [
        "Dental caries, unspecified",
        "Chronic gingivitis, plaque induced",
        "pregnancy in labour 39wks episiotomy",
    ]
    for q in test_queries:
        print('\nQUERY:', q)
        res = retrieve_icd_codes_for_query(q, top_k=5)
        for code, score, text in res[:10]:
            print(f"  code={code} score={score:.3f} snippet={text[:120]!r}")
